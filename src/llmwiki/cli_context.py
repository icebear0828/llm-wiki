from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llmwiki.vault import Vault  # type: ignore[import-not-found]


_FALLBACK_TASKS = ["audio", "report", "slides", "video", "flashcards"]
_TREE_IGNORE = "node_modules|vendor|__pycache__|.git|.venv|.pytest_cache|.ruff_cache"
_GENERATED_MARKER = "<!-- llmwiki:cli-context -->"

# AGENTS.md is the source of truth (Codex / OpenClaw / Hermes convention).
# CLAUDE.md and GEMINI.md are symlinks so Claude Code and Gemini CLI pick up
# the same instructions without duplication.
_PRIMARY = "AGENTS.md"
_ALIASES = ("CLAUDE.md", "GEMINI.md")


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
language: en                       # optional; passed to vendor `-l` for audio/report/video/infographic/slides/data-table
tags: [task/audio, task/slides]    # task/* triggers background generation
status: pending                    # pending | processing | done | error
arxiv_id: "2401.12345"             # optional; consumed by task/arxiv
youtube_id: "tj8ggd8UvB0"          # optional; consumed by task/youtube
notebook_scope: topic              # optional; topic shares one NotebookLM workspace across notes
notebook_key: topics/ai-agents     # optional; NotebookIndex key when scope is topic
notebook_id: "abc123"              # optional; explicit NotebookLM workspace override
artifacts:                         # written back by watcher
  audio: assets/audio/x.mp3
  slides: assets/slides/x.pdf
---
```"""

_LAYOUT_BLOCK = """- `raw/` — Inbox (raw PDFs, web clippings, recordings, externally imported notes)
- `wiki/` — Structured knowledge zone (finalized Markdown with bidirectional links)
- `assets/{audio,video,slides,report,quiz,flashcards,arxiv,youtube}/` — NotebookLM/Notecraft artifacts + arxiv PDFs + YouTube transcripts
- `vendor/notebooklm/` — git submodule; primary RAG/generation commands via `npx notebooklm <cmd>`
- `src/llmwiki/` — Python package (`wikictl` CLI, watcher, ingest, tasks)"""


def _agents_md(vault_root: Path, tasks: list[str]) -> str:
    tree = _render_tree(vault_root)
    task_lines = "\n".join(f"- `#task/{name}` — triggers `tasks.{name}.run(note)`" for name in tasks)
    return f"""# AGENTS.md — LLM-Wiki Vault

> Auto-generated. Edit `src/llmwiki/cli_context.py` to modify. Run `wikictl context regen` to refresh.
>
> `CLAUDE.md` and `GEMINI.md` are symlinks to this file. Personality lives in `SOUL.md`; user profile in `USER.md`.

## Project Intent

NotebookLM-first personal multimodal knowledge OS. NotebookLM owns primary RAG, source-grounded generation, and notebook-level orchestration. LLM-Wiki owns capture, task orchestration, workspace reuse, artifact persistence, Obsidian/wiki, Git autopilot, and verification. Local RAG is supporting infrastructure for quick wiki lookup, Gateway context, agent context, and offline fallback.

## Vault Layout

{_LAYOUT_BLOCK}

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
                 │ ingest.move_to_wiki(note, artifacts={{...}})
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

{_FRONTMATTER_BLOCK}

Upon completion, the watcher removes the corresponding `task/*` tag, sets `status: done`, and inserts `![[assets/...]]` embeds at the top of the note body.

## Obsidian Syntax Conventions

- Bidirectional links: `[[wiki/topic]]` or `[[topic]]` (shortest link format enabled)
- Attachment embeds: `![[assets/audio/x.mp3]]`, `![[assets/slides/x.pdf]]`
- Tag triggers: adding `task/audio` etc. to the frontmatter `tags` array will be picked up by the watcher
- Link updates: `alwaysUpdateLinks: true` — links auto-follow when files are renamed/moved

## Task Vocabulary (`#task/*`)

{task_lines}

## Current Directory (live)

```
{tree}
```

## Do-Not-Break Guardrails

- Auto-push is opt-in via `<vault>/autopilot.toml` (`[push] enabled = true`); the safe default still only commits locally. Never `git push --force`; if you must rewrite, use `force-with-lease`.
- Do not delete `.obsidian/`: it holds vault config (attachmentFolderPath, link format, etc.).
- Do not bypass the watcher and write `wiki/` directly: it breaks the ingest pipeline and frontmatter state machine.
- Do not hand-edit the `artifacts:` field outside of frontmatter: the watcher owns that field.
- Read the owner agent file before modifying `src/llmwiki/{{notecraft,vault,label_watcher,ingest,git_autopilot}}.py`.

## Hard Rules

- TDD: write pytest first; not done until tests are green.
- Python: use `uv run`; bare `python`/`pip` is forbidden.
- TypeScript: `any` is forbidden.
- E2E: changes involving notecraft / NotebookLM must pass live calls ≥3 consecutive successes.
- Push is opt-in via `autopilot.toml`; default is local-commit-only. `--force` is forbidden; `force-with-lease` is the only allowed history-rewrite path.
- Commit format: `<type>: <description>`; auto-generated artifacts use `[Auto] ...`.
"""


def _resolve_primary(root: Path) -> Path:
    target = root / _PRIMARY
    if target.is_symlink():
        target.unlink()
        return target
    if target.exists():
        try:
            head = target.read_text(encoding="utf-8", errors="ignore")[:4096]
        except OSError as exc:
            raise RuntimeError(f"cannot read {target}: {exc}") from exc
        if _GENERATED_MARKER not in head:
            raise RuntimeError(
                f"refusing to overwrite {target} (no llmwiki marker). "
                f"Move/rename it, or add the marker `{_GENERATED_MARKER}` to opt in."
            )
    return target


def _ensure_alias(root: Path, alias_name: str, target_name: str) -> Path:
    alias = root / alias_name
    if alias.is_symlink():
        try:
            current = alias.readlink()
        except OSError:
            current = None
        if current is not None and Path(current).name == target_name:
            return alias
        alias.unlink()
    elif alias.exists():
        try:
            head = alias.read_text(encoding="utf-8", errors="ignore")[:4096]
        except OSError as exc:
            raise RuntimeError(f"cannot read {alias}: {exc}") from exc
        if _GENERATED_MARKER in head:
            alias.unlink()
        else:
            raise RuntimeError(
                f"refusing to overwrite {alias} (no llmwiki marker, not a symlink). "
                f"Move/rename it to opt in."
            )
    alias.symlink_to(target_name)
    return alias


def regenerate(vault: "Vault | None" = None, vault_root: Path | None = None) -> dict[str, Path]:
    if vault is not None:
        root = Path(vault.root)  # type: ignore[attr-defined]
    elif vault_root is not None:
        root = Path(vault_root)
    else:
        root = Path.cwd()
    root = root.resolve()
    tasks = _load_tasks()

    primary_path = _resolve_primary(root)
    body = f"{_GENERATED_MARKER}\n{_agents_md(root, tasks)}"
    primary_path.write_text(body, encoding="utf-8")

    written: dict[str, Path] = {_PRIMARY: primary_path}
    for alias_name in _ALIASES:
        written[alias_name] = _ensure_alias(root, alias_name, _PRIMARY)
    return written
