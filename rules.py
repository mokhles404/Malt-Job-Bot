"""
Selection rules: decide whether to apply to an offer.
"""

from __future__ import annotations

import logging

from offer_analyzer import Offer

logger = logging.getLogger("malt_bot.rules")


def should_apply(offer: Offer, config: dict) -> tuple[bool, str]:
    """
    Evaluate the offer against the rules in config.
    Returns (should_apply, reason).
    """
    budget_cfg = config.get("budget", {})
    keywords_cfg = config.get("keywords", {})

    min_daily = budget_cfg.get("min_daily", 0)
    min_total = budget_cfg.get("min_total", 0)
    include_kw = [k.lower() for k in keywords_cfg.get("include", [])]
    exclude_kw = [k.lower() for k in keywords_cfg.get("exclude", [])]

    # Build a searchable text blob
    blob = " ".join([
        offer.title,
        offer.description,
        " ".join(offer.tags),
        offer.company_name,
    ]).lower()

    # --- Budget filter ---
    if offer.budget_numeric > 0:
        if "jour" in offer.budget_raw.lower() or "day" in offer.budget_raw.lower():
            if offer.budget_numeric < min_daily:
                return False, f"Daily budget {offer.budget_numeric} < min {min_daily}"
        else:
            if offer.budget_numeric < min_total:
                return False, f"Total budget {offer.budget_numeric} < min {min_total}"

    # --- Exclude keywords ---
    for kw in exclude_kw:
        if kw in blob:
            return False, f"Excluded keyword found: '{kw}'"

    # --- Include keywords (at least one must match) ---
    if include_kw:
        matched = [kw for kw in include_kw if kw in blob]
        if not matched:
            return False, "No include keyword matched"
        logger.info("Matched keywords: %s", matched)

    return True, "OK"
