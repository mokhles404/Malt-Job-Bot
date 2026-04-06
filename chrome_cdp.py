"""
Manage the user's Chrome for CDP-based automation.

Launches Chrome-Debug (a separate instance with symlinked profile) with
--remote-debugging-port so the bot can connect via CDP. This shares all
cookies and sessions with the user's regular Chrome profile.

NOTE: Chrome refuses CDP on its *default* user-data-dir. The workaround
is a separate dir ("Chrome-Debug") whose Default/ folder is a symlink
to the real profile.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
import subprocess
import time

logger = logging.getLogger("chrome_cdp")

CDP_PORT = 9222

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


def _chrome_default_data_dir() -> str:
    """Return Chrome's default user-data-dir."""
    system = platform.system()
    if system == "Darwin":
        return os.path.expanduser(
            "~/Library/Application Support/Google/Chrome"
        )
    if system == "Linux":
        return os.path.expanduser("~/.config/google-chrome")
    raise RuntimeError(f"Unsupported platform: {system}")


def _chrome_debug_data_dir() -> str:
    """
    A separate user-data-dir whose Default/ and Local State are symlinked
    from the real profile so Chrome can open CDP while sharing cookies.
    """
    real = _chrome_default_data_dir()
    debug = real + "-Debug"
    os.makedirs(debug, exist_ok=True)

    for name in ("Default", "Local State"):
        target = os.path.join(debug, name)
        source = os.path.join(real, name)
        if os.path.islink(target):
            continue
        if os.path.exists(target):
            continue
        if os.path.exists(source):
            os.symlink(source, target)

    return debug


def _is_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _quit_chrome_macos() -> None:
    """Gracefully quit Chrome via AppleScript (saves session/tabs)."""
    subprocess.run(
        ["osascript", "-e", 'tell application "Google Chrome" to quit'],
        capture_output=True,
        timeout=10,
    )


def _is_chrome_running() -> bool:
    if platform.system() == "Darwin":
        result = subprocess.run(
            ["pgrep", "-x", "Google Chrome"],
            capture_output=True,
        )
        return result.returncode == 0
    result = subprocess.run(
        ["pgrep", "-f", "chrome"],
        capture_output=True,
    )
    return result.returncode == 0


def _wait_chrome_quit(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _is_chrome_running():
            return
        time.sleep(0.5)
    raise TimeoutError("Chrome did not quit within the timeout.")


def _wait_cdp_ready(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _is_port_open(port):
            return
        time.sleep(0.5)
    raise TimeoutError(
        f"Chrome did not expose CDP on port {port} within {timeout}s."
    )


def ensure_chrome_with_cdp(
    port: int = CDP_PORT,
    start_url: str = "https://www.malt.fr/messages",
) -> str:
    """
    Make sure Chrome-Debug is running with ``--remote-debugging-port``.

    Returns the CDP endpoint URL (e.g. ``http://127.0.0.1:9222``).
    """
    cdp_url = f"http://127.0.0.1:{port}"

    if _is_port_open(port):
        logger.info("Chrome already has CDP on port %d.", port)
        return cdp_url

    chrome = _find_chrome()
    if not chrome:
        raise FileNotFoundError(
            "Google Chrome not found. Install Chrome first."
        )

    if _is_chrome_running():
        logger.info(
            "Regular Chrome is running without CDP. "
            "Launching a separate Chrome-Debug instance ..."
        )

    user_data = _chrome_debug_data_dir()
    cmd = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
        start_url,
    ]
    logger.info("Launching Chrome-Debug with CDP on port %d ...", port)
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wait_cdp_ready(port, timeout=30.0)
    logger.info("Chrome-Debug is ready (CDP %s).", cdp_url)
    return cdp_url
