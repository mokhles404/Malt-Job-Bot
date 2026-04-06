"""Create or reuse Playwright storage state (cookies + localStorage) for Malt."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page, Playwright
from playwright._impl._errors import TargetClosedError

from malt_selectors import Selectors

STATE_FILE = "malt_state.json"
LOGIN_URL = "https://www.malt.fr/login"
MESSAGES_URL = "https://www.malt.fr/messages"
PROFILE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chrome-malt-profile")


def _on_login_path(url: str) -> bool:
    try:
        path = urlparse(url).path.lower().rstrip("/")
    except Exception:
        url_l = url.lower()
        return "/login" in url_l or "/signin" in url_l
    return path.endswith("/login") or path.endswith("/signin")


async def _page_looks_logged_in(page: Page) -> bool:
    if _on_login_path(page.url):
        return False
    el = await page.query_selector(Selectors.LOGGED_IN_INDICATOR)
    return el is not None


# --------------------------------------------------------------------------- #
#  Strategy 1: Extract cookies from the user's running Chrome (macOS)
# --------------------------------------------------------------------------- #

def _try_extract_from_chrome(state_path: str, logger: logging.Logger) -> bool:
    """
    Attempt to read Malt cookies directly from the user's Chrome profile
    (no new browser window). Returns True on success.
    """
    if platform.system() != "Darwin":
        return False

    try:
        from extract_chrome_session import extract_malt_cookies, build_storage_state
    except ImportError:
        return False

    try:
        cookies = extract_malt_cookies()
    except Exception as exc:
        logger.debug("Cookie extraction failed: %s", exc)
        return False

    if not cookies:
        return False

    session_cookies = [c for c in cookies if c["name"] in ("SESSION", "JSESSIONID", "remember-me")]
    if not session_cookies:
        logger.debug("Chrome has Malt cookies but no session cookies (not logged in?).")
        return False

    import json
    Path(state_path).write_text(json.dumps(build_storage_state(cookies), indent=2))
    logger.info(
        "Extracted %d Malt cookies from Chrome (no new browser needed).",
        len(cookies),
    )
    return True


# --------------------------------------------------------------------------- #
#  Strategy 2: Launch real Chrome subprocess for manual login
# --------------------------------------------------------------------------- #

_CHROME_CANDIDATES = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ],
    "Linux": [
        "google-chrome-stable",
        "google-chrome",
        "chromium-browser",
        "chromium",
    ],
    "Windows": [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ],
}


def _find_chrome() -> str | None:
    system = platform.system()
    for candidate in _CHROME_CANDIDATES.get(system, []):
        if os.path.isabs(candidate) and os.path.isfile(candidate):
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
    return shutil.which("google-chrome") or shutil.which("chrome")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launch_chrome_subprocess(
    port: int,
    user_data_dir: str,
    start_url: str,
    logger: logging.Logger,
) -> subprocess.Popen:
    chrome = _find_chrome()
    if not chrome:
        raise FileNotFoundError(
            "Google Chrome not found. Install Chrome or set CHROME_CDP_URL in .env."
        )
    os.makedirs(user_data_dir, exist_ok=True)
    cmd = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        start_url,
    ]
    logger.info("Starting Chrome: port %d, profile %s", port, user_data_dir)
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _kill_chrome(proc: subprocess.Popen, logger: logging.Logger) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Chrome did not exit after SIGTERM; sending SIGKILL.")
        proc.kill()
    except Exception:
        pass


async def _wait_for_cdp(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            await asyncio.sleep(0.5)
    raise TimeoutError(f"Chrome did not expose CDP on port {port} within {timeout}s")


async def _login_via_subprocess(
    playwright: Playwright,
    state_path: str,
    logger: logging.Logger,
    timeout_sec: float,
    poll_interval_sec: float,
    messages_probe_interval_sec: float,
) -> None:
    """Open a real Chrome subprocess for manual login, save state via CDP."""
    logger.info(
        "Opening Chrome with a dedicated profile — log in to Malt there. "
        "Google OAuth will work normally (no bot detection)."
    )

    port = _free_port()
    proc = _launch_chrome_subprocess(port, PROFILE_DIR, LOGIN_URL, logger)
    browser = None
    path = Path(state_path)

    try:
        await _wait_for_cdp(port)
        browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")

        contexts = browser.contexts
        if not contexts:
            raise RuntimeError("No browser contexts found after connecting over CDP")
        context = contexts[0]
        pages = context.pages
        page = pages[0] if pages else await context.new_page()

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec
        last_messages_probe = 0.0

        while loop.time() < deadline:
            try:
                if await _page_looks_logged_in(page):
                    await context.storage_state(path=state_path)
                    logger.info("Session saved to %s", path.resolve())
                    return

                now = loop.time()
                if not _on_login_path(page.url) and (
                    now - last_messages_probe >= messages_probe_interval_sec
                ):
                    last_messages_probe = now
                    try:
                        await page.goto(
                            MESSAGES_URL,
                            wait_until="domcontentloaded",
                            timeout=30_000,
                        )
                    except Exception:
                        pass
                    await page.wait_for_timeout(400)
                    if await _page_looks_logged_in(page):
                        await context.storage_state(path=state_path)
                        logger.info("Session saved to %s", path.resolve())
                        return

                wait_ms = min(
                    int(poll_interval_sec * 1000),
                    int((deadline - loop.time()) * 1000),
                )
                if wait_ms > 0:
                    await page.wait_for_timeout(wait_ms)

            except TargetClosedError:
                logger.error(
                    "Chrome closed before session was saved. "
                    "Run again and keep Chrome open until login is detected."
                )
                raise TimeoutError("Chrome closed during login.") from None

        raise TimeoutError(
            f"Login was not detected within {timeout_sec:.0f}s. "
            "Finish logging in then run again."
        )
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        _kill_chrome(proc, logger)


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #

async def ensure_malt_storage_state(
    playwright: Playwright,
    state_path: str,
    *,
    logger: logging.Logger,
    timeout_sec: float = 900.0,
    poll_interval_sec: float = 2.0,
    messages_probe_interval_sec: float = 12.0,
) -> None:
    """
    Make sure ``state_path`` exists with valid Malt cookies.

    Strategy order:
      1. File already exists → done.
      2. Extract cookies from the user's running Chrome (macOS Keychain).
      3. Fall back to a real Chrome subprocess for manual login.
    """
    path = Path(state_path)
    if path.exists() and path.stat().st_size > 0:
        return

    if _try_extract_from_chrome(state_path, logger):
        return

    logger.info(
        "Could not extract cookies from Chrome automatically. "
        "Falling back to a login window."
    )
    await _login_via_subprocess(
        playwright,
        state_path,
        logger,
        timeout_sec,
        poll_interval_sec,
        messages_probe_interval_sec,
    )
