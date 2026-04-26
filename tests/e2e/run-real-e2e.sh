#!/usr/bin/env bash
# Real E2E driver — runs all 9 notecraft tasks against the live NotebookLM
# service. Expected wall time 30–60 min.
#
# History:
#   #38 first run: 5 success, 1 contract-OK-upstream-silent (source-add),
#                  3 upstream flakes (audio CDN/TLS, video silent no-mp4,
#                  infographic timeout). PR #45.
#   #46 follow-up: investigated the 3 boundary cases. Findings:
#     - video silent no-mp4 → OUR-BUG-FIXED: vendor `video` only prints a
#       URL, never downloads. Task now parses stdout, writes `video_url`
#       to frontmatter and prepends a markdown link.
#     - source-add 34→34 → UPSTREAM/TEST-TIMING: re-test confirmed every
#       add creates a new source row (no dedupe); the original count miss
#       was likely a transient detail-poll race.
#     - audio CDN/TLS → MIXED: vendor saves `audio_*.mp4` but our
#       `_EXPECTED_EXTS["audio"]` only listed mp3/wav/m4a, so even
#       successful downloads were reported as missing. Added `.mp4`.
#       The TLS/CDN flake itself is upstream.
#     - infographic timeout → UPSTREAM hard cap: vendor's
#       `pollArtifactReady` waits at most 300s. Task timeout dropped
#       from 1200s to 360s so we fail fast instead of false-waiting.
#
# Usage:
#   NB_ID=<existing-notebook-id> ./tests/e2e/run-real-e2e.sh
#   NOTECRAFT_DEBUG_LOG_DIR=/tmp/notecraft-debug to capture argv/stdout/stderr

set -uo pipefail

if [[ -z "${NB_ID:-}" ]]; then
  echo "ERROR: set NB_ID=<existing-notebook-id> (use 'npx notebooklm list')" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

URL="https://en.wikipedia.org/wiki/Markdown"
LOG="/tmp/e2e-38-run-$(date -u +%Y%m%dT%H%M%SZ).log"
echo "Logging to $LOG"
exec > >(tee -a "$LOG") 2>&1

mkdir -p raw

run_task() {
  local stem="$1"; shift
  local frontmatter="$1"; shift
  local note="raw/${stem}.md"
  printf -- "---\n%s\ncreated: %s\n---\n\nE2E probe.\n" \
    "$frontmatter" \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$note"
  echo "=== $stem ==="
  date -u
  uv run wikictl run-task "$note" || true
  for candidate in "raw/${stem}.md" "wiki/${stem}.md"; do
    if [[ -f "$candidate" ]]; then
      echo "--- frontmatter of $candidate ---"
      awk '/^---$/{c++; if(c==2) exit} {print}' "$candidate"
      break
    fi
  done
  echo
}

TS="$(date -u +%s)"

# attribution: upstream-flake (TLS/CDN); .mp4 extension fix landed in #46
run_task "e2e-audio-${TS}" \
  "title: E2E audio
source: ${URL}
status: pending
tags: [task/audio]"

run_task "e2e-flashcards-${TS}" \
  "title: E2E flashcards
source: ${URL}
status: pending
tags: [task/flashcards]"

run_task "e2e-slides-${TS}" \
  "title: E2E slides
source: ${URL}
status: pending
tags: [task/slides]"

run_task "e2e-quiz-${TS}" \
  "title: E2E quiz
source: ${URL}
status: pending
tags: [task/quiz]"

# attribution: upstream — vendor CDN download has 10 retries with attempt*10s
# backoff (10+20+...+100 = 550s) on top of pollArtifactReady (≤300s).
# Worst-case ≈850s end-to-end. Task timeout set to 900s.
run_task "e2e-infographic-${TS}" \
  "title: E2E infographic
source: ${URL}
status: pending
tags: [task/infographic]"

run_task "e2e-datatable-${TS}" \
  "title: E2E data-table
source: ${URL}
status: pending
tags: [task/data-table]
data_table_instructions: \"Compare Markdown variants\""

# attribution: no our-bug; #38 count-unchanged was a detail-poll race.
# Note: same URL is NOT deduped upstream — every run adds a new source row.
run_task "e2e-sourceadd-${TS}" \
  "title: E2E source-add
source: ${URL}
status: pending
tags: [task/source-add]
source_add_notebook: ${NB_ID}"

run_task "e2e-chat-${TS}" \
  "title: E2E chat
source: ${URL}
status: pending
tags: [task/chat]
notebook_id: ${NB_ID}
chat_question: \"Summarize this notebook in 2 sentences\""

# attribution: our-bug-fixed in #46. Vendor doesn't save a file; it prints
# the stream/hls/download URL on stdout. Task writes `video_url` to frontmatter
# and prepends a markdown link to the body — no .mp4 ever lands locally.
run_task "e2e-video-${TS}" \
  "title: E2E video
source: ${URL}
status: pending
tags: [task/video]"

echo "All 9 tasks attempted. Inspect $LOG for details."
