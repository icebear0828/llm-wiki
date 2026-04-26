#!/usr/bin/env bash
# Real E2E driver for issue #38 — runs all 9 notecraft tasks against the
# live NotebookLM service. Expected wall time 30–60 min.
#
# Usage:
#   NB_ID=<existing-notebook-id> ./tests/e2e/run-real-e2e.sh

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

run_task "e2e-video-${TS}" \
  "title: E2E video
source: ${URL}
status: pending
tags: [task/video]"

echo "All 9 tasks attempted. Inspect $LOG for details."
