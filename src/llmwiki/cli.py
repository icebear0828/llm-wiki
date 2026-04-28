from __future__ import annotations

import shutil
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(no_args_is_help=True, add_completion=False)
context_app = typer.Typer(no_args_is_help=True, help="CLI context file management")
app.add_typer(context_app, name="context")

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

_ASSET_DIRS = ("audio", "video", "slides", "report", "quiz")


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

    import threading

    shutdown = threading.Event()

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
        shutdown.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    watcher.start()
    autopilot.start()
    console.print(f"[green]daemon running[/green] vault={cfg.vault_root}")
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
    if not note_path.exists():
        note_path.write_text(
            f"---\ntitle: 'arxiv:{arxiv_id}'\narxiv_id: '{arxiv_id}'\n"
            f"tags: [task/arxiv]\nstatus: pending\n---\n",
            encoding="utf-8",
        )
        console.print(f"[dim]created[/dim] {note_path.relative_to(root)}")

    try:
        result = _arxiv.run(Note(note_path), arg=id_or_url)
    except _nc.NotecraftError as exc:
        console.print(f"[red]arxiv ingest failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    pdf = result.get("arxiv_pdf")
    if pdf is not None:
        try:
            console.print(f"[green]✓ ingested arxiv:{arxiv_id}[/green] → {pdf.relative_to(root)}")
        except ValueError:
            console.print(f"[green]✓ ingested arxiv:{arxiv_id}[/green] → {pdf}")


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
        
    notes_by_stem: dict[str, Note] = {}
    for d in (vault.raw, vault.wiki):
        if not d.is_dir(): continue
        for md in d.rglob("*.md"):
            try:
                note = Note(md)
                notes_by_stem[md.stem] = note
            except Exception:
                continue

    now = time.time()
    to_delete: list[str] = []
    keys_to_remove: list[str] = []

    for stem, nb_id in items:
        note = notes_by_stem.get(stem)
        if note is None:
            # Orphan
            to_delete.append(nb_id)
            keys_to_remove.append(stem)
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
            keys_to_remove.append(stem)

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
