# LLM-Wiki v2.0

> **中文** · [English](./README.en.md)

NotebookLM-first 个人多模态知识库 OS。NotebookLM 负责主 RAG、source-grounded 生成和 notebook 内编排；LLM-Wiki 负责采集、任务编排、workspace 复用、产物沉淀、Obsidian/wiki、Git 和 E2E 自动化。

- **Source**：多源异构碎片资料（网页、语音、图片、PDF）
- **NotebookLM**：主 RAG / source 编排 / 报告、音频、幻灯片等生成
- **LLM-Wiki**：本地控制面、持久化、状态机、Obsidian 双链和验证层

## Quickstart

完整安装、配置、凭据、API key、自动 push 一站式指南：**[docs/SETUP.md](docs/SETUP.md)**

最短路径（详见 SETUP）：
```bash
uv sync
git -c protocol.file.allow=always submodule update --init --recursive
(cd vendor/notebooklm && npm i && npm run build) && npm i ./vendor/notebooklm --no-save

# 复制配置模板，按需填入你的 key（也可走 env 覆盖，见各 .example 注释）
cp gateway.toml.example gateway.toml
cp imagen.toml.example  imagen.toml
cp im.toml.example      im.toml

uv run wikictl gateway init && uv run wikictl im init && uv run wikictl imagen init && uv run wikictl stt init && uv run wikictl autopilot init
npx notebooklm export-session
uv run wikictl daemon
```

## 架构

```
raw/    收件箱（PDF、剪藏、录音）
wiki/   结构知识区（Markdown + 双向链接）
assets/ 多模态产物（音/视频/PPT/抽认卡）
```

Vault 根 = 项目根 = git 仓库。后台守护进程扫 frontmatter 的 `task/*` 标签，自动调 [notecraft](vendor/notebooklm/) 驱动 NotebookLM 生成播客 / 报告 / 幻灯片 / 视频 / 抽认卡，落盘后自动 git commit；按需走 `autopilot.toml` 推到私仓。

详细产品边界和阶段规划见 **[NotebookLM-first Roadmap](docs/NOTEBOOKLM_FIRST_ROADMAP.md)**。

## 子系统一览

每个子系统都有独立 init / start / 配置文件，详细字段、env var、凭据见 [docs/SETUP.md](docs/SETUP.md)。

| 子系统 | 文件 | 作用 |
|--------|------|------|
| **Gateway** | `gateway.toml` | LiteLLM proxy + 本地 wiki/RAG 辅助注入，统一暴露 OpenAI/Anthropic/Gemini 三家协议入口（端口 8080） |
| **IM** | `im.toml` | Telegram bot + HTTP `/ingest`（8081）→ `raw/`；斜杠命令注入 `task/*` 标签 |
| **Imagen** | `imagen.toml` | `task/gen-image` 反向生图；OpenAI / Gemini 两种 backend |
| **STT** | `stt.toml` | Whisper 转录；语音消息走 `task/transcribe` 落到 `wiki/` |
| **Notecraft** | (vendor) | NotebookLM 自动化；workspace id 持久化进 `<vault>/.llmwiki/notebooks.json`，跨任务复用，是主生成路径 |
| **Autopilot** | `autopilot.toml` | 5s debounce → `[Auto] commit`；可选自动 push 到私仓（默认关） |

## 状态

MVP 闭环开发中，进度见 [Issues](../../issues) 与 [MVP closed loop](../../milestone/1) milestone。完整 PRD 与延后子系统见 epic issue **PRD v2.0 全景**。

## wikicraft (Claude Code skill)

`.claude/skills/wikicraft/SKILL.md` —— 把 raw/ 笔记**编织进** wiki/ 双向链接知识网络的 Claude Code skill。三个动作：`/wikicraft absorb`（喂新素材）/ `cleanup`（审计现有文章）/ `breakdown`（识别缺失文章）。继承 farzaa [personal-wiki-skill](https://gist.github.com/farzaa/c35ac0cfbeb957788650e36aabea836d) 的"理解而非归档"理念，适配本仓 Obsidian + watcher 架构。查询走 `wikictl rag query`，状态走 `wikictl status`。
