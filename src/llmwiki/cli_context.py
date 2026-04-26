from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmwiki.vault import Vault  # type: ignore[import-not-found]


_FALLBACK_TASKS = ["audio", "report", "slides", "video", "flashcards"]
_TREE_IGNORE = "node_modules|vendor|__pycache__|.git|.venv|.pytest_cache|.ruff_cache"


def _load_tasks() -> list[str]:
    try:
        from llmwiki.tasks import TASK_REGISTRY  # type: ignore[import-not-found]
    except Exception:
        return list(_FALLBACK_TASKS)
    try:
        names = sorted(TASK_REGISTRY.keys())  # type: ignore[attr-defined]
        return names if names else list(_FALLBACK_TASKS)
    except Exception:
        return list(_FALLBACK_TASKS)


def _python_tree(root: Path, max_depth: int = 2) -> str:
    ignore = set(_TREE_IGNORE.split("|"))
    lines: list[str] = [root.name + "/"]

    def walk(path: Path, depth: int, prefix: str) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(
                [p for p in path.iterdir() if p.name not in ignore and not p.name.startswith(".")],
                key=lambda p: (not p.is_dir(), p.name),
            )
        except OSError:
            return
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                walk(entry, depth + 1, prefix + extension)

    walk(root, 1, "")
    return "\n".join(lines)


