# Real E2E playbook for the 9 notecraft tasks

This is the manual reproducibility doc for issue #38.

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

- audio: `assets/audio/<stem>.mp3`
- flashcards: `assets/quiz/flashcards_*.html`
- slides: `assets/slides/slides_*.pdf`
- quiz: `assets/quiz/quiz_*.html`
- infographic: `assets/infographic/<stem>.{png,html,...}`
- data-table: `assets/data-table/data_table_*.json`
- source-add: notebook gains a new source; note gets `notecraft_source_added_to` and `source_added_at` in frontmatter
- chat: answer appended to note body under `## Chat: <question>`
- video: `assets/video/<stem>.mp4`

## Failure classification

- **Our bug** — Python exception, missing handler, wrong CLI flag: stop
  and fix.
- **Upstream flake** — `429`, `SessionExpired`, TLS errors, transient
  HTTP 5xx, timeout: re-run; if it persists, document and continue.

## Logs

Append per-run logs to `/tmp/e2e-38-log.md` (gitignored).
