# E2E Playbook

This directory has two E2E layers:

- **Local E2E**: no external services. Runs real local process / filesystem
  boundaries for IM HTTP ingest and the raw -> watcher -> wiki closed loop.
- **Live E2E**: real external services. Marked `live`; requires credentials,
  sessions, or LAN services and must pass 3 consecutive calls when that
  integration changes.

## Local E2E

```bash
uv run pytest tests/e2e -q -m "e2e and not live"
uv run wikictl test-matrix --local-e2e
```

Current local coverage:

- `test_im_http_process_e2e.py`: starts `uv run wikictl im http` on localhost
  and verifies JSON ingest + token rejection over a real socket.
- `test_local_closed_loop_e2e.py`: exercises raw note + `LabelWatcher` + fake
  local task + `ingest.move_to_wiki` + run record without NotebookLM.
- `test_graph_audit_e2e.py`: runs `uv run wikictl graph audit` over a sample
  vault and verifies links, embeds, provenance, and graph summary over the real
  CLI boundary.
- `test_gateway_skeleton_e2e.py`: starts the local gateway shell and verifies
  the OpenAI/Anthropic/Gemini routes are present.

## NotebookLM Live E2E

This is the manual reproducibility doc for issues #38 and #46.

`tests/e2e/test_notecraft_e2e.py` covers `npx notebooklm list` x3, a short
real audio-generation smoke when a NotebookLM session is available, and
`source-add` x3 when `LLMWIKI_E2E_SOURCE_ADD_NB_ID` is set. The full 9
generation task matrix (audio, flashcards, slides, quiz, infographic,
data-table, source-add, chat, video) hits the live NotebookLM service, takes
30-60 minutes total, and is kept in the helper script below.

### Pre-flight

```bash
uv run wikictl status
cd vendor/notebooklm && npx notebooklm list --transport auto
uv run pytest tests/ --ignore=tests/e2e
```

Pick an existing notebook id from `npx notebooklm list` for the
`source-add` and `chat` tasks (they require a live notebook).

For the pytest live source-add gate:

```bash
LLMWIKI_E2E_SOURCE_ADD_NB_ID=<some-existing-notebook-id> \
  uv run pytest tests/e2e/test_notecraft_e2e.py::test_source_add_real_thrice -q
```

### Run

```bash
NB_ID=<some-existing-notebook-id> ./tests/e2e/run-real-e2e.sh
```

The script writes one note per task under `raw/`, calls
`uv run wikictl run-task` synchronously, and prints the resulting
artifact path / frontmatter status. All 9 tasks use the same source URL
`https://en.wikipedia.org/wiki/Markdown` for stable, low-CDN test
content.

### Expected results

- audio: `assets/audio/audio_*.mp4` (vendor saves mp4 container, not mp3)
- flashcards: `assets/flashcards/flashcards_*.html`
- slides: `assets/slides/slides_*.pdf`
- quiz: `assets/quiz/quiz_*.html`
- infographic: `assets/infographic/infographic_*.png` (vendor poll ≤300s + CDN retry ≤550s, task timeout 900s)
- data-table: `assets/data-table/data_table_*.json`
- source-add: notebook gains a new source row (no upstream dedupe — same URL added twice creates two rows); note gets `notecraft_source_added_to` and `source_added_at` in frontmatter
- chat: answer appended to note body under `## Chat: <question>`
- video: **no local file** — frontmatter gains `video_url` (stream/hls/download URL from NotebookLM); body prepended with `[Video overview](<url>)` link

### Failure classification

- **Our bug** — Python exception, missing handler, wrong CLI flag: stop
  and fix.
- **Upstream flake** — `429`, `SessionExpired`, TLS errors, transient
  HTTP 5xx, timeout: re-run; if it persists, document and continue.

### Logs

The script logs to `/tmp/e2e-38-run-<UTC timestamp>.log` (gitignored).

For boundary cases set `NOTECRAFT_DEBUG_LOG_DIR=/tmp/notecraft-debug` —
each subprocess call writes a `<ts>-<cmd>.log` containing argv, stdout,
stderr, returncode, and duration. This is what unblocked the #46
investigation (vendor `video` exits 0 but only emits a URL; without
stdout capture the failure looked like silent upstream loss).

## STT Live E2E

```bash
LLMWIKI_E2E_STT_BASE_URL=http://192.168.10.2:8000 \
LLMWIKI_E2E_STT_AUDIO=/path/to/sample.wav \
uv run pytest tests/e2e/test_live_stt_e2e.py -q
```

Optional:

- `LLMWIKI_E2E_STT_LANGUAGE=auto`
- `LLMWIKI_E2E_STT_TIMEOUT=300`

## Imagen Live E2E

```bash
LLMWIKI_E2E_IMAGEN=1 \
LLMWIKI_E2E_IMAGEN_BACKEND=gemini \
LLMWIKI_E2E_IMAGEN_BASE_URL=https://... \
LLMWIKI_E2E_IMAGEN_KEY=... \
LLMWIKI_E2E_IMAGEN_MODEL=... \
uv run pytest tests/e2e/test_live_imagen_e2e.py -q
```

If `LLMWIKI_E2E_IMAGEN_KEY` is unset, the test falls back to
`LLMWIKI_IMAGEN_KEY`.
