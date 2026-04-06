"""
One-time login script for Malt.

Opens a browser window, waits until you are logged in (no Enter key),
then saves the session to malt_state.json.

Same logic as the automatic first run of malt_bot.py.
Use ``python login_and_save_state.py --force`` to replace an existing session.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from malt_session import STATE_FILE, ensure_malt_storage_state

load_dotenv()


async def main(force: bool) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger("malt_login")

    if force:
        Path(STATE_FILE).unlink(missing_ok=True)

    async with async_playwright() as p:
        await ensure_malt_storage_state(p, STATE_FILE, logger=log)

    log.info("You can now run: python malt_bot.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Save Malt session for the bot.")
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"Delete {STATE_FILE} first, then capture a new session.",
    )
    args = parser.parse_args()

    if Path(STATE_FILE).exists() and not args.force:
        print(
            f"{STATE_FILE} already exists. Run with --force to replace it, "
            "or delete the file manually.",
            file=sys.stderr,
        )
        sys.exit(0)

    asyncio.run(main(args.force))
