"""
Fill the Malt proposal/application form and submit it.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path

from playwright.async_api import Page

from offer_analyzer import Offer
from malt_selectors import Selectors

logger = logging.getLogger("malt_bot.filler")

HANDLED_FILE = "handled_threads.json"
DAILY_COUNTER_FILE = "daily_counter.json"


# ---------------------------------------------------------------------------
# Handled threads tracking
# ---------------------------------------------------------------------------

def _load_handled() -> set[str]:
    if not os.path.exists(HANDLED_FILE):
        return set()
    with open(HANDLED_FILE) as f:
        data = json.load(f)
    return set(data)


def _save_handled(handled: set[str]):
    with open(HANDLED_FILE, "w") as f:
        json.dump(sorted(handled), f, indent=2)


def is_already_handled(conversation_url: str) -> bool:
    return conversation_url in _load_handled()


def mark_as_handled(conversation_url: str):
    handled = _load_handled()
    handled.add(conversation_url)
    _save_handled(handled)


# ---------------------------------------------------------------------------
# Daily application counter
# ---------------------------------------------------------------------------

def _load_daily_counter() -> dict:
    if not os.path.exists(DAILY_COUNTER_FILE):
        return {"date": "", "count": 0}
    with open(DAILY_COUNTER_FILE) as f:
        return json.load(f)


def _save_daily_counter(data: dict):
    with open(DAILY_COUNTER_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_daily_count() -> int:
    data = _load_daily_counter()
    today = date.today().isoformat()
    if data.get("date") != today:
        return 0
    return data.get("count", 0)


def increment_daily_count():
    today = date.today().isoformat()
    data = _load_daily_counter()
    if data.get("date") != today:
        data = {"date": today, "count": 0}
    data["count"] = data.get("count", 0) + 1
    _save_daily_counter(data)


def can_apply_today(max_per_day: int) -> bool:
    return get_daily_count() < max_per_day


# ---------------------------------------------------------------------------
# Form filling
# ---------------------------------------------------------------------------

async def _find_textarea(page: Page):
    """Find the proposal message textarea using multiple strategies."""
    for sel in Selectors.PROPOSAL_TEXTAREA.split(","):
        sel = sel.strip()
        el = await page.query_selector(sel)
        if el:
            visible = await el.is_visible()
            if visible:
                return el

    # Fallback: any visible textarea
    textareas = await page.query_selector_all("textarea")
    for ta in textareas:
        if await ta.is_visible():
            return ta

    return None


async def _find_rate_input(page: Page):
    """Find the daily rate input field."""
    for sel in Selectors.DAILY_RATE_INPUT.split(","):
        sel = sel.strip()
        el = await page.query_selector(sel)
        if el and await el.is_visible():
            return el
    return None


async def _find_submit_button(page: Page):
    """Find the send/submit/postuler button."""
    # Strategy 1: CSS selector
    for sel in Selectors.SUBMIT_BUTTON.split(","):
        sel = sel.strip()
        el = await page.query_selector(sel)
        if el and await el.is_visible():
            return el

    # Strategy 2: button text matching
    for text_pattern in Selectors.SUBMIT_BUTTON_TEXT_PATTERNS:
        try:
            locator = page.get_by_role("button", name=text_pattern, exact=False)
            count = await locator.count()
            if count > 0:
                first = locator.first
                if await first.is_visible():
                    return first
        except Exception:
            continue

    # Strategy 3: any visible button with submit-like text
    buttons = await page.query_selector_all("button")
    for btn in buttons:
        try:
            text = (await btn.inner_text()).strip().lower()
            if any(p.lower() in text for p in Selectors.SUBMIT_BUTTON_TEXT_PATTERNS):
                if await btn.is_visible():
                    return btn
        except Exception:
            continue

    return None


async def _click_postuler(page: Page) -> bool:
    """
    Click the initial 'Postuler' button that opens the application form.
    Returns True if the form appeared after clicking.
    """
    postuler_btn = None

    # Strategy 1: button with exact "Postuler" text
    for pattern in ["Postuler", "postuler", "Apply"]:
        try:
            locator = page.get_by_role("button", name=pattern, exact=False)
            if await locator.count() > 0:
                first = locator.first
                if await first.is_visible():
                    postuler_btn = first
                    break
        except Exception:
            continue

    # Strategy 2: link/button containing "Postuler"
    if not postuler_btn:
        buttons = await page.query_selector_all("button, a")
        for btn in buttons:
            try:
                text = (await btn.inner_text()).strip().lower()
                if "postuler" in text and await btn.is_visible():
                    postuler_btn = btn
                    break
            except Exception:
                continue

    if not postuler_btn:
        logger.error("Could not find 'Postuler' button on the offer page")
        return False

    logger.info("Clicking 'Postuler' to open application form ...")
    await postuler_btn.click()
    await page.wait_for_timeout(3000)
    return True


async def fill_and_submit(
    page: Page,
    offer: Offer,
    cover_letter: str,
    config: dict,
) -> bool:
    """
    Click Postuler, fill the application form, and submit.
    Returns True if submission appeared successful.
    """
    throttle = config.get("throttle", {})
    delay_before_send = throttle.get("delay_before_send", 3)
    preferred_rate = int(os.getenv("PREFERRED_DAILY_RATE", config.get("budget", {}).get("min_daily", 500)))

    # --- Step 1: Click Postuler to open the form ---
    if not await _click_postuler(page):
        return False

    # --- Step 2: Fill message textarea (if present) ---
    textarea = await _find_textarea(page)
    if textarea:
        await textarea.click()
        await textarea.fill(cover_letter)
        logger.info("Filled cover letter (%d chars)", len(cover_letter))
    else:
        logger.info("No textarea found after Postuler — continuing without cover letter")

    # --- Step 3: Fill daily rate (if field exists) ---
    rate_input = await _find_rate_input(page)
    if rate_input:
        await rate_input.click()
        await rate_input.fill("")
        await rate_input.fill(str(preferred_rate))
        logger.info("Set daily rate to %d", preferred_rate)

    # --- Log what we're about to send ---
    logger.info("=" * 50)
    logger.info("ABOUT TO SUBMIT APPLICATION")
    logger.info("  Offer:  %s", offer.title[:80])
    logger.info("  Company: %s", offer.company_name[:50])
    logger.info("  Rate:   %d EUR/day", preferred_rate)
    logger.info("  Letter length: %d chars", len(cover_letter))
    logger.info("  URL:    %s", offer.conversation_url)
    logger.info("=" * 50)

    # --- Safety delay ---
    logger.info("Waiting %d seconds before clicking Send...", delay_before_send)
    await page.wait_for_timeout(delay_before_send * 1000)

    # --- Step 4: Find and click the final submit button ---
    submit_btn = await _find_submit_button(page)
    if not submit_btn:
        logger.warning("No separate Submit button found — Postuler click may have been enough")

    if submit_btn:
        try:
            await submit_btn.click()
        except Exception as exc:
            logger.error("Failed to click submit button: %s", exc)
            return False

    # --- Wait for confirmation ---
    await page.wait_for_timeout(3000)

    toast = await page.query_selector(Selectors.CONFIRMATION_TOAST)
    page_text = (await page.inner_text("body")).lower()

    success_signals = ["envoyé", "soumis", "candidature", "succès", "sent", "submitted", "postulé"]
    if toast or any(s in page_text for s in success_signals):
        logger.info("Application submitted successfully!")
        mark_as_handled(offer.conversation_url)
        increment_daily_count()
        _log_application(offer, cover_letter, preferred_rate, success=True)
        return True

    logger.warning("Could not confirm submission, but click was executed. Marking as handled.")
    mark_as_handled(offer.conversation_url)
    increment_daily_count()
    _log_application(offer, cover_letter, preferred_rate, success=None)
    return True


def _log_application(offer: Offer, cover_letter: str, rate: int, success: bool | None):
    """Append application details to a log file for record-keeping."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "applications.log"
    timestamp = datetime.now().isoformat()
    status = "SUCCESS" if success else ("UNKNOWN" if success is None else "FAILED")

    entry = (
        f"\n{'='*60}\n"
        f"[{timestamp}] {status}\n"
        f"Title:   {offer.title}\n"
        f"Company: {offer.company_name}\n"
        f"Budget:  {offer.budget_raw}\n"
        f"Rate:    {rate} EUR/day\n"
        f"URL:     {offer.conversation_url}\n"
        f"Tags:    {', '.join(offer.tags[:8])}\n"
        f"Letter:\n{cover_letter}\n"
        f"{'='*60}\n"
    )

    with open(log_file, "a", encoding="utf-8") as f:
        f.write(entry)
