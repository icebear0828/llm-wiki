# LLM-Wiki v2.0

> [中文](./README.md) · **English**

A NotebookLM-first personal multimodal knowledge OS. NotebookLM owns the
primary RAG, source-grounded generation, and notebook-level orchestration;
LLM-Wiki owns capture, task routing, workspace reuse, artifact persistence,
Obsidian/wiki, Git, and E2E automation.

- **Source**: heterogeneous fragments from the wild (web pages, voice notes, images, PDFs)
- **NotebookLM**: primary RAG / source orchestration / reports, audio, slides, and other generated outputs
- **LLM-Wiki**: local control plane, persistence, state machine, Obsidian links, and verification layer

## Quickstart

End-to-end install / config / credentials / API keys / auto-push: **[docs/SETUP.en.md](docs/SETUP.en.md)**

Shortest path (full details in SETUP):
```bash
uv sync
git -c protocol.file.allow=always submodule update --init --recursive
(cd vendor/notebooklm && npm i && npm run build) && npm i ./vendor/notebooklm --no-save

# Copy config templates and fill in your keys (env overrides also work — see each .example for notes)
cp gateway.toml.example gateway.toml
cp imagen.toml.example  imagen.toml
cp im.toml.example      im.toml

uv run wikictl gateway init && uv run wikictl im init && uv run wikictl imagen init && uv run wikictl stt init && uv run wikictl autopilot init
npx notebooklm export-session
uv run wikictl daemon
```

## Architecture

```
raw/    inbox (PDFs, web clips, recordings)
wiki/   structured knowledge zone (Markdown + bidirectional links)
assets/ multimodal artifacts (audio/video/slides/flashcards/arxiv PDFs)
```

Vault root = repo root = git repo. A background daemon scans frontmatter `task/*` tags, calls [notecraft](vendor/notebooklm/) to drive NotebookLM generation for podcasts / reports / slides / videos / flashcards, lands artifacts on disk, and auto-commits via git autopilot. Push to a private remote is opt-in via `autopilot.toml`.

For product boundaries and phased work, see the **[NotebookLM-first Roadmap](docs/NOTEBOOKLM_FIRST_ROADMAP.md)**.

## Subsystems at a glance

Each subsystem has its own init / start / config file. For full field-by-field docs, env vars, and credentials see [docs/SETUP.en.md](docs/SETUP.en.md).

| Subsystem | File | Purpose |
|--------|------|------|
| **Gateway** | `gateway.toml` | LiteLLM proxy plus local wiki/RAG support injection; exposes OpenAI / Anthropic / Gemini protocols on one port (8080) |
| **IM** | `im.toml` | Telegram bot + HTTP `/ingest` (8081) → `raw/`; slash commands inject `task/*` tags |
| **Imagen** | `imagen.toml` | Reverse image generation for `task/gen-image`; OpenAI / Gemini backends |
| **STT** | `stt.toml` | Whisper transcription; voice messages flow through `task/transcribe` into `wiki/` |
| **Notecraft** | (vendor) | NotebookLM automation; workspace ids persist in `<vault>/.llmwiki/notebooks.json`, are reused across tasks, and form the primary generation path |
| **Autopilot** | `autopilot.toml` | 5s-debounced `[Auto] commit`; optional auto-push to a private remote (off by default) |

## Multilingual artifact generation

Set `language:` in a note's frontmatter and the watcher passes it as `--language` to vendor/notebooklm for `audio / report / video / infographic / slides / data-table`. Default is `en`.

```yaml
---
title: My note
language: zh
tags: [task/audio, task/slides]
---
```

`task/transcribe` localizes its body header (`## Transcription` / `## 转录` / `## 文字起こし` / etc.) based on the language Whisper detects.

## arxiv ingestion

Drop an arxiv id or URL via CLI, frontmatter, or tag arg:

```bash
# CLI: creates raw/arxiv-<id>.md, downloads PDF to assets/arxiv/, fills in metadata
uv run wikictl arxiv add 2401.12345
uv run wikictl arxiv add https://arxiv.org/abs/2310.06825
uv run wikictl arxiv add https://arxiv.org/pdf/2402.03300v2.pdf
```

Or write a stub note with frontmatter `arxiv_id: 2401.12345` + `tags: [task/arxiv]`, and the watcher does the same. Once ingested, the PDF is wired into `source_file:` so any downstream task (`task/audio`, `task/slides`, …) reads from the paper directly.

## Status

MVP closed-loop development; see [Issues](../../issues) and the [MVP closed loop](../../milestone/1) milestone. Full PRD and deferred subsystems live in the **PRD v2.0 panorama** epic.

## wikicraft (Claude Code skill)

`.claude/skills/wikicraft/SKILL.md` is a Claude Code skill that **weaves** raw notes into the wiki/ bidirectional-link knowledge network. Three actions: `/wikicraft absorb` (feed new material), `cleanup` (audit existing articles), `breakdown` (find missing articles). Inherits the "understand, not file" philosophy from farzaa's [personal-wiki-skill](https://gist.github.com/farzaa/c35ac0cfbeb957788650e36aabea836d), adapted to this repo's Obsidian + watcher architecture. Queries go through `wikictl rag query`; status through `wikictl status`.
