<!-- llmwiki:cli-context -->
# AGENT.md — LLM-Wiki Vault

> 自动生成，编辑请改 `src/llmwiki/cli_context.py`。运行 `wikictl context regen` 刷新。

## 项目意图

个人多模态智能知识库：Obsidian Vault + Git autopilot + Notecraft 自动产物生成。

## Vault 布局

- `raw/` — 收件箱（原始 PDF、剪藏、录音、外部导入的笔记）
- `wiki/` — 结构知识区（最终落盘 Markdown，双向链接网络）
- `assets/{audio,video,slides,report,quiz}/` — Notecraft 多模态产物
- `vendor/notebooklm/` — git submodule，所有生成命令通过 `npx notebooklm <cmd>`
- `src/llmwiki/` — Python 包（`wikictl` CLI、watcher、ingest、tasks）

## 架构数据流

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

## Frontmatter 契约

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

## 任务词表（`#task/*`）

- `#task/audio` — 触发 `tasks.audio.run(note)`
- `#task/report` — 触发 `tasks.report.run(note)`
- `#task/slides` — 触发 `tasks.slides.run(note)`
- `#task/video` — 触发 `tasks.video.run(note)`
- `#task/flashcards` — 触发 `tasks.flashcards.run(note)`

## 当前目录（live）

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

## Do-not-break 防破坏准则

- 不要 `git push`：autopilot 只本地 commit；推送由用户显式触发
- 不要删除 `.obsidian/`：内含 vault 配置（attachmentFolderPath、链接格式等）
- 不要绕过 watcher 直接写 `wiki/`：会破坏 ingest pipeline 与 frontmatter 状态机
- 不要在 frontmatter 之外手动管理 `artifacts:` 字段：watcher 拥有写权
- 修改 `src/llmwiki/{notecraft,vault,label_watcher,ingest,git_autopilot}.py` 前先看 owner agent
- E2E：涉及 notecraft 的改动必须真调 ≥3 次（mock 不算）
