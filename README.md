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

## IM gateway

外部消息（HTTP webhook、Telegram bot、未来的 Discord/飞书等）经一条共享 ingest 管道落到 `raw/`，被 `wikictl daemon` 接管并按 `task/*` 标签触发 Notecraft 生成。

```bash
uv run wikictl im init           # 写 <vault>/im.toml 模板
uv run wikictl im http           # 只起 HTTP /ingest（端口 8081）
uv run wikictl im telegram       # 只起 Telegram polling
uv run wikictl im start          # 同进程并发起 HTTP + Telegram
```

### HTTP `/ingest`

```bash
# 文本
curl -X POST http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -d '{"kind":"text","payload":"笔记内容","tags":["task/report"]}'

# URL（trafilatura 自动抓正文转 markdown）
curl -X POST http://localhost:8081/ingest \
  -H "Content-Type: application/json" \
  -d '{"kind":"url","payload":"https://en.wikipedia.org/wiki/HTTPS"}'

# 文件上传
curl -X POST http://localhost:8081/ingest/file \
  -F "file=@paper.pdf" -F "tags=task/report"
```

可选鉴权：在 `im.toml` 设 `http_token = "<秘密>"`，请求加 `X-Llmwiki-Token: <秘密>`。

### Telegram bot

1. BotFather 建 bot 拿 token
2. `LLMWIKI_TG_TOKEN=<token> uv run wikictl im start`
3. 给 bot 发：纯文本 / URL / 文档 / 图片 / 语音都会落到 `raw/`
4. 斜杠命令注入 task 标签：`/audio <text>`、`/report <url>`、`/slides`、`/video`、`/flashcards`
5. 默认全开（不限白名单）；要锁就在 `im.toml` 的 `[telegram] allowed_user_ids = [123456]` 填你的 chat id

完整子命令见 `uv run wikictl im --help`。

## STT (Whisper)

设备 A (192.168.10.2:8000) 跑 `mlx-whisper-large-v3` (FastAPI + MLX)，launchd 自启。Telegram 语音消息默认带 `task/transcribe` 标签 → daemon 检测 → 调 A 转录 → 笔记落 `wiki/`，body 顶部嵌入转录正文，segments JSON 存 `assets/transcripts/`。

```bash
uv run wikictl stt init                  # 写 <vault>/stt.toml 模板
uv run wikictl stt transcribe foo.mp3    # 一次性转录单文件
```

支持中/英/日/韩等多语言 auto-detect；frontmatter 自动写入 `language` + `duration_seconds`。

完整子命令见 `uv run wikictl stt --help`。

## Notifications

daemon 在某些异常时直接给你的 Telegram 推送（不需要再去 vault 翻 `assets/ALERT-*.md`）。

配置：在 `im.toml` 的 `[telegram]` 段填 `notify_chat_id`（int）：

```toml
[telegram]
bot_token = "..."         # 或 env LLMWIKI_TG_TOKEN
notify_chat_id = 12345    # 你的 chat_id
```

拿 `chat_id`：先给 bot 发任意一条消息，然后浏览器访问
`https://api.telegram.org/bot<TOKEN>/getUpdates`，`result[0].message.chat.id` 就是。

去抖：每个 `throttle_key` 默认 1 小时窗口内只推一次，状态记在
`<vault>/.llmwiki/notify-state.json`。

当前会触发推送的事件：

- `SessionExpired` —— NotebookLM session 失效，需要 `npx notebooklm export-session`

## Reverse generation (`#task/gen-image`)

笔记 frontmatter 加 `image_prompt: "..."` + tag `task/gen-image` → daemon 调上游图像模型 → 落到 `assets/images/<UTC-ts>-<n>.{png|jpg}` → 笔记顶部插入 `![[...]]`。

支持 OpenAI 风格 (`/v1/images/generations`) 和 Gemini 原生 (`/v1beta/.../generateContent`) 两种 backend，由 `imagen.toml` 的 `backend = "gemini" | "openai"` 切换。

```bash
uv run wikictl imagen init              # 写 <vault>/imagen.toml 模板
uv run wikictl imagen generate "a cat"  # 一次性生图（不入 vault）
```

`image_prompt` 可以是单字符串或字符串数组（一篇笔记多张图）。

完整子命令见 `uv run wikictl imagen --help`。

## wikicraft (Claude Code skill)

`.claude/skills/wikicraft/SKILL.md` —— 把 raw/ 笔记**编织进** wiki/ 双向链接知识网络的 Claude Code skill。三个动作：`/wikicraft absorb`（喂新素材）/ `cleanup`（审计现有文章）/ `breakdown`（识别缺失文章）。继承 farzaa [personal-wiki-skill](https://gist.github.com/farzaa/c35ac0cfbeb957788650e36aabea836d) 的"理解而非归档"理念，适配本仓 Obsidian + watcher 架构。查询走 `wikictl rag query`，状态走 `wikictl status`。