def _render_tree(root: Path) -> str:
    if shutil.which("tree"):
        try:
            result = subprocess.run(
                ["tree", "-L", "2", "-I", _TREE_IGNORE, str(root)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout.rstrip()
        except (subprocess.TimeoutExpired, OSError):
            pass
    return _python_tree(root)


_FRONTMATTER_BLOCK = """```yaml
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
```"""

_LAYOUT_BLOCK = """- `raw/` — 收件箱（原始 PDF、剪藏、录音、外部导入的笔记）
- `wiki/` — 结构知识区（最终落盘 Markdown，双向链接网络）
- `assets/{audio,video,slides,report,quiz}/` — Notecraft 多模态产物
- `vendor/notebooklm/` — git submodule，所有生成命令通过 `npx notebooklm <cmd>`
- `src/llmwiki/` — Python 包（`wikictl` CLI、watcher、ingest、tasks）"""


def _render_common(vault_root: Path, tasks: list[str]) -> dict[str, str]:
    tree = _render_tree(vault_root)
    task_lines = "\n".join(f"- `#task/{name}` — 触发 `tasks.{name}.run(note)`" for name in tasks)
    return {
        "layout": _LAYOUT_BLOCK,
        "frontmatter": _FRONTMATTER_BLOCK,
        "tree": tree,
        "task_vocab": task_lines,
    }


def _claude_md(vault_root: Path, tasks: list[str]) -> str:
    c = _render_common(vault_root, tasks)
    return f"""# CLAUDE.md — LLM-Wiki Vault

> 自动生成，编辑请改 `src/llmwiki/cli_context.py`。运行 `wikictl context regen` 刷新。

## 项目意图

个人多模态智能知识库：Obsidian Vault + Git autopilot + Notecraft 自动产物生成。

## Vault 布局

{c["layout"]}

## Frontmatter 契约

`raw/*.md` 与 `wiki/*.md` 同构：

{c["frontmatter"]}

完成后 watcher 移除对应 `task/*`、置 `status: done`、在正文顶部插入 `![[assets/...]]` 嵌入。

## Obsidian 语法约定

- 双向链接：`[[wiki/topic]]` 或 `[[topic]]`（启用 shortest 链接格式）
- 附件嵌入：`![[assets/audio/x.mp3]]`、`![[assets/slides/x.pdf]]`
- 标签触发：在 frontmatter `tags` 数组里写 `task/audio` 等会被 watcher 拾取
- 链接更新：`alwaysUpdateLinks: true`，重命名/移动文件时链接自动跟随

## 任务词表（`#task/*`）

{c["task_vocab"]}

## 当前目录（live）

```
{c["tree"]}
```

## 硬性规则

- TDD：先写 pytest，绿了才算完成
- Python 用 `uv run`，禁止裸 `python`/`pip`
- TypeScript 禁止 `any`
- E2E：涉及 notecraft / NotebookLM 的改动必须真调 ≥3 次连续成功
- No push：`git_autopilot` 只 commit 不 push
- Commit 格式：`<type>: <description>`；自动产物用 `[Auto] ...`
"""


def _agent_md(vault_root: Path, tasks: list[str]) -> str:
    c = _render_common(vault_root, tasks)
    return f"""# AGENT.md — LLM-Wiki Vault

> 自动生成，编辑请改 `src/llmwiki/cli_context.py`。运行 `wikictl context regen` 刷新。

## 项目意图

个人多模态智能知识库：Obsidian Vault + Git autopilot + Notecraft 自动产物生成。

## Vault 布局

{c["layout"]}

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
                 │ ingest.move_to_wiki(note, artifacts={{...}})
                 ▼
          wiki/foo.md  +  ![[assets/audio/foo.mp3]]
                 │
                 ▼
          ┌──────────────┐
          │ GitAutopilot │  5s debounce → [Auto] commit (no push)
          └──────────────┘
```

## Frontmatter 契约

{c["frontmatter"]}

## 任务词表（`#task/*`）

{c["task_vocab"]}

## 当前目录（live）

```
{c["tree"]}
```

## Do-not-break 防破坏准则

- 不要 `git push`：autopilot 只本地 commit；推送由用户显式触发
- 不要删除 `.obsidian/`：内含 vault 配置（attachmentFolderPath、链接格式等）
- 不要绕过 watcher 直接写 `wiki/`：会破坏 ingest pipeline 与 frontmatter 状态机
- 不要在 frontmatter 之外手动管理 `artifacts:` 字段：watcher 拥有写权
- 修改 `src/llmwiki/{{notecraft,vault,label_watcher,ingest,git_autopilot}}.py` 前先看 owner agent
- E2E：涉及 notecraft 的改动必须真调 ≥3 次（mock 不算）
"""


def _gemini_md(vault_root: Path, tasks: list[str]) -> str:
    c = _render_common(vault_root, tasks)
    return f"""# GEMINI.md — LLM-Wiki Vault

> 自动生成。运行 `wikictl context regen` 刷新。

## 布局

{c["layout"]}

## Frontmatter

{c["frontmatter"]}

## 任务词表

{c["task_vocab"]}

## 当前目录

```
{c["tree"]}
```
"""


_GENERATED_MARKER = "<!-- llmwiki:cli-context -->"


def _resolve_target(root: Path, name: str) -> Path:
    for candidate in (root / name, root / name.upper()):
        if candidate.exists():
            try:
                head = candidate.read_text(encoding="utf-8", errors="ignore")[:4096]
            except OSError:
                continue
            if _GENERATED_MARKER in head:
                return candidate
            raise RuntimeError(
                f"refusing to overwrite {candidate} (no llmwiki marker). "
                f"Move/rename it, or add the marker `{_GENERATED_MARKER}` to opt in."
            )
    return root / name


def regenerate(vault: "Vault | None" = None, vault_root: Path | None = None) -> dict[str, Path]:
    if vault is not None:
        root = Path(vault.root)  # type: ignore[attr-defined]
    elif vault_root is not None:
        root = Path(vault_root)
    else:
        root = Path.cwd()
    root = root.resolve()
    tasks = _load_tasks()
    files = {
        "claude.md": _claude_md(root, tasks),
        "agent.md": _agent_md(root, tasks),
        "gemini.md": _gemini_md(root, tasks),
    }
    written: dict[str, Path] = {}
    for name, content in files.items():
        body = f"{_GENERATED_MARKER}\n{content}"
        path = _resolve_target(root, name)
        path.write_text(body, encoding="utf-8")
        written[name] = path
    return written
