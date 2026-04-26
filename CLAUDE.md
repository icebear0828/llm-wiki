# LLM-Wiki v2.0

个人多模态智能知识库：Obsidian Vault + Git autopilot + Notecraft 自动产物生成。完整 PRD 见 `/Users/c/.claude/plans/prd-agent-team-bubbly-mango.md`。本仓库根 = Vault 根 = git 仓库。

## Vault 布局

- `raw/` — 收件箱（原始 PDF、剪藏、录音、外部导入的笔记）
- `wiki/` — 结构知识区（最终落盘 Markdown，双向链接网络）
- `assets/{audio,video,slides,report,quiz}/` — Notecraft 多模态产物
- `vendor/notebooklm/` — git submodule，所有生成命令通过 `npx notebooklm <cmd>`
- `src/llmwiki/` — Python 包（`wikictl` CLI、watcher、ingest、tasks）

## Frontmatter 契约

`raw/*.md` 与 `wiki/*.md` 同构：

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

完成后 watcher 移除对应 `task/*`、置 `status: done`、在正文顶部插入 `![[assets/...]]` 嵌入。

## 硬性规则

- **TDD**：新增/修改功能先写 pytest，绿了才算完成
- **Python 用 `uv run`**，禁止裸 `python` / `pip`
- **TypeScript 禁止 `any`**（含 `as any`、`: any`、`<any>`）
- **E2E**：涉及 notecraft / NotebookLM 的改动，mock 测试不算完成。必须真调 ≥3 次连续成功
- **No push**：`git_autopilot` 只 commit 不 push；远程推送由用户显式触发
- **Commit 格式**：`<type>: <description>` (feat/fix/refactor/docs/test/chore/perf/ci)；自动产物用 `[Auto] ...`

## 资源指引

- Notecraft 命令表 → `vendor/notebooklm/SKILL.md`
- 各 agent 分工与 issue 对照 → PRD plan 第 "Agent Team 派活" 节
- 当前进度 → GitHub Issues + MVP milestone
