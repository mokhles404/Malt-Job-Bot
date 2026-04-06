"""
Auto-fill and submit the Malt application-funnel form.

Handles URLs like:
    /client/sourcing-projects/application-funnel/<id>/apply

The form has:
    1. Daily rate (number input)
    2. Pitch message (WYSIWYG contenteditable)
    3. Scheduling link (text input, optional)
    4. Submit button

Pitch selection uses a weighted scoring algorithm that classifies the
project as MOBILE, WEB, or GENERAL and picks the matching template.
"""

from __future__ import annotations

import logging
import os
import re
from enum import Enum, auto

import yaml
from playwright.async_api import Page

logger = logging.getLogger("malt_bot.funnel")

CONFIG_FILE = "config.yaml"


# ── Project type classification ──────────────────────────────────────────

class ProjectType(Enum):
    MOBILE = auto()
    WEB = auto()
    GENERAL = auto()


# Keyword → (weight, type).  Higher weight = stronger signal.
_MOBILE_SIGNALS: dict[str, int] = {
    "flutter": 5,
    "dart": 5,
    "react native": 5,
    "swift": 4,
    "kotlin": 4,
    "swiftui": 4,
    "application mobile": 5,
    "app mobile": 5,
    "appli mobile": 5,
    "mobile app": 5,
    "ios": 4,
    "android": 4,
    "play store": 4,
    "app store": 4,
    "google play": 4,
    "smartphone": 3,
    "téléphone": 2,
    "multiplateforme": 3,
    "cross-platform": 3,
    "cross platform": 3,
    "mobile": 3,
    "natif": 2,
    "native": 2,
    "apk": 3,
    "ipa": 3,
    "expo": 3,
    "xcode": 3,
    "cocoapods": 3,
    "gradle": 2,
    "firebase cloud messaging": 3,
    "push notification": 3,
    "notifications push": 3,
}

_WEB_SIGNALS: dict[str, int] = {
    "react.js": 4,
    "reactjs": 4,
    "react": 3,
    "next.js": 4,
    "nextjs": 4,
    "vue.js": 4,
    "vuejs": 4,
    "angular": 4,
    "nuxt": 4,
    "svelte": 4,
    "html": 3,
    "css": 3,
    "tailwind": 3,
    "bootstrap": 3,
    "sass": 2,
    "webpack": 3,
    "vite": 3,
    "site web": 4,
    "site internet": 4,
    "application web": 5,
    "webapp": 5,
    "web app": 5,
    "plateforme web": 5,
    "portail": 3,
    "dashboard": 4,
    "tableau de bord": 3,
    "back-office": 3,
    "backoffice": 3,
    "landing page": 4,
    "page web": 4,
    "frontend": 3,
    "front-end": 3,
    "back-end": 2,
    "backend": 2,
    "api rest": 3,
    "api": 2,
    "saas": 3,
    "cms": 3,
    "wordpress": 3,
    "e-commerce": 3,
    "ecommerce": 3,
    "shopify": 3,
    "django": 3,
    "flask": 3,
    "fastapi": 3,
    "express": 3,
    "nest.js": 3,
    "nestjs": 3,
    "php": 3,
    "laravel": 3,
    "ruby on rails": 3,
    "hébergement": 2,
    "responsive": 2,
    "seo": 2,
    "navigateur": 2,
}


def classify_project(text: str) -> tuple[ProjectType, int, int]:
    """
    Score the project text against mobile and web keyword dictionaries.

    Returns (ProjectType, mobile_score, web_score).

    Rules:
    - If mobile_score > web_score and mobile_score >= 4  → MOBILE
    - If web_score > mobile_score and web_score >= 4     → WEB
    - If scores are within 2 of each other or both < 4   → GENERAL
    """
    blob = text.lower()

    mobile_score = 0
    for kw, weight in _MOBILE_SIGNALS.items():
        if kw in blob:
            mobile_score += weight

    web_score = 0
    for kw, weight in _WEB_SIGNALS.items():
        if kw in blob:
            web_score += weight

    diff = abs(mobile_score - web_score)

    if mobile_score >= 4 and mobile_score > web_score and diff > 2:
        ptype = ProjectType.MOBILE
    elif web_score >= 4 and web_score > mobile_score and diff > 2:
        ptype = ProjectType.WEB
    else:
        ptype = ProjectType.GENERAL

    logger.info(
        "Project classification: %s  (mobile=%d, web=%d, diff=%d)",
        ptype.name, mobile_score, web_score, diff,
    )
    return ptype, mobile_score, web_score


