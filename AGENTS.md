<!-- llmwiki:cli-context -->
# AGENTS.md — LLM-Wiki Vault

> Auto-generated. Edit `src/llmwiki/cli_context.py` to modify. Run `wikictl context regen` to refresh.
>
> `CLAUDE.md` and `GEMINI.md` are symlinks to this file. Personality lives in `SOUL.md`; user profile in `USER.md`.

## Project Intent

Personal multimodal intelligent knowledge base: Obsidian Vault + Git autopilot + Notecraft automatic artifact generation.

## Vault Layout

- `raw/` — Inbox (raw PDFs, web clippings, recordings, externally imported notes)
- `wiki/` — Structured knowledge zone (finalized Markdown with bidirectional links)
- `assets/{audio,video,slides,report,quiz,arxiv}/` — Notecraft multimodal artifacts + arxiv PDFs
- `vendor/notebooklm/` — git submodule; all generation commands via `npx notebooklm <cmd>`
- `src/llmwiki/` — Python package (`wikictl` CLI, watcher, ingest, tasks)

## Architecture / Data Flow

```
   user write
       │
       ▼
  raw/foo.md  ──┐  frontmatter: tags=[task/audio]
                │
                ▼
          ┌──────────────┐
          │ LabelWatcher │  watchdog → debounce → parse frontmatter
          └──────┬───────┘
                 │ tasks.audio.run(note)
                 ▼
          ┌──────────────┐         npx notebooklm audio
          │  Notecraft   │ ──────────────────────────► assets/audio/foo.mp3
          └──────┬───────┘
                 │ ingest.move_to_wiki(note, artifacts={...})
                 ▼
          wiki/foo.md  +  ![[assets/audio/foo.mp3]]
                 │
                 ▼
          ┌──────────────┐
          │ GitAutopilot │  5s debounce → [Auto] commit (no push)
          └──────────────┘
```

## Frontmatter Contract

`raw/*.md` and `wiki/*.md` share the same structure:

```yaml
---
title: "..."
source: "https://..."
created: 2026-04-25T09:05:00+08:00
language: en                       # optional; passed to vendor `-l` for audio/report/video/infographic/slides/data-table
tags: [task/audio, task/slides]    # task/* triggers background generation
status: pending                    # pending | processing | done | error
arxiv_id: "2401.12345"             # optional; consumed by task/arxiv
artifacts:                         # written back by watcher
  audio: assets/audio/x.mp3
  slides: assets/slides/x.pdf
---
```

Upon completion, the watcher removes the corresponding `task/*` tag, sets `status: done`, and inserts `![[assets/...]]` embeds at the top of the note body.

## Obsidian Syntax Conventions

- Bidirectional links: `[[wiki/topic]]` or `[[topic]]` (shortest link format enabled)
- Attachment embeds: `![[assets/audio/x.mp3]]`, `![[assets/slides/x.pdf]]`
- Tag triggers: adding `task/audio` etc. to the frontmatter `tags` array will be picked up by the watcher
- Link updates: `alwaysUpdateLinks: true` — links auto-follow when files are renamed/moved

## Task Vocabulary (`#task/*`)

- `#task/arxiv` — triggers `tasks.arxiv.run(note)`
- `#task/audio` — triggers `tasks.audio.run(note)`
- `#task/chat` — triggers `tasks.chat.run(note)`
- `#task/data-table` — triggers `tasks.data-table.run(note)`
- `#task/flashcards` — triggers `tasks.flashcards.run(note)`
- `#task/gen-image` — triggers `tasks.gen-image.run(note)`
- `#task/infographic` — triggers `tasks.infographic.run(note)`
- `#task/quiz` — triggers `tasks.quiz.run(note)`
- `#task/report` — triggers `tasks.report.run(note)`
- `#task/slides` — triggers `tasks.slides.run(note)`
- `#task/source-add` — triggers `tasks.source-add.run(note)`
- `#task/transcribe` — triggers `tasks.transcribe.run(note)`
- `#task/video` — triggers `tasks.video.run(note)`

