from __future__ import annotations

import json
import logging
import shutil
import signal
import subprocess
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
context_app = typer.Typer(no_args_is_help=True, help="CLI context file management")
app.add_typer(context_app, name="context")
graph_app = typer.Typer(no_args_is_help=True, help="Knowledge graph audits")
app.add_typer(graph_app, name="graph")

console = Console()

_DEFAULT_OBSIDIAN_APP_JSON = """{
  "attachmentFolderPath": "assets",
  "alwaysUpdateLinks": true,
  "useMarkdownLinks": false,
  "newLinkFormat": "shortest",
  "showUnsupportedFiles": false,
  "promptDelete": true,
  "showLineNumber": true,
  "readableLineLength": true,
  "strictLineBreaks": false,
  "foldHeading": true,
  "foldIndent": true
}
"""

_ASSET_DIRS = ("audio", "video", "slides", "report", "quiz", "flashcards")


def _discover_vault_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).resolve()
    try:
        from llmwiki.vault import Vault  # type: ignore[import-not-found]

        return Path(Vault.discover().root).resolve()  # type: ignore[attr-defined]
    except Exception:
        return Path.cwd().resolve()


def _ensure_dir(path: Path) -> bool:
    existed = path.exists()
    path.mkdir(parents=True, exist_ok=True)
    gitkeep = path / ".gitkeep"
    if not gitkeep.exists():
        gitkeep.touch()
    return not existed


@app.command()
def init(
    path: Path = typer.Option(Path("."), "--path", "-p", help="Vault root to initialize"),
) -> None:
    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)

    created: list[str] = []
    for sub in ("raw", "wiki"):
        if _ensure_dir(root / sub):
            created.append(sub + "/")
    assets_root = root / "assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    for asset in _ASSET_DIRS:
        if _ensure_dir(assets_root / asset):
            created.append(f"assets/{asset}/")

    obsidian_dir = root / ".obsidian"
    obsidian_dir.mkdir(parents=True, exist_ok=True)
    app_json = obsidian_dir / "app.json"
    if not app_json.exists():
        app_json.write_text(_DEFAULT_OBSIDIAN_APP_JSON, encoding="utf-8")
        created.append(".obsidian/app.json")

    console.print(f"[green]vault initialized at[/green] {root}")
    if created:
        console.print("[cyan]created:[/cyan] " + ", ".join(created))
    else:
        console.print("[dim]already up to date (idempotent)[/dim]")

    vendor = root / "vendor" / "notebooklm"
    if not vendor.exists() or not any(vendor.iterdir()):
        console.print(
            "[yellow]reminder:[/yellow] vendor/notebooklm is empty -- run "
            "`git -c protocol.file.allow=always submodule update --init`"
        )


def _build_rag_indexer(vault: object) -> object | None:
    """Build and return a started IndexerService driving the hybrid index, or
    None if RAG is disabled in gateway config or initialization fails.

    Cold-start: if Chroma is empty, do a one-shot reindex_all() so the daemon
    starts useful immediately. Failures here must NOT abort the daemon — the
    fastembed model download or Chroma init can fail and the rest of the
    watcher pipeline should still run.
    """
    try:
        from llmwiki.gateway.config import GatewayConfig
        from llmwiki.rag.index import WikiIndex
        from llmwiki.rag.indexer_service import IndexerService
        from llmwiki.vault import Vault as _Vault
    except ImportError as e:
        console.print(f"[yellow]rag indexer disabled:[/yellow] {e}")
        return None

    assert isinstance(vault, _Vault)
    cfg = GatewayConfig.load(vault.root)
    if not cfg.rag_enabled:
        return None

    try:
        index = WikiIndex(vault)
        if int(index.stats().get("count", 0)) == 0:
            n = index.reindex_all()
            console.print(f"[cyan]rag cold-start reindex:[/cyan] {n} notes")
        service = IndexerService(vault, index)
        service.start()
        console.print("[green]rag indexer started[/green]")
        return service
    except Exception as e:
        console.print(f"[yellow]rag indexer init failed:[/yellow] {e}")
        return None


def _configure_daemon_logging(vault_root: Path) -> Path:
    log_dir = vault_root / ".llmwiki" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "daemon.log"
    logger = logging.getLogger("llmwiki")
    logger.setLevel(logging.INFO)
    for handler in logger.handlers:
        if getattr(handler, "_llmwiki_daemon_log_path", None) == str(log_path):
            return log_path
    handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    setattr(handler, "_llmwiki_daemon_log_path", str(log_path))
    logger.addHandler(handler)
    return log_path


