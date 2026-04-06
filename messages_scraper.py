"""
Navigate to Malt /messages and list conversations
that have pending offers waiting for a reply.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from playwright.async_api import Page

from malt_selectors import Selectors

logger = logging.getLogger("malt_bot.scraper")


@dataclass
class ThreadInfo:
    """Lightweight descriptor for a conversation thread seen in the sidebar."""
    index: int
    title: str
    snippet: str
    is_pending_reply: bool
    raw_element_index: int


async def _is_session_valid(page: Page) -> bool:
    """Return True if we are logged in (not redirected to login/signin)."""
    url_lower = page.url.lower()
    if "login" in url_lower or "signin" in url_lower:
        return False
    indicator = await page.query_selector(Selectors.LOGGED_IN_INDICATOR)
    return indicator is not None


_SCROLL_JS = """() => {
    const items = document.querySelectorAll('li[class*="summary__wrapper"]');
    if (items.length === 0) return {scrolled: false, atBottom: true};
    let el = items[0].parentElement;
    while (el) {
        const s = getComputedStyle(el);
        if (s.overflowY === 'auto' || s.overflowY === 'scroll'
            || s.overflow === 'auto' || s.overflow === 'scroll') {
            const before = el.scrollTop;
            el.scrollTop = el.scrollHeight;
            const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 10;
            return {scrolled: el.scrollTop > before, atBottom};
        }
        el = el.parentElement;
    }
    return {scrolled: false, atBottom: true};
}"""


async def _scroll_sidebar_to_bottom(page: Page, max_scrolls: int = 50):
    """
    Scroll the conversation sidebar until no new items load AND
    the scroll container is at the bottom.
    Malt lazy-loads ~10 items per scroll.
    """
    prev_count = 0
    stale_rounds = 0

    for i in range(max_scrolls):
        items = await page.query_selector_all(Selectors.CONVERSATION_ITEM)
        count = len(items)

        result = await page.evaluate(_SCROLL_JS)
        at_bottom = result.get("atBottom", False)
        did_scroll = result.get("scrolled", False)

        if count > prev_count:
            stale_rounds = 0
            prev_count = count
        else:
            stale_rounds += 1

        # Only stop if scroll is at the bottom AND no new items after 2 tries
        if at_bottom and stale_rounds >= 2:
            break
        # Also stop if we can't scroll and nothing new appeared
        if not did_scroll and stale_rounds >= 2:
            break

        await page.wait_for_timeout(2000)

    final = await page.query_selector_all(Selectors.CONVERSATION_ITEM)
    logger.info(
        "Sidebar fully loaded: %d conversations (%d scroll(s))",
        len(final), i + 1,
    )
    return final


async def _find_pending_threads_by_text(page: Page) -> list[int]:
    """
    Scroll the sidebar to load ALL conversations, then find ones
    marked 'En attente de votre réponse' / 'postulez'.
    """
    all_items = await _scroll_sidebar_to_bottom(page)

    if not all_items:
        logger.warning("No conversation items found after scrolling.")
        all_items = await page.query_selector_all("a[href*='/messages/']")

    pending_indices: list[int] = []

    for idx, item in enumerate(all_items):
        try:
            text = await item.inner_text()
        except Exception:
            continue

        text_lower = text.lower()

        if "en attente de modération" in text_lower or "candidature envoyée" in text_lower:
            continue

        for pattern in Selectors.PENDING_REPLY_TEXTS_ALT:
            if pattern.lower() in text_lower:
                pending_indices.append(idx)
                break

    return pending_indices


async def list_new_offer_threads(page: Page) -> tuple[list[ThreadInfo], bool]:
    """
    Navigate to /messages, scroll sidebar to load ALL conversations,
    and return (threads, session_ok).
    """
    if "/messages" not in page.url:
        logger.info("Navigating to https://www.malt.fr/messages ...")
        await page.goto(
            "https://www.malt.fr/messages",
            wait_until="domcontentloaded",
        )
    else:
        logger.info("Already on messages page: %s", page.url)

    for attempt in range(3):
        await page.wait_for_timeout(3000)
        if await _is_session_valid(page):
            break
        logger.debug(
            "Session check attempt %d/3 — url: %s", attempt + 1, page.url,
        )
    else:
        logger.error(
            "Session invalid (url: %s). "
            "Log in to Malt in your Chrome, then run again.",
            page.url,
        )
        return [], False

    pending_indices = await _find_pending_threads_by_text(page)

    if not pending_indices:
        logger.info("No pending-reply conversations found.")
        return [], True

    # Re-query after scroll to get the full list
    all_items = await page.query_selector_all(Selectors.CONVERSATION_ITEM)

    threads: list[ThreadInfo] = []
    for rank, idx in enumerate(pending_indices):
        if idx >= len(all_items):
            continue
        item = all_items[idx]
        try:
            full_text = await item.inner_text()
        except Exception:
            full_text = ""

        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        title = lines[0] if lines else f"Thread #{idx}"
        snippet = " ".join(lines[1:3]) if len(lines) > 1 else ""

        threads.append(ThreadInfo(
            index=rank,
            title=title,
            snippet=snippet,
            is_pending_reply=True,
            raw_element_index=idx,
        ))

    logger.info("Found %d pending offer thread(s) (out of %d total)", len(threads), len(all_items))
    return threads, True


async def open_thread(page: Page, thread: ThreadInfo) -> bool:
    """
    Click a conversation thread in the sidebar to open it.
    Scrolls the sidebar if needed to reach the target item.
    Returns True if the right panel loaded successfully.
    """
    idx = thread.raw_element_index

    # Wait for initial items then scroll until our target index is reachable
    for attempt in range(30):
        all_items = await page.query_selector_all(Selectors.CONVERSATION_ITEM)
        if len(all_items) > idx:
            break
        # Scroll sidebar to load more items
        await page.evaluate(_SCROLL_JS)
        await page.wait_for_timeout(1500)
    else:
        all_items = await page.query_selector_all(Selectors.CONVERSATION_ITEM)

    if idx >= len(all_items):
        logger.error(
            "Thread index %d out of range (%d items after scrolling)",
            idx, len(all_items),
        )
        return False

    item = all_items[idx]

    # Scroll the item into view before clicking
    try:
        await item.scroll_into_view_if_needed()
        await page.wait_for_timeout(500)
        await item.click()
    except Exception as exc:
        logger.error("Failed to click thread %d: %s", idx, exc)
        return False

    await page.wait_for_timeout(2000)

    return True