## Current Directory (live)

```
wiki/
├── assets/
│   ├── arxiv/
│   ├── audio/
│   ├── infographic/
│   ├── slides/
│   └── source-add/
├── docs/
│   ├── SETUP.en.md
│   └── SETUP.md
├── optional-skills/
│   └── llmwiki/
├── raw/
│   ├── arxiv-2310.06825.md
│   ├── arxiv-2401.12345.md
│   └── arxiv-2402.03300v2.md
├── skills/
│   └── wikicraft/
├── src/
│   └── llmwiki/
├── tests/
│   ├── e2e/
│   ├── test_arxiv_task.py
│   ├── test_autopilot_config.py
│   ├── test_chat_task.py
│   ├── test_cli.py
│   ├── test_cli_context.py
│   ├── test_common_language.py
│   ├── test_data_table_task.py
│   ├── test_gateway_cli.py
│   ├── test_gateway_config.py
│   ├── test_gemini_middleware.py
│   ├── test_gen_image_task.py
│   ├── test_git_autopilot.py
│   ├── test_git_autopilot_push.py
│   ├── test_im_common.py
│   ├── test_im_config.py
│   ├── test_im_http.py
│   ├── test_im_telegram.py
│   ├── test_imagen_cli.py
│   ├── test_imagen_client.py
│   ├── test_infographic_task.py
│   ├── test_ingest.py
│   ├── test_label_watcher.py
│   ├── test_litellm_config.py
│   ├── test_litellm_config_with_rag.py
│   ├── test_notebook_index.py
│   ├── test_notebook_lookup.py
│   ├── test_notecraft.py
│   ├── test_notecraft_parse.py
│   ├── test_notify.py
│   ├── test_quiz_task.py
│   ├── test_r2.py
│   ├── test_rag_callback.py
│   ├── test_rag_cli.py
│   ├── test_rag_index.py
│   ├── test_rag_indexer_service.py
│   ├── test_smoke.py
│   ├── test_source_add_task.py
│   ├── test_stt_cli.py
│   ├── test_stt_client.py
│   ├── test_tasks.py
│   ├── test_tasks_notebook_persist.py
│   ├── test_transcribe_task.py
│   ├── test_vault.py
│   └── test_video_task.py
├── wiki/
├── AGENTS.md
├── CLAUDE.md
├── GEMINI.md
├── LICENSE
├── README.en.md
├── README.md
├── SOUL.md
├── USER.md
├── create_analysis_note.py
├── gateway.toml
├── gateway.toml.example
├── im.toml
├── im.toml.example
├── imagen.toml
├── imagen.toml.example
├── pyproject.toml
└── uv.lock
```

## Do-Not-Break Guardrails

- Auto-push is opt-in via `<vault>/autopilot.toml` (`[push] enabled = true`); the safe default still only commits locally. Never `git push --force`; if you must rewrite, use `force-with-lease`.
- Do not delete `.obsidian/`: it holds vault config (attachmentFolderPath, link format, etc.).
- Do not bypass the watcher and write `wiki/` directly: it breaks the ingest pipeline and frontmatter state machine.
- Do not hand-edit the `artifacts:` field outside of frontmatter: the watcher owns that field.
- Read the owner agent file before modifying `src/llmwiki/{notecraft,vault,label_watcher,ingest,git_autopilot}.py`.

## Hard Rules

- TDD: write pytest first; not done until tests are green.
- Python: use `uv run`; bare `python`/`pip` is forbidden.
- TypeScript: `any` is forbidden.
- E2E: changes involving notecraft / NotebookLM must pass live calls ≥3 consecutive successes.
- Push is opt-in via `autopilot.toml`; default is local-commit-only. `--force` is forbidden; `force-with-lease` is the only allowed history-rewrite path.
- Commit format: `<type>: <description>`; auto-generated artifacts use `[Auto] ...`.
