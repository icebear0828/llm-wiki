# LLM-Wiki — SETUP

把这个 vault 从零跑起来要：装依赖 → 写 4 个 toml → 抽一份 NotebookLM session → 起 daemon。下面是按顺序的最短路径。

> 所有命令在仓根（vault 根 = git 仓库根）执行。Python 一律 `uv run`，禁止裸 `python` / `pip`。

---

## 1. 5 分钟 Quickstart

```bash
# 1. Python 依赖
uv sync

# 2. vendor/notebooklm submodule + 构建（首次）
git -c protocol.file.allow=always submodule update --init --recursive
(cd vendor/notebooklm && npm i && npm run build)
npm i ./vendor/notebooklm --no-save     # 让仓根的 npx 找到 cli

# 3. 写四个空模板（已有则跳过）
uv run wikictl gateway init
uv run wikictl im init
uv run wikictl imagen init
uv run wikictl stt init
uv run wikictl autopilot init           # push 默认关，先写出来再编辑

# 4. NotebookLM session（一次）
npx notebooklm export-session           # 弹 Chrome 让你登 Google

# 5. 起 daemon（watcher + git autopilot）
uv run wikictl daemon
```

往 `raw/` 扔一个 `.md`、frontmatter 加 `tags: [task/report]`，watcher 会自动跑 NotebookLM、落产物到 `assets/report/`、迁笔记到 `wiki/`、把产物嵌入文末，最后 autopilot commit 一笔。

---

## 2. 配置文件清单

| 文件 | 子命令 | 必填 | 备注 |
|------|--------|------|------|
| `gateway.toml` | `wikictl gateway init` | 至少一个 `[backends.X]` 的 `api_base` + `api_key` | LiteLLM 反代入口；详见 §5 |
| `im.toml` | `wikictl im init` | `[telegram] bot_token` 或 env `LLMWIKI_TG_TOKEN` | Telegram bot；HTTP /ingest 在 8081 |
| `imagen.toml` | `wikictl imagen init` | `api_key` 或 env `LLMWIKI_IMAGEN_KEY` | `task/gen-image` 用 |
| `stt.toml` | `wikictl stt init` | 可全空 | Whisper 端点（默认 192.168.10.2:8000） |
| `autopilot.toml` | `wikictl autopilot init` | 可全空 | 自动 push（默认关）；详见 §6 |

每个 `init` 都是幂等的：文件已存在就保留不覆盖。

---

## 3. 环境变量

| 变量 | 用途 | 默认 |
|------|------|------|
| `LLMWIKI_VAULT` | 强制指定 vault 根 | 自动从 cwd 向上找 `pyproject.toml + raw/ + wiki/` |
| `LLMWIKI_TG_TOKEN` | Telegram bot token（覆盖 toml） | — |
| `LLMWIKI_IMAGEN_KEY` | Imagen API key（覆盖 toml） | — |
| `LLMWIKI_GATEWAY_YAML` | 强制指定 LiteLLM 生成的 yaml 路径 | `<vault>/.llmwiki/litellm.generated.yaml` |
| `LLMWIKI_RAG_ENABLED` | gateway 注入 RAG 开关 | `1`（开） |
| `LLMWIKI_RAG_TOP_K` | RAG 召回数 | `5` |
| `LLMWIKI_RAG_MIN_Q` | RAG 触发的最小 query 长度 | `10` |
| `NOTECRAFT_DEBUG_LOG_DIR` | notecraft 子进程的 argv/stdout/stderr 落盘路径 | — |
| `NOTEBOOKLM_HOME` | NotebookLM session 存储根 | `~/.notebooklm` |

---

## 4. NotebookLM session

vendor CLI 用 cookie + token 调 Google 私有 API。`session.json` 落 `~/.notebooklm/`。

**首次登录**：
```bash
npx notebooklm export-session
```
弹出 Chrome → 登 Google → 自动落 `~/.notebooklm/session.json`。

**Token 过期（数小时一次）** — vendor 自己刷，你不用管。

**Cookie 过期（数天/周）** — daemon 检测到会 Telegram 推一条 `SessionExpired`。手动恢复：
```bash
npx notebooklm refresh-session    # 优先：cookies 还活着就刷新 token
npx notebooklm export-session     # cookies 也死了：重新登
```

**已经有一个登好了 Google 的 Chrome 实例（CDP 9222）**：
```bash
node vendor/notebooklm/scripts/extract-session-cdp.mjs
# 打开 https://notebooklm.google.com 那个 tab，从 CDP 抽 cookie + tokens 写到 session.json
```