# ── Pre-written pitch templates ──────────────────────────────────────────

PITCH_GENERAL = """\
Bonjour,

Je peux vous accompagner sur votre projet de A à Z : cadrage, architecture, développement et mise en production.

Avec plus de 6 ans d'expérience en développement mobile et web, j'ai l'habitude de travailler sur des projets complets et exigeants, en mettant l'accent sur la performance, la scalabilité et la qualité du code.

J'ai notamment développé des applications avec des fonctionnalités avancées (temps réel, paiements, APIs, dashboards, systèmes multi-utilisateurs).

Quelques réalisations en production :
https://play.google.com/store/apps/details?id=com.ngtech.cliickservice

https://play.google.com/store/apps/details?id=com.cinnov.ritchess

Portfolio : https://mokleslajimi.web.app/

Si cela vous convient, je peux rapidement analyser votre besoin et vous proposer une approche claire et efficace."""

PITCH_MOBILE = """\
Bonjour,

Spécialisé en développement mobile avec plus de 6 ans d'expérience, je vous accompagne dans la création ou l'amélioration de votre application Flutter (Android & iOS).

J'interviens sur tout le cycle : architecture, développement, optimisation des performances, intégration API, temps réel, paiements et publication sur les stores.

Habitué à travailler sur des applications complexes avec une forte exigence en UX et stabilité.

Exemples d'applications en production :
https://play.google.com/store/apps/details?id=com.ngtech.cliickservice

https://play.google.com/store/apps/details?id=com.cinnov.ritchess

Portfolio : https://mokleslajimi.web.app/

Disponible pour échanger et vous proposer une solution adaptée à votre projet."""

PITCH_WEB = """\
Bonjour,

Je peux vous accompagner sur le développement de votre projet web, que ce soit pour une plateforme complète, un dashboard ou une API backend.

Avec plus de 6 ans d'expérience, j'interviens sur des architectures performantes et évolutives, avec une bonne maîtrise du frontend, backend et gestion de bases de données.

Approche orientée résultats : code propre, solutions fiables et respect des délais.

Portfolio : https://mokleslajimi.web.app/

Je suis disponible pour discuter de votre besoin et vous proposer une solution concrète et efficace."""

_PITCHES = {
    ProjectType.GENERAL: PITCH_GENERAL,
    ProjectType.MOBILE: PITCH_MOBILE,
    ProjectType.WEB: PITCH_WEB,
}


# ── Page scraping helpers ────────────────────────────────────────────────

def _load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        return {}
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def _extract_project_info(page_text: str) -> dict[str, str]:
    """Pull structured info out of the funnel page's visible text."""
    info: dict[str, str] = {}

    about_match = re.search(
        r"À propos du projet\s*\n(.+?)(?:\n\n|\nProfil recherché)",
        page_text,
        re.DOTALL,
    )
    if about_match:
        info["about"] = about_match.group(1).strip()

    profile_match = re.search(
        r"Profil recherché\s*\n(.+?)(?:\n\n|Lire plus|Politique)",
        page_text,
        re.DOTALL,
    )
    if profile_match:
        info["profile"] = profile_match.group(1).strip()

    skills_match = re.search(
        r"Compétences:\s*\n(.+?)(?:\nEstimez|\n\n)",
        page_text,
        re.DOTALL,
    )
    if skills_match:
        info["skills"] = skills_match.group(1).strip()

    title_match = re.search(
        r"Mon espace freelance\s*\n(.+?)\nÀ propos",
        page_text,
        re.DOTALL,
    )
    if title_match:
        info["title"] = title_match.group(1).strip()

    return info


