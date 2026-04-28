"""Subprocess wrapper around `npx notebooklm` (vendor/notebooklm).

Setup once per checkout:
    git -c protocol.file.allow=always submodule update --init --recursive
    (cd vendor/notebooklm && npm i && npm run build)
    npm i ./vendor/notebooklm --no-save   # so `npx notebooklm` resolves from repo root
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

_NOTEBOOK_ID_RE = re.compile(
    r"Notebook:\s*https?://notebooklm\.google\.com/notebook/([\w-]+)"
)


def parse_notebook_id(stderr: str) -> str | None:
    """Extract NotebookLM workspace id from vendor CLI stderr.

    vendor cli.ts emits `console.error(`Notebook: ${notebookUrl}`)` after
    every generation command. Multiple matches return the last (most recent).
    """
    matches = _NOTEBOOK_ID_RE.findall(stderr or "")
    return matches[-1] if matches else None

REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_RELATIVE = Path("node_modules/notebooklm-client/dist/cli.js")

_EXPECTED_EXTS: dict[str, tuple[str, ...]] = {
    "audio": (".mp3", ".wav", ".m4a", ".mp4"),
    "video": (".mp4",),
    "slides": (".pdf",),
    "report": (".md", ".txt"),
    "flashcards": (".json", ".md", ".html"),
    "quiz": (".json", ".md", ".html"),
    "infographic": (".png", ".jpg", ".jpeg", ".svg", ".html"),
    "data-table": (".csv", ".md", ".json"),
}


@dataclass
class NoteSource:
    url: str | None = None
    text: str | None = None
    file: Path | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        set_fields = [n for n, v in self._items() if v is not None]
        if len(set_fields) != 1:
            raise ValueError(
                f"NoteSource requires exactly one of url/text/file/topic; got {set_fields}"
            )

    def _items(self) -> list[tuple[str, object]]:
        return [
            ("url", self.url),
            ("text", self.text),
            ("file", self.file),
            ("topic", self.topic),
        ]

    def as_args(self) -> list[str]:
        for name, value in self._items():
            if value is not None:
                return [f"--{name}", str(value)]
        raise AssertionError("unreachable")


class NotecraftError(Exception):
    pass


class SessionExpired(NotecraftError):
    pass


class RateLimited(NotecraftError):
    pass


def _ensure_installed() -> None:
    cli = REPO_ROOT / _CLI_RELATIVE
    if cli.exists():
        return
    vendor = REPO_ROOT / "vendor" / "notebooklm"
    if not (vendor / "package.json").exists():
        raise NotecraftError(
            f"vendor/notebooklm not initialized at {vendor}; "
            "run `git -c protocol.file.allow=always submodule update --init --recursive`"
        )
    subprocess.run(
        ["npm", "i", str(vendor), "--no-save"],
        cwd=REPO_ROOT,
        check=True,
    )


def _classify(stderr: str) -> type[NotecraftError]:
    s = stderr.lower()
    if "no session available" in s or "audio download returned login page" in s:
        return SessionExpired
    if "rate limited" in s or "429" in s:
        return RateLimited
    return NotecraftError


def _write_debug_log(
    cmd: str,
    argv: list[str],
    *,
    returncode: int | None,
    stdout: str,
    stderr: str,
    duration: float,
    timed_out: bool = False,
) -> None:
    log_dir = os.environ.get("NOTECRAFT_DEBUG_LOG_DIR")
    if not log_dir:
        return
    target = Path(log_dir)
    target.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = target / f"{ts}-{cmd}.log"
    rc_repr = "TIMEOUT" if timed_out else str(returncode)
    body = (
        f"argv={' '.join(argv)}\n"
        f"returncode={rc_repr}\n"
        f"duration_s={duration:.2f}\n"
        f"--- stdout ---\n{stdout}\n"
        f"--- stderr ---\n{stderr}\n"
    )
    path.write_text(body, encoding="utf-8")


def _newest_artifact(out_dir: Path, cmd: str, since: float) -> Path:
    exts = _EXPECTED_EXTS.get(cmd)
    candidates: list[Path] = []
    for p in out_dir.rglob("*"):
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime + 1e-3 < since:
                continue
        except OSError:
            continue
        if exts is None or p.suffix.lower() in exts:
            candidates.append(p)
    if not candidates:
        raise NotecraftError(
            f"no output artifact found in {out_dir} for cmd={cmd} (expected {exts})"
        )
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


@dataclass
class RunResult:
    """Outcome of a notecraft.run call.

    `artifact` is None when expect_artifact=False (the command produced no
    local file); callers wanting the directory should use `out_dir` instead.
    """

    artifact: Path | None
    out_dir: Path
    stdout: str
    stderr: str
    notebook_id: str | None = None


def run(
    cmd: str,
    *,
    source: NoteSource,
    out_dir: Path,
    extra_args: list[str] | None = None,
    timeout: float = 600.0,
    subcommand: str | None = None,
    expect_artifact: bool = True,
    pass_output_dir: bool | None = None,
    return_full: bool = False,
    notebook_id: str | None = None,
) -> Path | RunResult:
    _ensure_installed()
    out_dir.mkdir(parents=True, exist_ok=True)
    if pass_output_dir is None:
        pass_output_dir = expect_artifact
    output_args: list[str] = ["-o", str(out_dir)] if pass_output_dir else []
    notebook_args: list[str] = ["--notebook", notebook_id] if notebook_id else []
    argv = [
        "npx",
        "notebooklm",
        cmd,
        *([subcommand] if subcommand else []),
        "--transport",
        "auto",
        *source.as_args(),
        *output_args,
        *notebook_args,
        *(extra_args or []),
    ]
    start = time.time()
    try:
        result = subprocess.run(
            argv,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        _write_debug_log(
            cmd,
            argv,
            returncode=None,
            stdout=(exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")),
            stderr=(exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")),
            duration=time.time() - start,
            timed_out=True,
        )
        raise NotecraftError(f"notecraft {cmd} timed out after {timeout}s") from exc

    _write_debug_log(
        cmd,
        argv,
        returncode=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        duration=time.time() - start,
    )

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        cls = _classify(err)
        tail = err[-2000:] if err else f"exit code {result.returncode}"
        raise cls(tail)

    artifact = _newest_artifact(out_dir, cmd, since=start) if expect_artifact else None
    if return_full:
        return RunResult(
            artifact=artifact,
            out_dir=out_dir,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
            notebook_id=parse_notebook_id(result.stderr or ""),
        )
    return artifact if artifact is not None else out_dir

def delete(notebook_ids: list[str]) -> None:
    """Delete one or more notebooks from NotebookLM."""
    if not notebook_ids:
        return
    _ensure_installed()
    argv = ["npx", "notebooklm", "delete", *notebook_ids]
    try:
        subprocess.run(argv, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise NotecraftError(f"notecraft delete failed: {stderr}") from exc
