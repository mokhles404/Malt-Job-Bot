"""
CSS / text selectors for the Malt messages page.

Malt is a React SPA -- DOM structure may change over time.
When selectors break, update this single file.

IMPORTANT: Run `python discover_selectors.py` in headed mode
to visually inspect the page and refine these selectors.
"""


class Selectors:
    # ------------------------------------------------------------------ #
    # Login / session detection
    # ------------------------------------------------------------------ #
    LOGIN_FORM = 'form[action*="login"], input[name="email"]'
    LOGGED_IN_INDICATOR = 'a[href="/messages"], a[href*="/dashboard"]'

    # ------------------------------------------------------------------ #
    # Messages page  (https://www.malt.fr/messages)
    # ------------------------------------------------------------------ #
    CONVERSATION_LIST_CONTAINER = (
        '[class*="conversation-list"], '
        '[class*="ConversationList"], '
        '[class*="thread-list"], '
        '[data-testid*="conversation"], '
        'aside, nav'
    )

    CONVERSATION_ITEM = (
        'li[class*="summary__wrapper"], '
        '[class*="conversation-item"], '
        '[class*="ConversationItem"], '
        '[class*="thread-item"], '
        '[data-testid*="conversation-item"], '
        '[class*="message-thread"]'
    )

    UNREAD_BADGE = (
        '[class*="unread"], '
        '[class*="badge"], '
        '[data-testid*="unread"], '
        '[class*="notification-dot"]'
    )

    # Text that identifies an offer waiting for your reply
    PENDING_REPLY_TEXT = "En attente de votre réponse"
    PENDING_REPLY_TEXTS_ALT = [
        "En attente de votre réponse",
        "En attente de v",
        "Waiting for your reply",
        "en attente de votre réponse",
        "Nouvelle proposition",
        "Nouvelle opportunité",
        "postulez",
    ]

    # ------------------------------------------------------------------ #
    # Inside a conversation / offer detail
    # ------------------------------------------------------------------ #
    PROJECT_TITLE = (
        '[class*="project-title"], '
        '[class*="ProjectTitle"], '
        '[data-testid*="project-title"], '
        'h1, h2, h3'
    )

    PROJECT_DESCRIPTION = (
        '[class*="project-description"], '
        '[class*="ProjectDescription"], '
        '[data-testid*="project-description"], '
        '[class*="mission-description"]'
    )

    BUDGET_ELEMENT = (
        '[class*="budget"], '
        '[class*="Budget"], '
        '[class*="daily-rate"], '
        '[class*="DailyRate"], '
        '[data-testid*="budget"]'
    )

    CLIENT_NAME = (
        '[class*="client-name"], '
        '[class*="ClientName"], '
        '[class*="company-name"], '
        '[class*="CompanyName"], '
        '[data-testid*="company"], '
        '[data-testid*="client"]'
    )

    TAGS_SKILLS = (
        '[class*="tag"], '
        '[class*="Tag"], '
        '[class*="skill"], '
        '[class*="Skill"], '
        '[data-testid*="skill"], '
        '[class*="chip"]'
    )

    # ------------------------------------------------------------------ #
    # Application form elements
    # ------------------------------------------------------------------ #
    PROPOSAL_TEXTAREA = (
        'textarea[name*="message"], '
        'textarea[name*="pitch"], '
        'textarea[data-testid*="message"], '
        'textarea[data-testid*="proposal"], '
        'textarea[placeholder*="message"], '
        'textarea[placeholder*="motivation"], '
        'textarea'
    )

    DAILY_RATE_INPUT = (
        'input[name*="rate"], '
        'input[name*="dailyRate"], '
        'input[name*="tjm"], '
        'input[data-testid*="rate"], '
        'input[data-testid*="daily"], '
        'input[type="number"]'
    )

    AVAILABILITY_SELECT = (
        'select[name*="availability"], '
        'select[name*="disponibilite"], '
        '[data-testid*="availability"]'
    )

    SUBMIT_BUTTON = (
        'button[type="submit"], '
        'button[data-testid*="submit"], '
        'button[data-testid*="send"], '
        'button[data-testid*="postuler"]'
    )

    SUBMIT_BUTTON_TEXT_PATTERNS = [
        "Postuler",
        "Envoyer",
        "Soumettre",
        "Candidater",
        "Envoyer ma candidature",
        "Envoyer la candidature",
        "Submit",
        "Send",
        "Apply",
    ]

    # ------------------------------------------------------------------ #
    # Confirmation after submission
    # ------------------------------------------------------------------ #
    CONFIRMATION_TOAST = (
        '[class*="toast"], '
        '[class*="Toast"], '
        '[class*="notification"], '
        '[class*="success"], '
        '[role="alert"]'
    )