def select_pitch(project_info: dict[str, str]) -> tuple[str, ProjectType]:
    """
    Classify the project and return the matching pitch + detected type.
    """
    text_blob = " ".join(project_info.values())
    ptype, _, _ = classify_project(text_blob)
    return _PITCHES[ptype], ptype


# ── Main form-filling logic ──────────────────────────────────────────────

async def read_project_description(page: Page) -> dict[str, str]:
    """Extract project info from the currently loaded funnel page."""
    body_text = await page.inner_text("body")
    return _extract_project_info(body_text)


async def fill_funnel_form(
    page: Page,
    *,
    daily_rate: int | None = None,
    scheduling_link: str | None = None,
    pitch_override: str | None = None,
    auto_submit: bool = True,
) -> bool:
    """
    Fill all fields on the application-funnel page and optionally submit.

    Returns True if the form was filled (and submitted if auto_submit).
    """
    config = _load_config()
    preferred_rate = daily_rate or int(
        os.getenv("PREFERRED_DAILY_RATE", "500")
    )
    link = (
        scheduling_link
        or config.get("cover_letter", {}).get("scheduling_link", "")
    )

    project_info = await read_project_description(page)
    logger.info(
        "Project info: %s",
        {k: v[:60] for k, v in project_info.items()},
    )

    if pitch_override:
        pitch = pitch_override
        logger.info("Using pitch override (%d chars)", len(pitch))
    else:
        pitch, ptype = select_pitch(project_info)
        logger.info(
            "Selected %s pitch (%d chars)",
            ptype.name, len(pitch),
        )

    # --- 1. Fill daily rate ---
    rate_input = await page.query_selector("#daily-rate")
    if rate_input and await rate_input.is_visible():
        await rate_input.click()
        await rate_input.fill("")
        await rate_input.fill(str(preferred_rate))
        logger.info("Set daily rate to %d €/jour", preferred_rate)
    else:
        logger.warning("Daily rate field not found")

    # --- 2. Fill pitch message (WYSIWYG contenteditable) ---
    editor = await page.query_selector(
        '.wysiwyg-editor__content[contenteditable="true"]'
    )
    if editor and await editor.is_visible():
        await editor.click()
        await editor.evaluate("el => el.innerHTML = ''")
        await page.keyboard.type(pitch, delay=5)
        logger.info("Filled pitch message")
    else:
        logger.warning("WYSIWYG editor not found, trying fallback textarea")
        textarea = await page.query_selector("textarea")
        if textarea and await textarea.is_visible():
            await textarea.click()
            await textarea.fill(pitch)
            logger.info("Filled pitch via textarea fallback")
        else:
            logger.error("No pitch field found at all")
            return False

    # --- 3. Fill scheduling link ---
    if link:
        link_input = await page.query_selector("#interview-scheduling-link")
        if link_input and await link_input.is_visible():
            await link_input.click()
            await link_input.fill(link)
            logger.info("Set scheduling link: %s", link)
        else:
            logger.warning("Scheduling link field not found")

    # --- 4. Submit ---
    if auto_submit:
        logger.info("Waiting 3 seconds before submitting ...")
        await page.wait_for_timeout(3000)

        submit_btn = await page.query_selector(
            '[data-testid="application-funnel-submit-button"]'
        )
        if not submit_btn or not await submit_btn.is_visible():
            submit_btn = await page.query_selector(
                'button:has-text("Soumettre la candidature")'
            )

        if submit_btn and await submit_btn.is_visible():
            await submit_btn.click()
            logger.info("Clicked 'Soumettre la candidature'")
            await page.wait_for_timeout(4000)

            body = (await page.inner_text("body")).lower()
            success_signals = [
                "candidature envoyée",
                "candidature soumise",
                "envoyé",
                "soumis",
                "succès",
                "submitted",
                "sent",
            ]
            if any(s in body for s in success_signals):
                logger.info("Application submitted successfully!")
                return True

            url_after = page.url
            if "apply" not in url_after:
                logger.info(
                    "Page navigated away from form — likely submitted: %s",
                    url_after,
                )
                return True
            logger.warning("Submit clicked but could not confirm success")
            return True
        else:
            logger.error("Submit button not found")
            return False

    logger.info("Form filled (auto_submit=False, not submitting)")
    return True
