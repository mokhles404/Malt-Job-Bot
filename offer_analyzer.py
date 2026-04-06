"""
Parse offer / project details from an open Malt conversation.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from playwright.async_api import Page

from malt_selectors import Selectors

logger = logging.getLogger("malt_bot.analyzer")


@dataclass
class Offer:
    title: str = ""
    description: str = ""
    budget_raw: str = ""
    budget_numeric: int = 0
    client_name: str = ""
    company_name: str = ""
    tags: list[str] = field(default_factory=list)
    is_direct_offer: bool = False
    conversation_url: str = ""


def _parse_budget(raw: str) -> int:
    """Extract a numeric budget from text like '500 €/jour' or '3 000 €'."""
    cleaned = raw.replace("\u202f", "").replace("\xa0", "").replace(" ", "")
    numbers = re.findall(r"(\d+)", cleaned)
    if numbers:
        return int(numbers[0])
    return 0


async def _safe_text(page: Page, selector: str) -> str:
    """Query a selector and return its inner text, or '' if not found."""
    el = await page.query_selector(selector)
    if el:
        try:
            return (await el.inner_text()).strip()
        except Exception:
            pass
    return ""


async def _safe_all_texts(page: Page, selector: str) -> list[str]:
    """Return inner text of all matching elements."""
    elements = await page.query_selector_all(selector)
    texts = []
    for el in elements:
        try:
            t = (await el.inner_text()).strip()
            if t:
                texts.append(t)
        except Exception:
            continue
    return texts


async def parse_offer_from_conversation(page: Page) -> Offer | None:
    """
    Extract project metadata from the currently open conversation.
    Returns None if this doesn't look like an offer.
    """
    offer = Offer()
    offer.conversation_url = page.url

    # --- Title ---
    for sel in Selectors.PROJECT_TITLE.split(","):
        sel = sel.strip()
        text = await _safe_text(page, sel)
        if text and len(text) > 3:
            offer.title = text
            break

    # --- Description ---
    for sel in Selectors.PROJECT_DESCRIPTION.split(","):
        sel = sel.strip()
        text = await _safe_text(page, sel)
        if text and len(text) > 10:
            offer.description = text
            break

    # If still no description, try to grab the main message body
    if not offer.description:
        body_texts = await _safe_all_texts(page, "p, div[class*='message-body'], div[class*='MessageBody']")
        for t in body_texts:
            if len(t) > 30:
                offer.description = t
                break

    # --- Budget ---
    for sel in Selectors.BUDGET_ELEMENT.split(","):
        sel = sel.strip()
        text = await _safe_text(page, sel)
        if text:
            offer.budget_raw = text
            offer.budget_numeric = _parse_budget(text)
            if offer.budget_numeric > 0:
                break

    # --- Client / company name ---
    for sel in Selectors.CLIENT_NAME.split(","):
        sel = sel.strip()
        text = await _safe_text(page, sel)
        if text and len(text) > 1:
            offer.company_name = text
            break

    # Fallback: use the page title or thread header
    if not offer.company_name:
        header = await _safe_text(page, "h1, h2")
        if header:
            offer.company_name = header

    # --- Tags / skills ---
    for sel in Selectors.TAGS_SKILLS.split(","):
        sel = sel.strip()
        tags = await _safe_all_texts(page, sel)
        if tags:
            offer.tags = tags[:15]
            break

    # --- Determine if this is actually an offer ---
    page_text = await page.inner_text("body")
    page_text_lower = page_text.lower()

    offer_signals = [
        "en attente de votre réponse",
        "postuler",
        "candidater",
        "proposition de mission",
        "offre de mission",
        "tjm",
        "taux journalier",
        "budget",
        "€/jour",
    ]
    signal_count = sum(1 for s in offer_signals if s in page_text_lower)
    offer.is_direct_offer = signal_count >= 2

    if not offer.title and not offer.description and signal_count < 1:
        logger.info("Conversation does not look like an offer. Skipping.")
        return None

    if not offer.title:
        offer.title = offer.company_name or "Offre sans titre"

    logger.info(
        "Parsed offer: title=%r company=%r budget=%s tags=%d",
        offer.title[:50],
        offer.company_name[:30],
        offer.budget_raw or "N/A",
        len(offer.tags),
    )

    return offer
