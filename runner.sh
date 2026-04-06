#!/bin/bash
#
# Malt Bot Runner
#
# Usage:
#   ./runner.sh              # Single run
#   ./runner.sh loop 300     # Run every 300 seconds (5 minutes)
#
# For cron (runs every 5 minutes):
#   */5 * * * * /Users/cinnov/malt-bot/runner.sh >> /Users/cinnov/malt-bot/logs/cron.log 2>&1
#

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtualenv
source venv/bin/activate

# Lock file to prevent concurrent runs
LOCK_FILE="/tmp/malt_bot.lock"

if [ -f "$LOCK_FILE" ]; then
    PID=$(cat "$LOCK_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "$(date): Bot already running (PID $PID). Skipping."
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

if [ "$1" = "loop" ]; then
    INTERVAL=${2:-300}
    python malt_bot.py --loop "$INTERVAL"
else
    python malt_bot.py
fi
