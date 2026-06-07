#!/bin/bash
# Runner for the scheduler (cron / launchd). Forwards any flags to digest.py.
# Examples:
#   ./run_digest.sh --no-videos --label newsletters     # newsletter-only brief
#   ./run_digest.sh --no-newsletters --label youtube     # youtube-only brief
set -u
REPO="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO" || exit 1

# Make common tool locations visible to launchd/cron's minimal PATH.
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/Library/Python/3.9/bin:$HOME/.local/bin:$PATH"

LOG="$REPO/state/run.log"
mkdir -p "$REPO/state"
echo "=== $(date) ($*) ===" >> "$LOG"

# Warn if the transcript PO-token provider isn't up (needed for YouTube; see README).
curl -s -m 5 "${POT_BASE_URL:-http://127.0.0.1:4416}/ping" >/dev/null 2>&1 || \
  echo "WARNING: PO-token provider not responding — YouTube transcripts may fail (see README)" >> "$LOG"

python3 digest.py "$@" >> "$LOG" 2>&1
echo "exit=$?" >> "$LOG"
