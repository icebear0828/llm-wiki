<!-- llmwiki:cli-context -->
# GEMINI.md — LLM-Wiki Vault

> 自动生成。运行 `wikictl context regen` 刷新。

## 布局

- `raw/` — 收件箱（原始 PDF、剪藏、录音、外部导入的笔记）
- `wiki/` — 结构知识区（最终落盘 Markdown，双向链接网络）
- `assets/{audio,video,slides,report,quiz}/` — Notecraft 多模态产物
- `vendor/notebooklm/` — git submodule，所有生成命令通过 `npx notebooklm <cmd>`
- `src/llmwiki/` — Python 包（`wikictl` CLI、watcher、ingest、tasks）

## Frontmatter

```yaml
---
title: "..."
source: "https://..."
created: 2026-04-25T09:05:00+08:00
tags: [task/audio, task/slides]   # task/* 触发后台生成
status: pending                    # pending | processing | done | error
artifacts:                         # watcher 写回
  audio: assets/audio/x.mp3
  slides: assets/slides/x.pdf
---
```

## 任务词表

- `#task/audio` — 触发 `tasks.audio.run(note)`
- `#task/report` — 触发 `tasks.report.run(note)`
- `#task/slides` — 触发 `tasks.slides.run(note)`
- `#task/video` — 触发 `tasks.video.run(note)`
- `#task/flashcards` — 触发 `tasks.flashcards.run(note)`

## 当前目录

```
wiki-cli/
├── assets/
│   ├── audio/
│   ├── quiz/
│   ├── report/
│   ├── slides/
│   └── video/
├── raw/
├── src/
│   └── llmwiki/
├── tests/
│   ├── test_cli.py
│   ├── test_cli_context.py
│   └── test_smoke.py
├── wiki/
├── CLAUDE.md
├── README.md
├── pyproject.toml
└── uv.lock
```
