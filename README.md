# LLM-Wiki v2.0

个人多模态智能知识库 — Karpathy 风格的"数字第二大脑 OS"。

- **Source**：多源异构碎片资料（网页、语音、图片、PDF）
- **Compiler**：底层大模型 + 自治 Agent
- **Executable**：Obsidian 承载的 Markdown 双向链接网络

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

Vault 根 = 项目根 = git 仓库。后台守护进程扫 frontmatter 的 `task/*` 标签，自动调 [notecraft](vendor/notebooklm/) 生成播客 / 报告 / 幻灯片 / 视频 / 抽认卡，落盘后自动 git commit；按需走 `autopilot.toml` 推到私仓。

## 子系统一览

每个子系统都有独立 init / start / 配置文件，详细字段、env var、凭据见 [docs/SETUP.md](docs/SETUP.md)。

| 子系统 | 文件 | 作用 |
|--------|------|------|
| **Gateway** | `gateway.toml` | LiteLLM proxy，统一暴露 OpenAI/Anthropic/Gemini 三家协议入口（端口 8080） |
| **IM** | `im.toml` | Telegram bot + HTTP `/ingest`（8081）→ `raw/`；斜杠命令注入 `task/*` 标签 |
| **Imagen** | `imagen.toml` | `task/gen-image` 反向生图；OpenAI / Gemini 两种 backend |
| **STT** | `stt.toml` | Whisper 转录；语音消息走 `task/transcribe` 落到 `wiki/` |
| **Notecraft** | (vendor) | NotebookLM 自动化；workspace id 持久化进 `<vault>/.llmwiki/notebooks.json`，跨任务复用 |
| **Autopilot** | `autopilot.toml` | 5s debounce → `[Auto] commit`；可选自动 push 到私仓（默认关） |

## 状态

MVP 闭环开发中，进度见 [Issues](../../issues) 与 [MVP closed loop](../../milestone/1) milestone。完整 PRD 与延后子系统见 epic issue **PRD v2.0 全景**。

## wikicraft (Claude Code skill)

`.claude/skills/wikicraft/SKILL.md` —— 把 raw/ 笔记**编织进** wiki/ 双向链接知识网络的 Claude Code skill。三个动作：`/wikicraft absorb`（喂新素材）/ `cleanup`（审计现有文章）/ `breakdown`（识别缺失文章）。继承 farzaa [personal-wiki-skill](https://gist.github.com/farzaa/c35ac0cfbeb957788650e36aabea836d) 的"理解而非归档"理念，适配本仓 Obsidian + watcher 架构。查询走 `wikictl rag query`，状态走 `wikictl status`。
