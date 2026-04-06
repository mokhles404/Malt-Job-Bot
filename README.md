# Malt Auto-Apply Bot

Automatically detects new project offers on `malt.fr/messages` and applies with a personalized cover letter.

## Quick Start

### 1. Install

```bash
cd ~/malt-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
# Default config uses Google Chrome (PLAYWRIGHT_CHANNEL=chrome) — install Chrome on the machine.
# To use only bundled Chromium instead, set PLAYWRIGHT_CHANNEL=chromium (or empty) in .env.
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your preferred daily rate and limits
# Edit config.yaml with your keywords, cover letter text, etc.
```

**Browser / CAPTCHA:** By default the bot uses **Google Chrome** (`PLAYWRIGHT_CHANNEL=chrome` in `.env`), which is harder for sites to fingerprint than Playwright’s bundled Chromium. If Malt still shows CAPTCHA often, start Chrome with a **dedicated profile** and remote debugging, log in there once, then set in `.env`:

```text
CHROME_CDP_URL=http://127.0.0.1:9222
```

The default **`malt_bot.py`** flow uses **`chrome_cdp.py`**, which launches **Chrome-Debug** under your OS Chrome folder (symlinked to your real profile)—not a folder inside this repo.

Optional manual CDP (only if you set `CHROME_CDP_URL` yourself). Use **any empty directory** outside the repo, never your main Chrome profile while everyday Chrome is open:

```bash
mkdir -p "$HOME/chrome-malt-cdp"
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-malt-cdp"
```

Leave that Chrome window running while the bot runs; **do not** point `--user-data-dir` at your normal Chrome profile if everyday Chrome is already open.

### 3. Log in to Malt (one time)

```bash
python login_and_save_state.py
```

A browser opens. Log in normally; the session is saved automatically when login is detected (or run `malt_bot.py`, which does the same on first run).

### 4. (Optional) Discover selectors

If the bot can't find elements, run:

```bash
python discover_selectors.py
```

Inspect the page with DevTools (F12) and update `malt_selectors.py`.

### 5. Run the bot

```bash
# Single run (headless)
python malt_bot.py

# Single run with visible browser (debugging)
python malt_bot.py --headed

# Loop mode: run every 5 minutes
python malt_bot.py --loop 300

# Or use the shell runner
./runner.sh              # single run
./runner.sh loop 300     # every 5 minutes
```

### 6. Schedule with cron (optional)

```bash
crontab -e
```

Add:

```
*/5 * * * * /Users/cinnov/malt-bot/runner.sh >> /Users/cinnov/malt-bot/logs/cron.log 2>&1
```

## Files

| File | Purpose |
|---|---|
| `login_and_save_state.py` | One-time login, saves session to `malt_state.json` |
| `malt_browser.py` | Chooses Chrome vs CDP (`PLAYWRIGHT_CHANNEL`, `CHROME_CDP_URL`) |
| `malt_session.py` | Creates `malt_state.json` when missing |
| `malt_bot.py` | Main orchestration script |
| `messages_scraper.py` | Scans `/messages` for pending offer threads |
| `offer_analyzer.py` | Extracts project details from a conversation |
| `rules.py` | Decides whether to apply based on budget/keywords |
| `cover_letter.py` | Generates personalized cover letters |
| `form_filler.py` | Fills form fields and clicks submit |
| `malt_selectors.py` | All CSS selectors (update when Malt changes UI) |
| `discover_selectors.py` | Helper to inspect the DOM and find selectors |
| `config.yaml` | Keywords, budget rules, cover letter templates |
| `.env` | Daily rate, limits, headless mode |
| `runner.sh` | Shell wrapper with lock file for cron |

## Safety

- Daily application limit (default: 10/day)
- Per-run limit (default: 5/run)
- Random delays between actions
- Full logging to `logs/malt_bot.log` and `logs/applications.log`
- Handled threads tracked in `handled_threads.json` to avoid duplicates
