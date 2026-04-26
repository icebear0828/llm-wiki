"""Subprocess wrapper around `npx notebooklm` (vendor/notebooklm).

Setup once per checkout:
    git -c protocol.file.allow=always submodule update --init --recursive
    (cd vendor/notebooklm && npm i && npm run build)
    npm i ./vendor/notebooklm --no-save   # so `npx notebooklm` resolves from repo root
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_RELATIVE = Path("node_modules/notebooklm-client/dist/cli.js")

_EXPECTED_EXTS: dict[str, tuple[str, ...]] = {
    "audio": (".mp3", ".wav", ".m4a"),
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


def run(
    cmd: str,
    *,
    source: NoteSource,
    out_dir: Path,
    extra_args: list[str] | None = None,
    timeout: float = 600.0,
    subcommand: str | None = None,
    expect_artifact: bool = True,
) -> Path:
    _ensure_installed()
    out_dir.mkdir(parents=True, exist_ok=True)
    output_args: list[str] = ["-o", str(out_dir)] if expect_artifact else []
    argv = [
        "npx",
        "notebooklm",
        cmd,
        *([subcommand] if subcommand else []),
        "--transport",
        "auto",
        *source.as_args(),
        *output_args,
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
        raise NotecraftError(f"notecraft {cmd} timed out after {timeout}s") from exc

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        cls = _classify(err)
        tail = err[-2000:] if err else f"exit code {result.returncode}"
        raise cls(tail)

    if not expect_artifact:
        return out_dir
    return _newest_artifact(out_dir, cmd, since=start)