---

## 5. LLM API key 填哪里

**反代统一入口（推荐）**：所有家走一个 LiteLLM proxy，client 端改 base URL 不用改 SDK。

`gateway.toml`：
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

`uv run wikictl gateway start` → 客户端：
```
http://localhost:8080/v1/chat/completions                     # OpenAI 协议
http://localhost:8080/v1/messages                             # Anthropic 协议
http://localhost:8080/v1beta/models/<model>:generateContent   # Gemini 协议
```

`uv run wikictl gateway config` 直接打印三家的环境变量赋值串。

**单独一家**：
- 图像生成：`imagen.toml` 的 `api_key` 或 env `LLMWIKI_IMAGEN_KEY`
- NotebookLM：不用 API key，走浏览器 session（§4）
- Whisper：`stt.toml` 的 `whisper_base_url`，目前指向局域网设备 A

---

## 6. 私有 GitHub 自动同步

Vault 是私人知识库 → 必须私仓 → autopilot 默认只 commit 不 push。开 push：

`autopilot.toml`：
```toml
[push]
enabled = true
remote = "origin"
branch = ""                # 空 = 当前 HEAD
strategy = "fast-forward"  # 或 force-with-lease；--force 永远禁用
debounce_seconds = 30      # commit 后等多久再 push
```

**凭据**：autopilot 不读 token / 不写 token，**全部走 git credential helper**：
- macOS：`git config --global credential.helper osxkeychain`，第一次 `git push` 输一次密码就进 keychain
- Linux：`git config --global credential.helper 'cache --timeout=86400'` 或 `libsecret`
- 推荐 SSH key：`git remote set-url origin git@github.com:<user>/<repo>.git`，钥匙在 `ssh-agent` 里

**non-FF 怎么办**：
- `fast-forward`（默认）：拒绝推，autopilot 把错误写日志 + Telegram 推 `PushFailed`
- `force-with-lease`：本地先 `git fetch`，然后 autopilot 才允许覆盖远端 tip；远端有别人 push 的新提交时仍然拒绝（防丢工作）

---

## 7. NotebookLM 工作区复用（vault 级 RAG）

watcher 跑 audio/video/report/slides/quiz/flashcards/infographic/data-table 时，会：
1. 先查 `<vault>/.llmwiki/notebooks.json`（key = 笔记 stem）
2. 找到就 `npx notebooklm <cmd> --notebook <id>` 复用，否则新建
3. 拿到 notebook id 后写回笔记 frontmatter `notebook_id` + 索引文件

效果：同一篇笔记反复跑生成命令、source 持续累积、上传一次反复用。手动复用某个 notebook：在 frontmatter 加 `notebook_id: <id>` 即可（覆盖索引）。

---

## 8. 常见错误

| 现象 | 原因 / 处理 |
|------|------|
| `Tokens not found` | NotebookLM session 过期；`npx notebooklm refresh-session`，不行就 `export-session` |
| `audio download returned login page` | 同上，cookies 死了 |
| `No session available` | `~/.notebooklm/session.json` 不存在；走 §4 |
| daemon 起不来：端口冲突 | 默认端口：gateway 8080、im /ingest 8081；改 `gateway.toml port` 或 `im.toml http_port` |
| `--force` 报错 | 是设计：CLAUDE.md 硬规则禁用 `--force`；用 `force-with-lease` |
| `notecraft <cmd>` 卡住 / 沉默失败 | `NOTECRAFT_DEBUG_LOG_DIR=/tmp/nc uv run wikictl daemon`，看 `/tmp/nc/*.log` 的 stderr |
| autopilot push 失败但本地 commit 成功 | 看日志 `git_autopilot push failed: <stderr>`，多半是凭据 helper 没装 / SSH key 没加 / non-FF |

---

## 9. 子命令速查

```bash
uv run wikictl --help
uv run wikictl daemon                                # watcher + autopilot
uv run wikictl run-task <task> <note.md>             # 手动跑一次 task
uv run wikictl gateway {init,start,status,config}
uv run wikictl im {init,http,telegram,start}
uv run wikictl imagen {init,generate}
uv run wikictl stt {init,transcribe}
uv run wikictl autopilot init
uv run wikictl rag {reindex,query,stats}
uv run wikictl context regen                          # 刷新 CLAUDE.md/AGENTS.md/GEMINI.md
```
