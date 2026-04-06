"""
Generate a personalized cover letter for a Malt offer.

Uses the same MOBILE / WEB / GENERAL classification as funnel_filler
so that the pitch is always consistent regardless of entry-point.
"""

from __future__ import annotations

import logging
import os
from textwrap import dedent

from offer_analyzer import Offer
from funnel_filler import classify_project, ProjectType, PITCH_MOBILE, PITCH_WEB, PITCH_GENERAL

logger = logging.getLogger("malt_bot.cover_letter")

_PITCHES = {
    ProjectType.GENERAL: PITCH_GENERAL,
    ProjectType.MOBILE: PITCH_MOBILE,
    ProjectType.WEB: PITCH_WEB,
}


def generate_cover_letter(offer: Offer, config: dict) -> str:
    """
    Classify the offer as MOBILE / WEB / GENERAL and return the
    matching pre-written pitch.  Falls back to GENERAL on ties.
    """
    text = " ".join([offer.title, offer.description, " ".join(offer.tags)])
    ptype, m, w = classify_project(text)
    logger.info(
        "Offer classified as %s (mobile=%d web=%d) → using %s pitch",
        ptype.name, m, w, ptype.name,
    )

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            return _generate_with_llm(offer, config.get("cover_letter", {}), openai_key)
        except Exception as exc:
            logger.warning("LLM generation failed, using template: %s", exc)

    return _PITCHES[ptype]


def _generate_with_llm(offer: Offer, cl_cfg: dict, api_key: str) -> str:
    """Call OpenAI to generate a smarter cover letter. Requires 'openai' pip package."""
    try:
        import openai
    except ImportError:
        raise RuntimeError("openai package not installed. pip install openai")

    client = openai.OpenAI(api_key=api_key)

    your_name = cl_cfg.get("your_name", "Mokhles Lajimi")
    specialty = cl_cfg.get("your_specialty", "développement mobile Flutter & web Full Stack")
    experience = cl_cfg.get("your_experience_summary", "")

    prompt = dedent(f"""\
    Tu es un freelance français spécialisé en {specialty}.
    Ton expérience : {experience}.

    Un client sur Malt propose ce projet :
    - Titre : {offer.title}
    - Entreprise : {offer.company_name}
    - Description : {offer.description[:500]}
    - Compétences : {', '.join(offer.tags[:8])}
    - Budget : {offer.budget_raw}

    Rédige une lettre de motivation concise (8-12 lignes) en français.
    Sois professionnel, direct, personnalisé. Ne sois pas générique.
    Mentionne des résultats concrets. Termine par ta disponibilité.
    Signe : {your_name}
    """)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=500,
        temperature=0.7,
    )

    return response.choices[0].message.content.strip()
