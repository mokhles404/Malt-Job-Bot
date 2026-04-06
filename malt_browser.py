"""Launch Google Chrome / Chromium or attach to Chrome over CDP."""

from __future__ import annotations

import logging
import os

from playwright.async_api import Browser, Playwright

logger = logging.getLogger("malt_browser")


def launch_channel() -> str | None:
    """
    Channel passed to ``chromium.launch(channel=...)``.

    If ``PLAYWRIGHT_CHANNEL`` is unset, defaults to ``\"chrome\"`` (installed Chrome).
    If set to empty or ``chromium`` / ``bundled`` / ``playwright``, use Playwright's
    bundled Chromium (no channel).
    """
    raw = os.getenv("PLAYWRIGHT_CHANNEL")
    if raw is None:
        return "chrome"
    s = raw.strip()
    if not s or s.lower() in ("chromium", "bundled", "playwright"):
        return None
    return s


def chrome_cdp_url() -> str | None:
    """When set, connect to this Chrome DevTools Protocol endpoint instead of launching."""
    u = os.getenv("CHROME_CDP_URL", "").strip()
    return u or None


async def connect_or_launch_chromium(
    playwright: Playwright,
    *,
    headless: bool,
) -> Browser:
    """Connect via ``CHROME_CDP_URL`` or launch with optional ``PLAYWRIGHT_CHANNEL``."""
    cdp = chrome_cdp_url()
    if cdp:
        try:
            return await playwright.chromium.connect_over_cdp(cdp)
        except Exception as exc:
            logger.error(
                "Could not connect to Chrome at %s (%s). Start Chrome with a "
                "remote debugging port that matches CHROME_CDP_URL.",
                cdp,
                exc,
            )
            raise

    channel = launch_channel()
    if channel:
        try:
            return await playwright.chromium.launch(
                headless=headless,
                channel=channel,
            )
        except Exception as exc:
            logger.warning(
                "Launch with channel %r failed (%s); using bundled Chromium instead.",
                channel,
                exc,
            )
            return await playwright.chromium.launch(headless=headless)

    return await playwright.chromium.launch(headless=headless)
