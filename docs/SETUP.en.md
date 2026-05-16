# LLM-Wiki — SETUP

> [中文](./SETUP.md) · **English**

To bring this vault up from scratch: install dependencies → write 4 toml files → export a NotebookLM session → start the daemon. The shortest path, in order, follows.

> Run all commands from the repo root (vault root = git repo root). Always use `uv run` for Python; bare `python` / `pip` is forbidden.

---

## 1. 5-minute Quickstart

```bash
# 1. Python deps
uv sync

# 2. vendor/notebooklm submodule + build (first time)
git -c protocol.file.allow=always submodule update --init --recursive
(cd vendor/notebooklm && npm i && npm run build)
npm i ./vendor/notebooklm --no-save     # so npx in the repo root finds the cli

# 3. Write four empty templates (skipped if they already exist)
uv run wikictl gateway init
uv run wikictl im init
uv run wikictl imagen init
uv run wikictl stt init
uv run wikictl autopilot init           # push is off by default; you write the file first, then edit

# 4. NotebookLM session (one-off)
npx notebooklm export-session           # opens Chrome for you to log into Google

# 5. Start the daemon (watcher + git autopilot)
uv run wikictl daemon
```

Drop a `.md` into `raw/` with `tags: [task/report]` in its frontmatter, and the watcher will run NotebookLM, land the artifact in `assets/report/`, move the note to `wiki/`, embed the artifact at the bottom, and let autopilot commit it.

---

## 2. Config file checklist

| File | Subcommand | Required | Notes |
|------|--------|------|------|
| `gateway.toml` | `wikictl gateway init` | At least one `[backends.X]` with `api_base` + `api_key` | LiteLLM reverse proxy entry; see §5 |
| `im.toml` | `wikictl im init` | `[telegram] bot_token` or env `LLMWIKI_TG_TOKEN` | Telegram bot; HTTP /ingest at 8081 |
| `imagen.toml` | `wikictl imagen init` | `api_key` or env `LLMWIKI_IMAGEN_KEY` | Used by `task/gen-image` |
| `stt.toml` | `wikictl stt init` | All optional | Whisper endpoint (defaults to LAN device A at 192.168.10.2:8000) |
| `autopilot.toml` | `wikictl autopilot init` | All optional | Auto-push (off by default); see §6 |

Each `init` is idempotent: existing files are kept untouched.

---

## 3. Environment variables

| Variable | Purpose | Default |
|------|------|------|
| `LLMWIKI_VAULT` | Force the vault root | Walks up from cwd looking for `pyproject.toml + raw/ + wiki/` |
| `LLMWIKI_TG_TOKEN` | Telegram bot token (overrides toml) | — |
| `LLMWIKI_IMAGEN_KEY` | Imagen API key (overrides toml) | — |
| `LLMWIKI_GATEWAY_YAML` | Force the path of the LiteLLM-generated yaml | `<vault>/.llmwiki/litellm.generated.yaml` |
| `LLMWIKI_RAG_ENABLED` | Toggle RAG injection in the gateway | `1` (on) |
| `LLMWIKI_RAG_TOP_K` | RAG retrieval count | `5` |
| `LLMWIKI_RAG_MIN_Q` | Minimum query length to trigger RAG | `10` |
| `NOTECRAFT_DEBUG_LOG_DIR` | Where to dump notecraft subprocess argv/stdout/stderr | — |
| `NOTEBOOKLM_HOME` | NotebookLM session storage root | `~/.notebooklm` |

---

## 4. NotebookLM session

The vendor CLI talks to Google's private API with cookies + tokens. `session.json` lands in `~/.notebooklm/`.

**First-time login**:
```bash
npx notebooklm export-session
```
Opens Chrome → log into Google → `~/.notebooklm/session.json` is written.

**Token expiry (every few hours)** — vendor refreshes itself, no action needed.

**Cookie expiry (days/weeks)** — the daemon detects this and pushes a `SessionExpired` Telegram message. Manual recovery:
```bash
npx notebooklm refresh-session    # preferred: refresh tokens while cookies are still alive
npx notebooklm export-session     # cookies are dead too: log in again
```

**Already have a Chrome instance with Google logged in (CDP 9222)**:
```bash
node vendor/notebooklm/scripts/extract-session-cdp.mjs
# Open the https://notebooklm.google.com tab; this script extracts cookies + tokens via CDP into session.json
```

---

## 5. Where to put your LLM API keys

**Unified reverse proxy (recommended)**: every provider goes through one LiteLLM proxy; clients change the base URL but keep their SDK.

`gateway.toml`:
```toml
port = 8080
master_key = "sk-pick-your-own"

[backends.openai]
api_base = "https://your-proxy.example.com"
api_key  = "sk-..."
models   = ["gpt-4o", "gpt-4o-mini"]

[backends.anthropic]
api_base = "https://your-proxy.example.com"
api_key  = "sk-..."
models   = ["claude-sonnet-4-6", "claude-opus-4-7"]

[backends.gemini]
api_base = "https://your-proxy.example.com"
api_key  = "..."
models   = ["gemini-2.0-flash"]
```

`uv run wikictl gateway start` → clients hit:
```
http://localhost:8080/v1/chat/completions                     # OpenAI protocol
http://localhost:8080/v1/messages                             # Anthropic protocol
http://localhost:8080/v1beta/models/<model>:generateContent   # Gemini protocol
```

`uv run wikictl gateway config` prints ready-to-eval env vars for all three.

**Single provider**:
- Image generation: `imagen.toml` `api_key` or env `LLMWIKI_IMAGEN_KEY`
- NotebookLM: no API key — uses a browser session (§4)
- Whisper: `stt.toml` `whisper_base_url`, currently pointing at LAN device A

