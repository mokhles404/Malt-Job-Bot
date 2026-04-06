# Malt Auto-Apply Bot — project context (for Cursor / future sessions)

This file documents **how the bot works today** and **recent design decisions**. Use it so tooling and contributors stay aligned with the actual code, not only the older README snippets.

---

## Goal

Automate applying to **pending Malt project offers** from `https://www.malt.fr/messages`, using the user’s **real Chrome session** (CDP) so cookies and TLS match a normal browser.

---

## High-level flow

1. **`chrome_cdp.py`** ensures Chrome is reachable with remote debugging on port **9222** using a separate **Chrome-Debug** profile whose `Default` and `Local State` are **symlinked** to the real Chrome profile. (Chrome forbids CDP on the default user-data-dir path; symlinks work around that.)

2. **`malt_bot.py`** connects via Playwright `connect_over_cdp`, goes to `/messages`, and **`messages_scraper.py`**:
   - **Scrolls the sidebar** (`div.scrollable`) until the list is at the bottom and lazy-loading stops (waits ~2s between scrolls; requires stable “at bottom” + no new items before stopping).
   - Collects threads whose sidebar text matches **pending** patterns (e.g. “En attente de votre réponse”, “Nouvelle opportunité”, “postulez”).
   - **Skips** sidebar rows that already show **“En attente de modération”** in that row (already submitted from that thread’s preview).

3. For each pending thread (in order):
   - `page.goto(/messages)` → **`open_thread`** scrolls the sidebar until the stored **index** exists, **`scroll_into_view_if_needed`**, then clicks.
   - If URL is in **`handled_threads.json`**, skip.
   - **Two apply paths:**
     - **Postuler** → navigates to **`/client/sourcing-projects/application-funnel/<id>/apply`** → **`funnel_filler.fill_funnel_form`** (WYSIWYG `.wysiwyg-editor__content`, `#daily-rate`, `#interview-scheduling-link`, submit `data-testid="application-funnel-submit-button"`).
     - **Discuter du projet** (no funnel) → **`_handle_discuter_flow`**: click “Discuter du projet” → fill the **widest visible** `textarea[placeholder*="Ecrivez"]` → submit via `button[data-testid="project-proposal-area-submit"]` or the Discuter button again.
   - If **neither** Postuler nor Discuter is visible, treat as already done/expired → **mark handled** (do **not** use full-page text for “modération”; other threads’ sidebar text would false-positive).

4. **Pitches:** `funnel_filler.classify_project` scores **MOBILE** vs **WEB** keywords on page/body text; ties or low scores → **GENERAL**. Three fixed French templates (mobile / web / general) with portfolio and store links. `cover_letter.py` reuses the same classifier for consistency.

5. **Limits & persistence:** `.env` — `PREFERRED_DAILY_RATE`, `MAX_APPLICATIONS_PER_RUN`, `MAX_APPLICATIONS_PER_DAY`. **`daily_counter.json`** (per calendar day). **`handled_threads.json`** stores **offer page URLs** (`/messages/client-project-offer/...` or plain `/messages/...`) to avoid duplicate work.

---

## Key files (current responsibilities)

| File | Role |
|------|------|
| `malt_bot.py` | Main loop: CDP, scan, open thread, Postuler vs Discuter vs skip, funnel fill, counts, `--funnel URL`, `--loop` |
| `chrome_cdp.py` | Launch / detect **Chrome-Debug** + CDP 9222, symlinked real profile |
| `messages_scraper.py` | Sidebar **full scroll**, pending detection, `open_thread` with scroll + click |
| `funnel_filler.py` | MOBILE/WEB/GENERAL templates, classifier, funnel form fill + submit |
| `malt_bot.py` (`_handle_discuter_flow`) | “Discuter du projet” in-thread proposal textarea flow |
| `config.yaml` | CV-style blurbs, keywords, **`cover_letter.scheduling_link`** (Calendly), throttle |
| `.env` | Rate, limits, optional `CHROME_CDP_URL` / `PLAYWRIGHT_CHANNEL` (or project may rely on `ensure_chrome_with_cdp` only) |
| `form_filler.py` | Legacy “Postuler + textarea in same view” flow; **main path is funnel + `funnel_filler`** |
| `offer_analyzer.py`, `rules.py` | Still in repo; **primary run path does not gate on `rules.should_apply`** for the funnel bulk apply — keep in mind if re-enabling filters |

---

## Pitfalls already hit (don’t regress)

1. **`page.goto` on `/messages` after CDP** can briefly leave the sidebar **empty** — `open_thread` **waits and scroll-loads** until `raw_element_index` exists.

2. **Stale “handled” list** — old runs marked URLs handled without a real submit; user may need to clear **`handled_threads.json`** once intentionally.

3. **Last thread “index out of range”** — can happen if list length changes between scan and click; mitigated by scrolling in `open_thread`; if Malt removes a thread mid-run, one skip is possible.

4. **Sidebar vs detail “modération”** — never detect “already applied” using **whole `body` text**; sidebar lists other threads’ states. Use **visible Postuler/Discuter** or row-level skip in scraper.

---

## Commands

```bash
# Typical: apply to all pending (respects .env limits)
./venv/bin/python malt_bot.py

# One funnel URL only
./venv/bin/python malt_bot.py --funnel "https://www.malt.fr/client/sourcing-projects/application-funnel/<id>/apply"

# Periodic
./venv/bin/python malt_bot.py --loop 300
```

---

## Maintenance checklist when Malt changes UI

- `SELECTORS.CONVERSATION_ITEM` / sidebar scroll parent in `messages_scraper.py`
- Postuler / Discuter button labels or roles in `malt_bot.py`
- Funnel: `funnel_filler.py` selectors (`#daily-rate`, `.wysiwyg-editor__content`, submit `data-testid`)
- Discuter: `textarea` placeholder, `project-proposal-area-submit`

---

## Last consolidated behavior (changelog summary)

- Real Chrome via **CDP + Chrome-Debug** symlink profile.
- **Full sidebar scroll** + pending thread enumeration.
- **Postuler → application funnel** with rate, classified pitch, Calendly.
- **Discuter du projet** path for in-page proposal textarea.
- **Handled** = URL file + daily counter; **no** whole-page modération string matching on detail view.

---

*Update this file when you change flows, selectors, or limits so Cursor and humans stay in sync.*
