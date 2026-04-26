# LLM-Wiki v2.0

个人多模态智能知识库 — Karpathy 风格的"数字第二大脑 OS"。

- **Source**：多源异构碎片资料（网页、语音、图片、PDF）
- **Compiler**：底层大模型 + 自治 Agent
- **Executable**：Obsidian 承载的 Markdown 双向链接网络

## 架构

```
raw/    收件箱（PDF、剪藏、录音）
wiki/   结构知识区（Markdown + 双向链接）
assets/ 多模态产物（音/视频/PPT/抽认卡）
```

Vault 根 = 项目根 = git 仓库。后台守护进程扫 frontmatter 的 `task/*` 标签，自动调 [notecraft](https://github.com/) (vendor/notebooklm) 生成播客 / 报告 / 幻灯片 / 视频 / 抽认卡，落盘后自动 git commit。

## 状态

MVP 闭环开发中，进度见 [Issues](../../issues) 与 [MVP closed loop](../../milestone/1) milestone。

完整 PRD 与延后子系统见 epic issue **PRD v2.0 全景**。

## Gateway (LiteLLM)

本地启一个 LiteLLM proxy，同时暴露三家协议入口，转发到用户配置的反代 base URL。给 Chatbox / Claude Code / Gemini CLI 一个统一接入点。

```
http://localhost:8080/v1/chat/completions                       # OpenAI
http://localhost:8080/v1/messages                               # Anthropic
http://localhost:8080/v1beta/models/<model>:generateContent     # Gemini
```

```bash
uv run wikictl gateway init       # 写 <vault>/gateway.toml 模板
uv run wikictl gateway start      # 起 LiteLLM proxy
uv run wikictl gateway status     # /health 检查
uv run wikictl gateway config     # 打印三家客户端环境变量
```

完整子命令见 `uv run wikictl gateway --help`。