@app.command()
def daemon(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    try:
        from llmwiki.config import Config
        from llmwiki.git_autopilot import GitAutopilot  # type: ignore[import-not-found]
        from llmwiki.label_watcher import LabelWatcher  # type: ignore[import-not-found]
        from llmwiki.vault import Vault  # type: ignore[import-not-found]
    except ImportError as e:
        console.print(f"[red]missing module:[/red] {e}")
        console.print("[yellow]Run after #2/#3 merged.[/yellow]")
        raise typer.Exit(code=1) from e

    cfg = Config.load(vault_path)
    vault = Vault(cfg.vault_root)  # type: ignore[call-arg]

    im_config = None
    try:
        from llmwiki.im.config import ImConfig
        im_config = ImConfig.load(cfg.vault_root)
    except FileNotFoundError:
        im_config = None
    except ImportError:
        im_config = None

    watcher = LabelWatcher(vault, im_config=im_config)  # type: ignore[call-arg]
    try:
        from llmwiki.autopilot_config import AutopilotConfig
        autopilot_cfg = AutopilotConfig.load(cfg.vault_root)
    except (ImportError, FileNotFoundError, ValueError):
        autopilot_cfg = None
    autopilot = GitAutopilot(  # type: ignore[call-arg]
        vault,
        debounce_seconds=cfg.debounce_seconds,
        autopilot_cfg=autopilot_cfg,
    )
    log_path = _configure_daemon_logging(vault.root)
    logging.getLogger(__name__).info("daemon starting vault=%s", vault.root)

    import threading

    shutdown = threading.Event()
    rag_indexer: object | None = None

    def _stop(*_: object) -> None:
        console.print("[yellow]stopping...[/yellow]")
        try:
            watcher.stop()
        except Exception:
            pass
        try:
            autopilot.stop()
        except Exception:
            pass
        if rag_indexer is not None:
            try:
                rag_indexer.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
        shutdown.set()

    # Install handlers BEFORE _build_rag_indexer (which can block 30-90s on
    # fastembed model download during cold start). The closure reads
    # rag_indexer at signal-delivery time, so the late assignment below is
    # observed correctly.
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    rag_indexer = _build_rag_indexer(vault)
    watcher.start()
    autopilot.start()
    console.print(f"[green]daemon running[/green] vault={cfg.vault_root}")
    console.print(f"[dim]logs[/dim] {log_path.relative_to(vault.root)}")
    # Don't use signal.pause(): SIGCHLD from subprocesses would wake it and
    # let the function return. An Event only set by SIGINT/SIGTERM is correct.
    shutdown.wait()
    sys.exit(0)


@app.command()
def ingest(
    file: Path = typer.Argument(..., exists=True, readable=True),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Add task tag, e.g. task/audio"),
    source_url: str | None = typer.Option(None, "--source-url"),
    title: str | None = typer.Option(None, "--title"),
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    import frontmatter

    root = _discover_vault_root(vault_path)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    src = file.resolve()
    now = datetime.now(timezone.utc).isoformat()

    if src.suffix.lower() == ".md":
        target = raw_dir / src.name
        post = frontmatter.load(str(src))
        if title:
            post["title"] = title
        elif "title" not in post.metadata:
            post["title"] = src.stem
        if source_url:
            post["source"] = source_url
        if "created" not in post.metadata:
            post["created"] = now
        if "status" not in post.metadata:
            post["status"] = "pending"
        existing_tags = list(post.metadata.get("tags") or [])
        for t in tag:
            if t not in existing_tags:
                existing_tags.append(t)
        if existing_tags:
            post["tags"] = existing_tags
        target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
        console.print(f"[green]ingested[/green] {target.relative_to(root)}")
    else:
        copied = raw_dir / src.name
        if src != copied:
            shutil.copy2(src, copied)
        wrapper_meta: dict[str, object] = {
            "title": title or src.stem,
            "source_file": f"raw/{src.name}",
            "created": now,
            "status": "pending",
        }
        if source_url:
            wrapper_meta["source"] = source_url
        if tag:
            wrapper_meta["tags"] = list(tag)
        post = frontmatter.Post(content=f"![[raw/{src.name}]]\n", **wrapper_meta)
        wrapper = raw_dir / f"{src.stem}.md"
        wrapper.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
        console.print(f"[green]wrapped[/green] {wrapper.relative_to(root)} -> {src.name}")


@app.command("run-task")
def run_task(
    note: Path = typer.Argument(..., exists=True, readable=True),
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    try:
        from llmwiki.label_watcher import LabelWatcher  # type: ignore[import-not-found]
        from llmwiki.vault import Note, Vault  # type: ignore[import-not-found]
    except ImportError as e:
        console.print(f"[red]missing module:[/red] {e}")
        console.print("[yellow]Run after #2/#3 merged.[/yellow]")
        raise typer.Exit(code=1) from e

    root = _discover_vault_root(vault_path)
    vault = Vault(root)  # type: ignore[call-arg]
    watcher = LabelWatcher(vault)  # type: ignore[call-arg]
    note_obj = Note(note.resolve())  # type: ignore[call-arg]
    watcher._process_note(note_obj)  # type: ignore[attr-defined]
    console.print(f"[green]processed[/green] {note}")


@context_app.command("regen")
def context_regen(
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    from llmwiki import cli_context

    root = _discover_vault_root(vault_path)
    try:
        written = cli_context.regenerate(vault_root=root)
    except RuntimeError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e
    for name, path in written.items():
        console.print(f"[green]wrote[/green] {path}")
    console.print(f"[cyan]{len(written)} files[/cyan]")


@app.command()
def status(
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    import frontmatter

    root = _discover_vault_root(vault_path)
    table = Table(title=f"vault status: {root}")
    table.add_column("path", style="white")
    table.add_column("status")
    table.add_column("task_tags", style="magenta")
    table.add_column("last_modified", style="dim")

    color = {
        "pending": "yellow",
        "processing": "cyan",
        "done": "green",
        "error": "red",
    }

    rows = 0
    for sub in ("raw", "wiki"):
        d = root / sub
        if not d.is_dir():
            continue
        for md in sorted(d.rglob("*.md")):
            try:
                post = frontmatter.load(str(md))
            except Exception:
                continue
            st = str(post.metadata.get("status", "-"))
            tags = post.metadata.get("tags") or []
            task_tags = [t for t in tags if isinstance(t, str) and t.startswith("task/")]
            mtime = datetime.fromtimestamp(md.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            c = color.get(st, "white")
            table.add_row(
                str(md.relative_to(root)),
                f"[{c}]{st}[/{c}]",
                ", ".join(task_tags) or "-",
                mtime,
            )
            rows += 1

    if rows == 0:
        console.print(f"[dim]no notes found under {root}/raw or {root}/wiki[/dim]")
    else:
        console.print(table)


def _iter_note_paths(root: Path, subdir: str) -> list[Path]:
    base = root / subdir
    if not base.is_dir():
        return []
    return sorted(base.rglob("*.md"))


def _agent_docs_check(root: Path) -> dict[str, object]:
    names = ("AGENTS.md", "CLAUDE.md", "GEMINI.md")
    missing: list[str] = []
    resolved: dict[str, str] = {}
    for name in names:
        path = root / name
        if not path.exists() and not path.is_symlink():
            missing.append(name)
            continue
        try:
            resolved[name] = str(path.resolve(strict=True).relative_to(root))
        except RuntimeError:
            return {
                "name": "agent_docs",
                "status": "error",
                "detail": f"{name} symlink loop",
            }
        except FileNotFoundError:
            return {
                "name": "agent_docs",
                "status": "error",
                "detail": f"{name} broken symlink",
            }
        except ValueError:
            resolved[name] = str(path.resolve(strict=True))

    if missing:
        return {
            "name": "agent_docs",
            "status": "warn",
            "detail": "missing=" + ",".join(missing),
        }
    if len(set(resolved.values())) == 1:
        return {"name": "agent_docs", "status": "ok", "detail": resolved["AGENTS.md"]}
    return {
        "name": "agent_docs",
        "status": "warn",
        "detail": "aliases resolve to different targets",
    }


def _doctor_payload(root: Path) -> dict[str, object]:
    import frontmatter

    checks: list[dict[str, object]] = []
    required_dirs = ("raw", "wiki", "assets")
    missing_dirs = [name for name in required_dirs if not (root / name).is_dir()]
    checks.append(
        {
            "name": "vault_layout",
            "status": "error" if missing_dirs else "ok",
            "detail": "missing=" + ",".join(missing_dirs) if missing_dirs else str(root),
        }
    )
    checks.append(_agent_docs_check(root))

    status_counts: dict[str, int] = {}
    raw_notes = _iter_note_paths(root, "raw")
    wiki_notes = _iter_note_paths(root, "wiki")
    invalid_paths: list[str] = []
    pending_tasks = 0
    processing_tasks = 0
    error_notes = 0
    for path in [*raw_notes, *wiki_notes]:
        try:
            post = frontmatter.load(str(path))
        except Exception:
            try:
                invalid_paths.append(str(path.relative_to(root)))
            except ValueError:
                invalid_paths.append(str(path))
            continue
        status_value = str(post.metadata.get("status", "-"))
        status_counts[status_value] = status_counts.get(status_value, 0) + 1
        tags = post.metadata.get("tags") or []
        task_tags = [t for t in tags if isinstance(t, str) and t.startswith("task/")]
        if task_tags and status_value == "pending":
            pending_tasks += len(task_tags)
        if task_tags and status_value == "processing":
            processing_tasks += len(task_tags)
        if status_value == "error":
            error_notes += 1

    checks.append(
        {
            "name": "notes",
            "status": "warn" if invalid_paths else "ok",
            "detail": (
                f"raw={len(raw_notes)} wiki={len(wiki_notes)} invalid={len(invalid_paths)}"
            ),
            "paths": invalid_paths,
        }
    )

    run_files = sorted((root / ".llmwiki" / "runs").glob("*.json"))
    if not run_files:
        checks.append({"name": "runs", "status": "ok", "detail": "none"})
    else:
        latest = run_files[-1]
        try:
            raw_run = json.loads(latest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(
                {
                    "name": "runs",
                    "status": "warn",
                    "detail": f"latest unreadable: {type(exc).__name__}",
                }
            )
        else:
            run_status = str(raw_run.get("status", "unknown")) if isinstance(raw_run, dict) else "unknown"
            note = str(raw_run.get("note", "-")) if isinstance(raw_run, dict) else "-"
            error = raw_run.get("error") if isinstance(raw_run, dict) else None
            detail = f"latest={run_status} note={note}"
            if error:
                detail += f" error={error}"
            checks.append(
                {
                    "name": "runs",
                    "status": "ok" if run_status == "done" else "warn",
                    "detail": detail,
                }
            )

    try:
        from llmwiki.rag.index import WikiIndex
        from llmwiki.vault import Vault

        stats = WikiIndex(Vault(root)).stats()
        indexed = int(stats.get("count", 0))
        detail = f"wiki_files={len(wiki_notes)} indexed={indexed}"
        checks.append(
            {
                "name": "rag_index",
                "status": "ok" if indexed == len(wiki_notes) else "warn",
                "detail": detail,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "rag_index",
                "status": "warn",
                "detail": f"unavailable: {type(exc).__name__}: {exc}",
            }
        )

    summary: dict[str, object] = {
        "root": str(root),
        "raw_notes": len(raw_notes),
        "wiki_notes": len(wiki_notes),
        "pending_tasks": pending_tasks,
        "processing_tasks": processing_tasks,
        "error_notes": error_notes,
        "status_counts": status_counts,
    }
    return {"summary": summary, "checks": checks}


@app.command()
def doctor(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    root = _discover_vault_root(vault_path)
    payload = _doctor_payload(root)
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    summary = payload["summary"]
    checks = payload["checks"]
    assert isinstance(summary, dict)
    assert isinstance(checks, list)

    table = Table(title=f"doctor: {root}")
    table.add_column("check")
    table.add_column("status")
    table.add_column("detail")
    colors = {"ok": "green", "warn": "yellow", "error": "red"}
    for item in checks:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "unknown"))
        status_value = str(item.get("status", "warn"))
        detail = str(item.get("detail", ""))
        color = colors.get(status_value, "white")
        table.add_row(name, f"[{color}]{status_value}[/{color}]", detail)
    console.print(table)
    console.print(
        "[dim]"
        f"raw={summary.get('raw_notes')} "
        f"wiki={summary.get('wiki_notes')} "
        f"pending_tasks={summary.get('pending_tasks')} "
        f"processing_tasks={summary.get('processing_tasks')} "
        f"errors={summary.get('error_notes')}"
        "[/dim]"
    )


@graph_app.command("audit")
def graph_audit(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON"),
) -> None:
    from llmwiki.graph_audit import audit_vault_graph

    root = _discover_vault_root(vault_path)
    payload = audit_vault_graph(root)
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return

    summary = payload["summary"]
    checks = payload["checks"]
    assert isinstance(summary, dict)
    assert isinstance(checks, list)

    table = Table(title=f"graph audit: {root}")
    table.add_column("check")
    table.add_column("status")
    table.add_column("count")
    colors = {"ok": "green", "warn": "yellow", "error": "red"}
    for item in checks:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "unknown"))
        status_value = str(item.get("status", "warn"))
        count = str(item.get("count", 0))
        color = colors.get(status_value, "white")
        table.add_row(name, f"[{color}]{status_value}[/{color}]", count)
    console.print(table)
    console.print(
        "[dim]"
        f"wiki={summary.get('wiki_notes')} "
        f"raw={summary.get('raw_notes')} "
        f"broken_links={summary.get('broken_links')} "
        f"broken_embeds={summary.get('broken_embeds')} "
        f"missing_sources={summary.get('missing_sources')} "
        f"ambiguous_links={summary.get('ambiguous_links')} "
        f"orphans={summary.get('orphans')} "
        f"task_tags_after_done={summary.get('task_tags_after_done')}"
        "[/dim]"
    )


def _test_matrix_checks(
    *,
    include_local_e2e: bool = False,
    include_vendor_test: bool = False,
    include_e2e: bool = False,
) -> list[tuple[str, list[str]]]:
    checks = [
        ("ruff", ["uv", "run", "ruff", "check", "."]),
        ("unit", ["uv", "run", "pytest", "tests/", "--ignore=tests/e2e"]),
        ("build", ["uv", "build"]),
        ("vendor-build", ["npm", "run", "build", "--prefix", "vendor/notebooklm"]),
    ]
    if include_local_e2e:
        checks.append(
            (
                "local-e2e",
                ["uv", "run", "pytest", "tests/e2e", "-q", "-m", "e2e and not live"],
            )
        )
    if include_vendor_test:
        checks.append(("vendor-test", ["npm", "test", "--prefix", "vendor/notebooklm"]))
    if include_e2e:
        checks.append(("e2e", ["uv", "run", "pytest", "tests/e2e", "-q"]))
    return checks


@app.command("test-matrix")
def test_matrix(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print checks without running"),
    include_local_e2e: bool = typer.Option(
        False,
        "--local-e2e",
        help="Also run local E2E tests that do not require external services",
    ),
    include_vendor_test: bool = typer.Option(
        False,
        "--vendor-test",
        help="Also run vendor/notebooklm unit tests",
    ),
    include_e2e: bool = typer.Option(
        False,
        "--e2e",
        help="Also run real-service E2E tests",
    ),
) -> None:
    root = _discover_vault_root(vault_path)
    checks = _test_matrix_checks(
        include_local_e2e=include_local_e2e,
        include_vendor_test=include_vendor_test,
        include_e2e=include_e2e,
    )
    table = Table(title="test matrix")
    table.add_column("check")
    table.add_column("command")
    for name, argv in checks:
        table.add_row(name, " ".join(argv))
    console.print(table)
    if dry_run:
        return

    results: list[dict[str, object]] = []
    overall_ok = True
    for name, argv in checks:
        started = datetime.now(timezone.utc)
        completed = subprocess.run(
            argv,
            cwd=root,
            capture_output=True,
            text=True,
        )
        finished = datetime.now(timezone.utc)
        ok = completed.returncode == 0
        overall_ok = overall_ok and ok
        status = "ok" if ok else "fail"
        color = "green" if ok else "red"
        console.print(f"[{color}]{status}[/{color}] {name}")
        results.append(
            {
                "name": name,
                "argv": argv,
                "status": status,
                "returncode": completed.returncode,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "stdout_tail": (completed.stdout or "")[-4000:],
                "stderr_tail": (completed.stderr or "")[-4000:],
            }
        )
        if not ok:
            break

    payload = {
        "status": "ok" if overall_ok else "fail",
        "checks": results,
        "include_local_e2e": include_local_e2e,
        "include_vendor_test": include_vendor_test,
        "include_e2e": include_e2e,
    }
    out_dir = root / ".llmwiki" / "test-matrix"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not overall_ok:
        raise typer.Exit(code=1)


gateway_app = typer.Typer(no_args_is_help=True, help="API gateway (LiteLLM proxy + RAG)")
app.add_typer(gateway_app, name="gateway")


_GATEWAY_CONFIG_SECTIONS = """\
# Chatbox / OpenAI-compatible tools
OPENAI_API_BASE=http://localhost:{port}/v1
OPENAI_API_KEY={key}

# Claude Code / Anthropic SDK
ANTHROPIC_BASE_URL=http://localhost:{port}
ANTHROPIC_API_KEY={key}

# Gemini CLI / Google AI SDK
GEMINI_API_KEY={key}
GEMINI_API_BASE=http://localhost:{port}/v1beta
"""


def _gateway_yaml_path(vault_root: Path) -> Path:
    return vault_root / ".llmwiki" / "litellm.generated.yaml"


autopilot_app = typer.Typer(no_args_is_help=True, help="Git autopilot config")
app.add_typer(autopilot_app, name="autopilot")


@autopilot_app.command("init")
def autopilot_init(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    from llmwiki.autopilot_config import CONFIG_FILENAME, write_default_template

    root = _discover_vault_root(vault_path)
    target, written = write_default_template(root)
    if written:
        console.print(f"[green]wrote[/green] {target.relative_to(root)}")
        console.print(
            "[dim]Edit autopilot.toml then enable [push]; auto-push uses git "
            "credential helper — never commit tokens.[/dim]"
        )
    else:
        console.print(f"[dim]{CONFIG_FILENAME} already exists, leaving untouched[/dim]")


@gateway_app.command("init")
def gateway_init(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    from llmwiki.gateway.config import CONFIG_FILENAME, write_default_template

    root = _discover_vault_root(vault_path)
    target, written = write_default_template(root)
    if written:
        console.print(f"[green]wrote[/green] {target.relative_to(root)}")
    else:
        console.print(f"[dim]{CONFIG_FILENAME} already exists, leaving untouched[/dim]")


@gateway_app.command("start")
def gateway_start(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
    port: int | None = typer.Option(None, "--port", help="Override gateway.toml port"),
    foreground: bool = typer.Option(
        False, "--foreground/--background", help="Stream proxy logs to stdout"
    ),
    health_timeout: float = typer.Option(20.0, "--health-timeout"),
) -> None:
    from dataclasses import replace

    from llmwiki.gateway.config import GatewayConfig
    from llmwiki.gateway.litellm_config import write_config
    from llmwiki.gateway.server import health_check, start

    root = _discover_vault_root(vault_path)
    cfg = GatewayConfig.load(root)
    if port is not None:
        cfg = replace(cfg, port=port)

    if not cfg.configured_backends():
        console.print(
            "[yellow]warning:[/yellow] no backends have api_base configured. "
            f"Edit {root / 'gateway.toml'} first."
        )

    yaml_path = _gateway_yaml_path(root)
    write_config(cfg, yaml_path)
    console.print(f"[cyan]wrote[/cyan] {yaml_path}")

    proc = start(cfg, yaml_path)
    console.print(f"[green]litellm proxy spawned[/green] pid={proc.pid} port={cfg.port}")
    rag_state = "enabled" if cfg.rag_enabled else "disabled"
    console.print(
        f"[cyan]RAG injection {rag_state}[/cyan] "
        f"top_k={cfg.rag_top_k} min_query_length={cfg.rag_min_query_length}"
    )
    ready = health_check(cfg.port, timeout=health_timeout)
    if not ready:
        console.print("[red]health check failed[/red] (see proxy logs)")
        proc.terminate()
        raise typer.Exit(code=1)
    console.print(f"[green]ready[/green] http://localhost:{cfg.port}")

    if foreground:
        try:
            proc.wait()
        except KeyboardInterrupt:
            proc.terminate()


@gateway_app.command("status")
def gateway_status(
    vault_path: Path | None = typer.Option(None, "--vault"),
    port: int | None = typer.Option(None, "--port"),
) -> None:
    from llmwiki.gateway.config import GatewayConfig
    from llmwiki.gateway.server import health_check

    root = _discover_vault_root(vault_path)
    cfg = GatewayConfig.load(root)
    target_port = port if port is not None else cfg.port
    ok = health_check(target_port, timeout=2.0)
    if ok:
        console.print(f"[green]gateway healthy[/green] port={target_port}")
        raise typer.Exit(code=0)
    console.print(f"[red]gateway not responding[/red] port={target_port}")
    raise typer.Exit(code=1)


@gateway_app.command("config")
def gateway_config(
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    from llmwiki.gateway.config import GatewayConfig

    root = _discover_vault_root(vault_path)
    cfg = GatewayConfig.load(root)
    console.print(_GATEWAY_CONFIG_SECTIONS.format(port=cfg.port, key=cfg.master_key))


rag_app = typer.Typer(no_args_is_help=True, help="Local RAG index over wiki/")
app.add_typer(rag_app, name="rag")


@rag_app.command("reindex")
def rag_reindex(
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    from llmwiki.rag.index import WikiIndex
    from llmwiki.vault import Vault

    root = _discover_vault_root(vault_path)
    vault = Vault(root)
    index = WikiIndex(vault)
    n = index.reindex_all()
    console.print(f"[green]reindexed[/green] {n} notes -> {index.persist_path}")


@rag_app.command("query")
def rag_query(
    text: str = typer.Argument(..., help="Query text"),
    k: int = typer.Option(5, "-k", "--k", help="Top-k results"),
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    from llmwiki.rag.index import WikiIndex
    from llmwiki.vault import Vault

    root = _discover_vault_root(vault_path)
    vault = Vault(root)
    index = WikiIndex(vault)
    hits = index.query(text, k=k)
    if not hits:
        console.print("[dim]no hits[/dim]")
        return
    table = Table(title=f"rag query: {text!r}")
    table.add_column("score", style="cyan", justify="right")
    table.add_column("rel_path", style="white")
    table.add_column("title", style="magenta")
    table.add_column("snippet", style="dim")
    for h in hits:
        table.add_row(f"{h.score:.3f}", h.rel_path, h.title, h.snippet[:120])
    console.print(table)


@rag_app.command("stats")
def rag_stats(
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    from llmwiki.rag.index import WikiIndex
    from llmwiki.vault import Vault

    root = _discover_vault_root(vault_path)
    vault = Vault(root)
    index = WikiIndex(vault)
    info = index.stats()
    table = Table(title="rag stats")
    table.add_column("key", style="cyan")
    table.add_column("value", style="white")
    for key, value in info.items():
        table.add_row(key, str(value))
    console.print(table)


im_app = typer.Typer(no_args_is_help=True, help="IM gateway (HTTP + Telegram)")
app.add_typer(im_app, name="im")


@im_app.command("init")
def im_init(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    from llmwiki.im.config import CONFIG_FILENAME, write_default_template

    root = _discover_vault_root(vault_path)
    target, written = write_default_template(root)
    if written:
        console.print(f"[green]wrote[/green] {target.relative_to(root)}")
    else:
        console.print(f"[dim]{CONFIG_FILENAME} already exists, leaving untouched[/dim]")


@im_app.command("http")
def im_http(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
    port: int | None = typer.Option(None, "--port", help="Override im.toml http_port"),
    host: str = typer.Option("127.0.0.1", "--host"),
) -> None:
    import uvicorn

    from llmwiki.im.config import ImConfig
    from llmwiki.im.http_endpoint import create_app
    from llmwiki.vault import Vault

    root = _discover_vault_root(vault_path)
    cfg = ImConfig.load(root)
    if port is not None:
        from dataclasses import replace

        cfg = replace(cfg, http_port=port)
    vault = Vault(root)
    fastapi_app = create_app(vault, cfg)
    console.print(f"[green]ready[/green] http://{host}:{cfg.http_port}")
    server = uvicorn.Server(
        uvicorn.Config(fastapi_app, host=host, port=cfg.http_port, log_level="info")
    )
    server.run()


@im_app.command("telegram")
def im_telegram(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    import asyncio

    from llmwiki.im.config import ImConfig
    from llmwiki.im.telegram_bot import TelegramBot
    from llmwiki.vault import Vault

    root = _discover_vault_root(vault_path)
    cfg = ImConfig.load(root)
    if not cfg.telegram.bot_token:
        console.print(
            "[red]telegram bot_token is empty[/red] — set env "
            "[bold]LLMWIKI_TG_TOKEN[/bold] or edit im.toml [telegram] bot_token"
        )
        raise typer.Exit(code=1)
    vault = Vault(root)
    bot = TelegramBot(vault, cfg)
    console.print("[green]telegram bot starting (polling)…[/green]")
    try:
        asyncio.run(bot.run_forever())
    except KeyboardInterrupt:
        console.print("[yellow]stopped[/yellow]")
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]telegram bot error:[/red] {e}")
        raise typer.Exit(code=1) from e


@im_app.command("start")
def im_start(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int | None = typer.Option(None, "--port", help="Override im.toml http_port"),
) -> None:
    import asyncio

    import uvicorn

    from llmwiki.im.config import ImConfig
    from llmwiki.im.http_endpoint import create_app
    from llmwiki.im.telegram_bot import TelegramBot
    from llmwiki.vault import Vault

    root = _discover_vault_root(vault_path)
    cfg = ImConfig.load(root)
    if port is not None:
        from dataclasses import replace

        cfg = replace(cfg, http_port=port)
    vault = Vault(root)
    fastapi_app = create_app(vault, cfg)
    server = uvicorn.Server(
        uvicorn.Config(fastapi_app, host=host, port=cfg.http_port, log_level="info")
    )

    bot: TelegramBot | None = None
    if cfg.telegram.bot_token:
        bot = TelegramBot(vault, cfg)
    else:
        console.print(
            "[yellow]warning:[/yellow] telegram bot_token empty — running HTTP only "
            "(set LLMWIKI_TG_TOKEN to enable telegram)"
        )

    async def _main() -> None:
        http_task = asyncio.create_task(server.serve(), name="http")
        console.print(f"[green][http] ready[/green] http://{host}:{cfg.http_port}")
        tg_task: asyncio.Task[None] | None = None
        if bot is not None:
            await bot.start()
            console.print("[green][telegram] ready[/green] (polling)")
            tg_task = asyncio.create_task(bot.run_forever(), name="telegram")

        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _shutdown() -> None:
            stop_event.set()

        for sig_name in ("SIGINT", "SIGTERM"):
            try:
                loop.add_signal_handler(getattr(signal, sig_name), _shutdown)
            except (NotImplementedError, AttributeError):
                pass

        done_task = asyncio.create_task(stop_event.wait(), name="stop")
        watch = [http_task, done_task]
        if tg_task is not None:
            watch.append(tg_task)
        await asyncio.wait(watch, return_when=asyncio.FIRST_COMPLETED)

        console.print("[yellow]shutting down…[/yellow]")
        server.should_exit = True
        if bot is not None:
            await bot.stop()
        if tg_task is not None:
            tg_task.cancel()
            try:
                await tg_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        try:
            await http_task
        except Exception:  # noqa: BLE001
            pass

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        console.print("[yellow]stopped[/yellow]")


stt_app = typer.Typer(no_args_is_help=True, help="Speech-to-text (Whisper)")
app.add_typer(stt_app, name="stt")


@stt_app.command("init")
def stt_init(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    from llmwiki.stt.config import CONFIG_FILENAME, write_default_template

    root = _discover_vault_root(vault_path)
    target, written = write_default_template(root)
    if written:
        console.print(f"[green]wrote[/green] {target.relative_to(root)}")
    else:
        console.print(f"[dim]{CONFIG_FILENAME} already exists, leaving untouched[/dim]")


@stt_app.command("transcribe")
def stt_transcribe(
    audio: Path = typer.Argument(..., exists=True, readable=True),
    language: str | None = typer.Option(None, "--language", "-l"),
    vault_path: Path | None = typer.Option(None, "--vault"),
) -> None:
    from llmwiki.stt.client import WhisperClient, WhisperError
    from llmwiki.stt.config import SttConfig

    root = _discover_vault_root(vault_path)
    cfg = SttConfig.load(root)
    client = WhisperClient(cfg)
    try:
        transcript = client.transcribe(audio, language=language)
    except WhisperError as e:
        console.print(f"[red]whisper error:[/red] {e}")
        raise typer.Exit(code=1) from e
    console.print(transcript.text)


imagen_app = typer.Typer(no_args_is_help=True, help="Reverse image generation")
app.add_typer(imagen_app, name="imagen")


@imagen_app.command("init")
def imagen_init(
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    from llmwiki.imagen.config import CONFIG_FILENAME as _IMAGEN_CFG, write_default_template as _imagen_write

    root = _discover_vault_root(vault_path)
    target, written = _imagen_write(root)
    if written:
        console.print(f"[green]wrote[/green] {target.relative_to(root)}")
    else:
        console.print(f"[dim]{_IMAGEN_CFG} already exists, leaving untouched[/dim]")


@imagen_app.command("generate")
def imagen_generate(
    prompt: str = typer.Argument(..., help="Image prompt"),
    n: int = typer.Option(1, "-n", "--n", help="Number of images"),
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    from llmwiki.imagen.client import ImagenClient, ImagenError
    from llmwiki.imagen.config import ImagenConfig

    root = _discover_vault_root(vault_path)
    cfg = ImagenConfig.load(root)
    try:
        client = ImagenClient(cfg)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1) from e

    out_dir = root / cfg.output_subdir
    try:
        paths = client.generate(prompt, n=n, out_dir=out_dir)
    except ImagenError as e:
        console.print(f"[red]imagen error:[/red] {e}")
        raise typer.Exit(code=1) from e

    for p in paths:
        try:
            rel = p.resolve().relative_to(root.resolve())
            console.print(f"[green]saved[/green] {rel}")
        except ValueError:
            console.print(f"[green]saved[/green] {p}")


arxiv_app = typer.Typer(no_args_is_help=True, help="Ingest arxiv papers (id or URL)")
app.add_typer(arxiv_app, name="arxiv")


@arxiv_app.command("add")
def arxiv_add(
    id_or_url: str = typer.Argument(..., help="arxiv id (2401.12345) or URL"),
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    import frontmatter as _frontmatter

    from llmwiki import notecraft as _nc
    from llmwiki.tasks import arxiv as _arxiv
    from llmwiki.vault import Note

    root = _discover_vault_root(vault_path)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        arxiv_id = _arxiv._parse_arxiv_id(id_or_url)
    except _nc.NotecraftError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    safe_id = arxiv_id.replace("/", "_")
    note_path = raw_dir / f"arxiv-{safe_id}.md"
    # NOTE: do NOT add `task/arxiv` to tags — the CLI runs the ingest
    # synchronously below. Adding the tag would cause a daemon watcher (if
    # running) to dispatch the same task in parallel, racing on frontmatter.
    if not note_path.exists():
        post = _frontmatter.Post(
            "",
            title=f"arxiv:{arxiv_id}",
            arxiv_id=arxiv_id,
            tags=[],
            status="pending",
        )
        body = _frontmatter.dumps(post)
        if not body.endswith("\n"):
            body += "\n"
        note_path.write_text(body, encoding="utf-8")
        console.print(f"[dim]created[/dim] {note_path.relative_to(root)}")

    note = Note(note_path)
    try:
        result = _arxiv.run(note, arg=id_or_url)
    except _nc.NotecraftError as exc:
        console.print(f"[red]arxiv ingest failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    note.set_status("done")
    note.save()

    pdf = result.get("arxiv_pdf")
    if pdf is not None:
        try:
            console.print(f"[green]✓ ingested arxiv:{arxiv_id}[/green] → {pdf.relative_to(root)}")
        except ValueError:
            console.print(f"[green]✓ ingested arxiv:{arxiv_id}[/green] → {pdf}")


youtube_app = typer.Typer(no_args_is_help=True, help="Ingest YouTube videos (id or URL)")
app.add_typer(youtube_app, name="youtube")


@youtube_app.command("add")
def youtube_add(
    id_or_url: str = typer.Argument(..., help="YouTube id or URL (watch / youtu.be / shorts / embed)"),
    vault_path: Path | None = typer.Option(None, "--vault", help="Vault root"),
) -> None:
    import frontmatter as _frontmatter

    from llmwiki import notecraft as _nc
    from llmwiki.tasks import youtube as _youtube
    from llmwiki.vault import Note

    root = _discover_vault_root(vault_path)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    try:
        video_id = _youtube._parse_video_id(id_or_url)
    except _nc.NotecraftError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    note_path = raw_dir / f"youtube-{video_id}.md"
    # NOTE: do NOT add `task/youtube` to tags — the CLI runs the ingest
    # synchronously below. Adding the tag would cause a daemon watcher (if
    # running) to dispatch the same task in parallel, racing on frontmatter.
    if not note_path.exists():
        post = _frontmatter.Post(
            "",
            title=f"youtube:{video_id}",
            youtube_id=video_id,
            tags=[],
            status="pending",
        )
        body = _frontmatter.dumps(post)
        if not body.endswith("\n"):
            body += "\n"
        note_path.write_text(body, encoding="utf-8")
        console.print(f"[dim]created[/dim] {note_path.relative_to(root)}")

    note = Note(note_path)
    try:
        result = _youtube.run(note, arg=id_or_url)
    except _nc.NotecraftError as exc:
        console.print(f"[red]youtube ingest failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    note.set_status("done")
    note.save()

    transcript = result.get("youtube_transcript")
    if transcript is not None:
        try:
            console.print(f"[green]✓ ingested youtube:{video_id}[/green] → {transcript.relative_to(root)}")
        except ValueError:
            console.print(f"[green]✓ ingested youtube:{video_id}[/green] → {transcript}")
    else:
        console.print(f"[green]✓ ingested youtube:{video_id}[/green] (oembed only — no captions available)")


notecraft_app = typer.Typer(no_args_is_help=True, help="NotebookLM automations and workspace management")
app.add_typer(notecraft_app, name="notecraft")


@notecraft_app.command("gc")
def notecraft_gc(
    days: float = typer.Option(7.0, "--days", "-d", help="Retain notebooks newer than N days"),
    vault_path: Path | None = typer.Option(None, "--vault"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Just print what would be deleted"),
) -> None:
    import time
    from llmwiki.vault import Vault, NotebookIndex, Note
    from llmwiki.notecraft import delete

    root = _discover_vault_root(vault_path)
    vault = Vault(root)
    index = NotebookIndex(vault)
    
    items = index.items()
    if not items:
        console.print("[dim]no notebooks in index, nothing to collect[/dim]")
        return
        
    notes_by_relpath: dict[str, Note] = {}
    for d in (vault.raw, vault.wiki):
        if not d.is_dir():
            continue
        for md in d.rglob("*.md"):
            try:
                note = Note(md)
                rel = md.resolve().relative_to(vault.root.resolve()).as_posix()
                notes_by_relpath[rel] = note
            except Exception:
                continue

    now = time.time()
    to_delete: list[str] = []
    keys_to_remove: list[str] = []

    for key, nb_id in items:
        note = notes_by_relpath.get(key)
        if note is None:
            # Orphan
            to_delete.append(nb_id)
            keys_to_remove.append(key)
            continue
            
        status = note.status
        if status in ("pending", "processing"):
            continue
            
        try:
            mtime = note.path.stat().st_mtime
        except OSError:
            continue
            
        age_days = (now - mtime) / 86400.0
        if age_days > days:
            to_delete.append(nb_id)
            keys_to_remove.append(key)

    if not to_delete:
        console.print("[dim]no notebooks eligible for garbage collection[/dim]")
        return

    console.print(f"[yellow]found {len(to_delete)} notebooks to delete[/yellow]")
    if dry_run:
        for k, nb_id in zip(keys_to_remove, to_delete):
            console.print(f" - {k}: {nb_id}")
        return

    chunk_size = 20
    for i in range(0, len(to_delete), chunk_size):
        chunk = to_delete[i:i + chunk_size]
        console.print(f"deleting batch {i//chunk_size + 1} ({len(chunk)} notebooks)...")
        try:
            delete(chunk)
        except Exception as e:
            console.print(f"[red]error deleting batch: {e}[/red]")
            continue
            
        for k in keys_to_remove[i:i + chunk_size]:
            index.remove(k)
            
    index.save()
    console.print("[green]garbage collection completed[/green]")


if __name__ == "__main__":
    app()
