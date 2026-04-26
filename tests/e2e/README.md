# Real E2E playbook for the 9 notecraft tasks

This is the manual reproducibility doc for issues #38 and #46.

`tests/e2e/test_notecraft_e2e.py` covers `npx notebooklm list` x3 (the
CLAUDE.md "≥3 successful real calls" minimum). The 9 generation tasks
(audio, flashcards, slides, quiz, infographic, data-table, source-add,
chat, video) hit the live NotebookLM service, take 30-60 minutes total,
and are deliberately **not** part of `pytest`. Run them with the helper
script below before merging task changes.

## Pre-flight

```bash
uv run wikictl status
cd vendor/notebooklm && npx notebooklm list --transport auto
uv run pytest tests/ --ignore=tests/e2e
```

Pick an existing notebook id from `npx notebooklm list` for the
`source-add` and `chat` tasks (they require a live notebook).

## Run

```bash
NB_ID=<some-existing-notebook-id> ./tests/e2e/run-real-e2e.sh
```

The script writes one note per task under `raw/`, calls
`uv run wikictl run-task` synchronously, and prints the resulting
artifact path / frontmatter status. All 9 tasks use the same source URL
`https://en.wikipedia.org/wiki/Markdown` for stable, low-CDN test
content.

## Expected results

- audio: `assets/audio/audio_*.mp4` (vendor saves mp4 container, not mp3)
- flashcards: `assets/quiz/flashcards_*.html`
- slides: `assets/slides/slides_*.pdf`
- quiz: `assets/quiz/quiz_*.html`
- infographic: `assets/infographic/infographic_*.png` (vendor poll ≤300s + CDN retry ≤550s, task timeout 900s)
- data-table: `assets/data-table/data_table_*.json`
- source-add: notebook gains a new source row (no upstream dedupe — same URL added twice creates two rows); note gets `notecraft_source_added_to` and `source_added_at` in frontmatter
- chat: answer appended to note body under `## Chat: <question>`
- video: **no local file** — frontmatter gains `video_url` (stream/hls/download URL from NotebookLM); body prepended with `[Video overview](<url>)` link

## Failure classification

- **Our bug** — Python exception, missing handler, wrong CLI flag: stop
  and fix.
- **Upstream flake** — `429`, `SessionExpired`, TLS errors, transient
  HTTP 5xx, timeout: re-run; if it persists, document and continue.

## Logs

Append per-run logs to `/tmp/e2e-38-log.md` (gitignored).

For boundary cases set `NOTECRAFT_DEBUG_LOG_DIR=/tmp/notecraft-debug` —
each subprocess call writes a `<ts>-<cmd>.log` containing argv, stdout,
stderr, returncode, and duration. This is what unblocked the #46
investigation (vendor `video` exits 0 but only emits a URL; without
stdout capture the failure looked like silent upstream loss).
