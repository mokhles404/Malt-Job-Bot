"""
Malt Auto-Apply Bot -- main orchestration script.

Connects to your real Chrome browser via CDP so the session, cookies,
and TLS fingerprint are exactly the same as when you browse normally.
No separate browser, no bot detection.

Flow per offer:
    1.  /messages  → click conversation in sidebar
    2.  /messages/client-project-offer/<id>  → click "Postuler"
    3.  /client/sourcing-projects/application-funnel/<id>/apply  → fill form
    4.  Submit  → back to /messages → next offer

Usage:
    python malt_bot.py              # Single run
    python malt_bot.py --loop 300   # Run every 300 seconds (5 min)
    python malt_bot.py --funnel URL # Fill one specific funnel page
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import sys
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

from chrome_cdp import ensure_chrome_with_cdp
from form_filler import (
    can_apply_today,
    get_daily_count,
    increment_daily_count,
    is_already_handled,
    mark_as_handled,
)
from funnel_filler import fill_funnel_form
from messages_scraper import list_new_offer_threads, open_thread

load_dotenv()

CONFIG_FILE = "config.yaml"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)

    fh = logging.FileHandler(log_dir / "malt_bot.log", encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(fh)


logger = logging.getLogger("malt_bot")


def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        logger.warning("Config file %s not found, using defaults.", CONFIG_FILE)
        return {}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_funnel_url(url: str) -> bool:
    return "/application-funnel/" in url and "/apply" in url


async def _click_postuler(page: Page) -> bool:
    """
    On a /messages/client-project-offer/<id> page, find and click the
    "Postuler" button which navigates to the application-funnel form.
    Returns True if we landed on the funnel page.
    """
    for pattern in ["Postuler", "postuler", "Apply"]:
        try:
            locator = page.get_by_role("button", name=pattern, exact=False)
            if await locator.count() > 0:
                first = locator.first
                if await first.is_visible():
                    logger.info("Clicking '%s' button ...", pattern)
                    await first.click()
                    await page.wait_for_timeout(5000)
                    if _is_funnel_url(page.url):
                        logger.info("Navigated to funnel: %s", page.url)
                        return True
                    logger.warning(
                        "Clicked Postuler but did not land on funnel (url=%s)",
                        page.url,
                    )
                    return False
        except Exception:
            continue

    # Fallback: try links containing "postuler"
    for el in await page.query_selector_all("a, button"):
        try:
            if not await el.is_visible():
                continue
            text = (await el.inner_text()).strip().lower()
            if "postuler" in text:
                await el.click()
                await page.wait_for_timeout(5000)
                if _is_funnel_url(page.url):
                    logger.info("Navigated to funnel via fallback: %s", page.url)
                    return True
        except Exception:
            continue

    logger.warning("No 'Postuler' button found on this page")
    return False


async def _has_postuler_button(page: Page) -> bool:
    """Return True if a visible 'Postuler' button exists on the offer page."""
    for pattern in ["Postuler", "postuler", "Apply"]:
        try:
            locator = page.get_by_role("button", name=pattern, exact=False)
            if await locator.count() > 0 and await locator.first.is_visible():
                return True
        except Exception:
            continue
    return False


async def _has_discuter_button(page: Page) -> bool:
    """Return True if 'Discuter du projet' button is visible."""
    try:
        loc = page.get_by_role("button", name="Discuter du projet", exact=False)
        return await loc.count() > 0 and await loc.first.is_visible()
    except Exception:
        return False


async def _handle_discuter_flow(page: Page) -> bool:
    """
    Handle the 'Discuter du projet' flow:
      1. Click 'Discuter du projet' to open the proposal textarea
      2. Fill the textarea with the right pitch
      3. Click 'Discuter du projet' again to submit
    Returns True on success.
    """
    from funnel_filler import classify_project, _load_config, ProjectType
    from funnel_filler import PITCH_MOBILE, PITCH_WEB, PITCH_GENERAL

    pitches = {
        ProjectType.GENERAL: PITCH_GENERAL,
        ProjectType.MOBILE: PITCH_MOBILE,
        ProjectType.WEB: PITCH_WEB,
    }

    # Classify project from page content
    body_text = await page.inner_text("body")
    ptype, m, w = classify_project(body_text)
    pitch = pitches[ptype]
    logger.info("Discuter flow — classified as %s (mob=%d web=%d)", ptype.name, m, w)

    # Step 1: Click 'Discuter du projet' to open the proposal area
    discuter = page.get_by_role("button", name="Discuter du projet", exact=False)
    await discuter.first.click()
    logger.info("Clicked 'Discuter du projet' — opening proposal area ...")
    await page.wait_for_timeout(2000)

    # Step 2: Find the proposal textarea (the wider one that appeared)
    textareas = await page.query_selector_all(
        'textarea[placeholder*="Ecrivez"]'
    )
    target_ta = None
    best_width = 0
    for ta in textareas:
        if not await ta.is_visible():
            continue
        bb = await ta.bounding_box()
        if bb and bb["width"] > best_width:
            best_width = bb["width"]
            target_ta = ta

    if not target_ta:
        logger.error("No visible textarea found after clicking Discuter")
        return False

    # Fill the pitch
    await target_ta.click()
    await target_ta.fill(pitch)
    logger.info("Filled proposal textarea (%d chars, %s pitch)", len(pitch), ptype.name)

    # Step 3: Click 'Discuter du projet' again to submit
    await page.wait_for_timeout(2000)

    submit = await page.query_selector(
        'button[data-testid="project-proposal-area-submit"]'
    )
    if not submit or not await submit.is_visible():
        submit = page.get_by_role("button", name="Discuter du projet", exact=False)
        if await submit.count() > 0:
            submit = submit.first
        else:
            logger.error("Submit button not found for Discuter flow")
            return False

    await submit.click()
    logger.info("Clicked submit for Discuter flow")
    await page.wait_for_timeout(3000)

    logger.info("Discuter du projet — message sent!")
    return True


# ---------------------------------------------------------------------------
# Main bot logic
# ---------------------------------------------------------------------------

async def run_funnel(page_url: str | None = None):
    """Fill and submit a single application-funnel form."""
    cdp_url = ensure_chrome_with_cdp(
        start_url=page_url or "https://www.malt.fr/messages",
    )

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        logger.info("Waiting for page to load ...")
        for _ in range(15):
            url = page.url
            if _is_funnel_url(url):
                break
            if "signin" not in url.lower() and "login" not in url.lower():
                break
            await page.wait_for_timeout(2000)

        if page_url and not _is_funnel_url(page.url):
            logger.info("Navigating to funnel page: %s", page_url)
            await page.goto(page_url, wait_until="domcontentloaded")
            await page.wait_for_timeout(4000)

        if "signin" in page.url.lower() or "login" in page.url.lower():
            logger.error(
                "Session invalid (redirected to %s). "
                "Log in to Malt in Chrome first.",
                page.url,
            )
            return

        logger.info("Page ready: %s", page.url)
        success = await fill_funnel_form(page, auto_submit=True)
        if success:
            logger.info("Funnel application completed!")
        else:
            logger.error("Funnel application failed.")


async def run_once():
    """
    Single pass:
      1. List pending offers in /messages sidebar
      2. For each: click thread → click Postuler → fill funnel form → submit
    """
    config = load_config()

    max_per_run = int(os.getenv("MAX_APPLICATIONS_PER_RUN", 5))
    max_per_day = int(os.getenv("MAX_APPLICATIONS_PER_DAY", 10))
    throttle = config.get("throttle", {})
    delay_min = throttle.get("delay_between_offers_min", 2)
    delay_max = throttle.get("delay_between_offers_max", 5)

    if not can_apply_today(max_per_day):
        logger.info(
            "Daily limit reached (%d/%d). Skipping.",
            get_daily_count(), max_per_day,
        )
        return

    cdp_url = ensure_chrome_with_cdp()
    applications_this_run = 0

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = (
            browser.contexts[0] if browser.contexts
            else await browser.new_context()
        )
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        # If Chrome already shows a funnel page, handle it immediately
        if _is_funnel_url(page.url):
            logger.info("Detected funnel page already open: %s", page.url)
            await fill_funnel_form(page, auto_submit=True)
            return

        # Navigate to messages
        logger.info("Navigating to messages ...")
        await page.goto(
            "https://www.malt.fr/messages",
            wait_until="domcontentloaded",
        )
        await page.wait_for_timeout(4000)
        logger.info("Page ready: %s", page.url)

        try:
            threads, session_ok = await list_new_offer_threads(page)

            if not session_ok:
                logger.error(
                    "Session invalid. Log in to Malt in Chrome, then rerun."
                )
                return

            if not threads:
                logger.info("No pending offers found.")
                return

            for thread in threads:
                if applications_this_run >= max_per_run:
                    logger.info("Per-run limit reached (%d).", max_per_run)
                    break
                if not can_apply_today(max_per_day):
                    logger.info("Daily limit reached (%d).", max_per_day)
                    break

                logger.info(
                    "━━━ Thread %d/%d: %s ━━━",
                    thread.index + 1,
                    len(threads),
                    thread.snippet[:60] or thread.title[:60],
                )

                # ── Step 1: go back to /messages ──
                await page.goto(
                    "https://www.malt.fr/messages",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(2000)

                # ── Step 2: click the conversation in the sidebar ──
                opened = await open_thread(page, thread)
                if not opened:
                    logger.warning("Could not open thread, skipping.")
                    continue

                offer_url = page.url
                logger.info("Opened offer page: %s", offer_url)

                # Skip if already handled
                if is_already_handled(offer_url):
                    logger.info("Already handled, skipping.")
                    continue

                # ── Step 3: apply via Postuler or Discuter du projet ──
                has_postuler = await _has_postuler_button(page)
                has_discuter = await _has_discuter_button(page)

                if not has_postuler and not has_discuter:
                    logger.info(
                        "No 'Postuler' or 'Discuter' button — "
                        "already applied or expired. Marking handled."
                    )
                    mark_as_handled(offer_url)
                    continue

                success = False

                if has_postuler:
                    landed = await _click_postuler(page)
                    if not landed:
                        logger.warning("Could not reach funnel page, skipping.")
                        continue
                    success = await fill_funnel_form(page, auto_submit=True)

                elif has_discuter:
                    success = await _handle_discuter_flow(page)
                if success:
                    applications_this_run += 1
                    mark_as_handled(offer_url)
                    increment_daily_count()
                    logger.info(
                        "✓ Application %d/%d sent",
                        applications_this_run, max_per_run,
                    )
                else:
                    logger.warning("Form filling failed for this offer.")

                # Throttle between offers
                delay = random.uniform(delay_min, delay_max)
                logger.info("Waiting %.1f s before next offer ...", delay)
                await page.wait_for_timeout(int(delay * 1000))

        except Exception as exc:
            logger.exception("Unexpected error: %s", exc)

    logger.info(
        "Run complete. Applied to %d offer(s). Daily total: %d/%d",
        applications_this_run, get_daily_count(), max_per_day,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Malt Auto-Apply Bot")
    parser.add_argument(
        "--loop", type=int, default=0,
        help="Re-run every N seconds (e.g. --loop 300 for 5 min).",
    )
    parser.add_argument(
        "--funnel", type=str, default="",
        help="Fill a single application-funnel URL directly.",
    )
    args = parser.parse_args()

    setup_logging()

    if args.funnel:
        logger.info("Funnel mode: %s", args.funnel)
        asyncio.run(run_funnel(args.funnel))
        return

    if args.loop > 0:
        logger.info("Loop mode (every %d s)", args.loop)
        while True:
            try:
                asyncio.run(run_once())
            except KeyboardInterrupt:
                logger.info("Interrupted. Exiting.")
                break
            except Exception as exc:
                logger.exception("Run failed: %s", exc)

            jitter = random.randint(0, min(30, args.loop // 5))
            sleep_time = args.loop + jitter
            logger.info("Sleeping %d s ...", sleep_time)
            try:
                time.sleep(sleep_time)
            except KeyboardInterrupt:
                logger.info("Interrupted. Exiting.")
                break
    else:
        asyncio.run(run_once())


if __name__ == "__main__":
    main()
