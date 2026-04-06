"""
Helper script: opens Malt messages in a headed browser
with your saved session and dumps the DOM structure
so you can identify the correct CSS selectors.

Usage:
    python discover_selectors.py
"""

import asyncio
import json
import os

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from malt_browser import connect_or_launch_chromium

load_dotenv()

STATE_FILE = "malt_state.json"
MESSAGES_URL = "https://www.malt.fr/messages"


async def dump_structure(page, selector: str, label: str, limit: int = 5):
    """Print outer HTML of matching elements for inspection."""
    elements = await page.query_selector_all(selector)
    count = len(elements)
    print(f"\n{'='*60}")
    print(f"  {label}: {count} elements match '{selector}'")
    print(f"{'='*60}")
    for i, el in enumerate(elements[:limit]):
        tag = await el.evaluate("e => e.tagName")
        classes = await el.evaluate("e => e.className")
        text = (await el.inner_text())[:120].replace("\n", " ")
        outer = (await el.evaluate("e => e.outerHTML"))[:300]
        print(f"\n  [{i}] <{tag}> class=\"{classes}\"")
        print(f"      text: {text}")
        print(f"      html: {outer}")


async def main():
    if not os.path.exists(STATE_FILE):
        print(f"ERROR: {STATE_FILE} not found. Run login_and_save_state.py first.")
        return

    async with async_playwright() as p:
        browser = await connect_or_launch_chromium(p, headless=False)
        context = await browser.new_context(
            storage_state=STATE_FILE,
            viewport={"width": 1400, "height": 900},
            locale="fr-FR",
        )
        page = await context.new_page()

        print(f"Navigating to {MESSAGES_URL} ...")
        await page.goto(MESSAGES_URL, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        current = page.url
        print(f"Current URL: {current}")

        if "login" in current.lower():
            print("\nSession expired. Re-run login_and_save_state.py")
            await browser.close()
            return

        # Dump candidate selectors
        candidates = {
            "Conversation items (div with 'conversation')": "[class*='conversation']",
            "Conversation items (div with 'thread')": "[class*='thread']",
            "Conversation items (li elements)": "li",
            "Unread badges": "[class*='unread'], [class*='badge']",
            "Textareas (for message input)": "textarea",
            "Submit / send buttons": "button[type='submit'], button:has-text('Envoyer'), button:has-text('Postuler')",
            "Input[type=number] (daily rate?)": "input[type='number']",
            "Anchors with /messages/": "a[href*='/messages/']",
            "Data-testid elements": "[data-testid]",
            "Pending reply text": f"text='{chr(171)}En attente{chr(187)}' , :has-text('En attente de votre réponse')",
        }

        for label, sel in candidates.items():
            try:
                await dump_structure(page, sel, label, limit=3)
            except Exception as e:
                print(f"\n  {label}: ERROR - {e}")

        # Also dump body children summary
        print(f"\n{'='*60}")
        print("  Top-level body children:")
        print(f"{'='*60}")
        body_children = await page.query_selector_all("body > *")
        for i, child in enumerate(body_children[:15]):
            tag = await child.evaluate("e => e.tagName")
            cid = await child.evaluate("e => e.id")
            cls = await child.evaluate("e => (e.className || '').toString().slice(0, 80)")
            print(f"  [{i}] <{tag}> id={cid} class={cls}")

        print("\n\nBrowser is open -- inspect the page with DevTools (F12).")
        print("Press ENTER here when done to close.")
        input()

        await context.storage_state(path=STATE_FILE)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