---

## 6. Private GitHub auto-sync

The vault is a private knowledge base → must be a private repo → autopilot only commits by default. Enable push:

`autopilot.toml`:
```toml
[push]
enabled = true
remote = "origin"
branch = ""                # empty = current HEAD
strategy = "fast-forward"  # or force-with-lease; --force is permanently disabled
debounce_seconds = 30      # how long to wait after commit before pushing
```

**Credentials**: autopilot does not read or write tokens. **Everything goes through git's credential helper**:
- macOS: `git config --global credential.helper osxkeychain`; first `git push` enters the password into Keychain
- Linux: `git config --global credential.helper 'cache --timeout=86400'` or `libsecret`
- Recommended SSH: `git remote set-url origin git@github.com:<user>/<repo>.git`, with the key in `ssh-agent`

**Non-FF cases**:
- `fast-forward` (default): refuses to push; autopilot logs the error and Telegrams `PushFailed`
- `force-with-lease`: autopilot first `git fetch`es, then is allowed to overwrite the remote tip — but only when no one else has pushed in the meantime (prevents lost work)

---

## 7. NotebookLM workspace reuse (primary RAG backend)

When the watcher runs audio/video/report/slides/quiz/flashcards/infographic/data-table, it:
1. Looks up the frontmatter `notebook_id`
2. If there is no explicit `notebook_id`, looks up `<vault>/.llmwiki/notebooks.json` (key = vault-relative POSIX path, such as `raw/foo.md` or `wiki/foo.md`)
3. If found, calls `npx notebooklm <cmd> --notebook <id>` to reuse the workspace; otherwise creates a fresh one
4. Writes the resulting notebook id back to the note's frontmatter `notebook_id` and to the index file

Effect: the same note can be re-run repeatedly, sources keep accumulating, and uploads happen once and are reused. To manually reuse a notebook: add `notebook_id: <id>` to the frontmatter (overrides the index). Local RAG is supporting infrastructure for quick wiki lookup, Gateway context, agent context, and offline fallback; deep source-grounded orchestration should prefer NotebookLM.

For a topic workspace shared by multiple notes, add:

```yaml
notebook_scope: topic
notebook_key: topics/ai-agents
```

Then inspect the local record with `uv run wikictl notecraft list`, `uv run wikictl notecraft status topics/ai-agents`, or `uv run wikictl notecraft verify`.

---

## 8. Multilingual artifacts

Set `language:` in frontmatter; the watcher passes it as `--language` to vendor/notebooklm for `audio / report / video / infographic / slides / data-table`. Default `en`. Examples: `zh`, `ja`, `ko`, `fr`, `de`, `es`.

```yaml
---
title: My paper
language: zh
tags: [task/audio]
---
```

`task/transcribe` localizes its body header from the language Whisper detects (`## Transcription` for `en`, `## 转录` for `zh`, `## 文字起こし` for `ja`, etc.).

---

## 9. arxiv ingestion

`task/arxiv` resolves an arxiv id or URL → downloads the PDF to `assets/arxiv/<id>.pdf` → fetches metadata from the arxiv API → fills in `title / source / arxiv_id / arxiv_authors / arxiv_published / source_file` and prepends the abstract. Three triggers, all equivalent:

```bash
# CLI (creates a stub note in raw/ and runs the task synchronously)
uv run wikictl arxiv add 2401.12345
uv run wikictl arxiv add https://arxiv.org/abs/2310.06825
uv run wikictl arxiv add https://arxiv.org/pdf/2402.03300v2.pdf
```

```yaml
# Frontmatter
---
arxiv_id: "2401.12345"
tags: [task/arxiv]
---
```

```yaml
# Tag arg form
---
tags: [task/arxiv:2401.12345]
---
```

After ingest the note stays in `raw/` (so you can pile on more `task/*` tags). PDF download is idempotent — running again on the same id won't re-fetch.

---

## 10. Common errors

| Symptom | Cause / fix |
|------|------|
| `Tokens not found` | NotebookLM session expired; `npx notebooklm refresh-session`, fall back to `export-session` |
| `audio download returned login page` | Same — cookies are dead |
| `No session available` | `~/.notebooklm/session.json` doesn't exist; see §4 |
| Daemon won't start: port conflict | Default ports: gateway 8080, im /ingest 8081; change `gateway.toml port` or `im.toml http_port` |
| `--force` errors | By design: `--force` is forbidden by the project's hard rules; use `force-with-lease` |
| `notecraft <cmd>` hangs / fails silently | `NOTECRAFT_DEBUG_LOG_DIR=/tmp/nc uv run wikictl daemon`, then read `/tmp/nc/*.log` for stderr |
| Autopilot push fails but local commit succeeds | Check log `git_autopilot push failed: <stderr>` — usually missing credential helper / SSH key not in agent / non-FF |

---

## 11. Subcommand cheatsheet

```bash
uv run wikictl --help
uv run wikictl daemon                                # watcher + autopilot
uv run wikictl run-task <task> <note.md>             # run a single task manually
uv run wikictl arxiv add <id|url>                    # ingest an arxiv paper
uv run wikictl gateway {init,start,status,config}
uv run wikictl im {init,http,telegram,start}
uv run wikictl imagen {init,generate}
uv run wikictl stt {init,transcribe}
uv run wikictl autopilot init
uv run wikictl rag {reindex,query,stats}
uv run wikictl notecraft {list,status,verify,gc}
uv run wikictl context regen                         # refresh CLAUDE.md/AGENTS.md/GEMINI.md
```
