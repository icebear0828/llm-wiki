from __future__ import annotations

import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import frontmatter

from llmwiki.im.config import ImConfig
from llmwiki.vault import Vault

MessageKind = Literal["text", "url", "file", "voice"]


@dataclass(frozen=True)
class IncomingMessage:
    kind: MessageKind
    text: str | None = None
    url: str | None = None
    file_path: Path | None = None
    voice_path: Path | None = None
    source: str = "unknown"
    tags: list[str] = field(default_factory=list)
    title: str | None = None


def slugify(text: str, *, max_len: int = 40) -> str:
    if not text:
        return "msg"
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    replaced = re.sub(r"[^a-z0-9]+", "-", lowered)
    collapsed = re.sub(r"-+", "-", replaced).strip("-")
    if not collapsed:
        return "msg"
    trimmed = collapsed[:max_len].rstrip("-")
    return trimmed or "msg"


def _timestamp(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y%m%d-%H%M%S")


def _iso_now(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.isoformat()


def _dedup_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _atomic_write(path: Path, data: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    if not data.endswith("\n"):
        data += "\n"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _first_line_title(text: str, *, max_len: int = 80) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "untitled"
    return line[:max_len].rstrip()


def _slug_from_words(text: str, n_words: int = 6) -> str:
    words = re.split(r"\s+", text.strip())[:n_words]
    return slugify(" ".join(words))


def _fetch_url_markdown(url: str, timeout: int) -> tuple[str | None, str | None]:
    import trafilatura

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as e:
        return None, f"fetch error: {e}"
    if downloaded is None:
        return None, "fetch returned no content"
    try:
        extracted = trafilatura.extract(
            downloaded,
            output_format="markdown",
            include_links=True,
            url=url,
        )
    except Exception as e:
        return None, f"extract error: {e}"
    if not extracted:
        return None, "extraction returned empty"
    return extracted, None


def ingest(msg: IncomingMessage, vault: Vault, cfg: ImConfig) -> Path:
    raw_dir = vault.raw
    raw_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = _timestamp(now)
    iso = _iso_now(now)

    kind_default_tags: list[str] = []
    metadata: dict[str, object] = {"created": iso, "status": "pending"}
    body = ""
    filename: str

    if msg.kind == "text":
        text_body = msg.text or ""
        slug = _slug_from_words(text_body)
        filename = f"{ts}-{slug}.md"
        title = msg.title or _first_line_title(text_body)
        metadata["title"] = title
        metadata["source"] = msg.source
        body = text_body if text_body.endswith("\n") or not text_body else text_body + "\n"

    elif msg.kind == "url":
        url = msg.url or ""
        title = msg.title or url
        slug_seed = msg.title or url
        slug = slugify(slug_seed)
        filename = f"{ts}-{slug}.md"
        metadata["title"] = title
        metadata["source"] = msg.source
        metadata["source_url"] = url
        if cfg.url_fetch_enabled and url:
            extracted, err = _fetch_url_markdown(url, cfg.url_fetch_timeout)
            if extracted:
                body = f"{extracted.rstrip()}\n\n---\n\nSource: {url}\n"
            else:
                body = f"Source: {url}\n\n_(fetch failed: {err})_\n"
        else:
            body = f"Source: {url}\n"

    elif msg.kind == "file":
        if msg.file_path is None:
            raise ValueError("file_path required for kind=file")
        src = Path(msg.file_path)
        if not src.is_file():
            raise FileNotFoundError(f"file_path does not exist: {src}")
        copied_name = f"{ts}-{src.name}"
        copied = raw_dir / copied_name
        shutil.copy2(src, copied)
        stem = Path(copied_name).stem
        filename = f"{stem}.md"
        title = msg.title or src.stem
        metadata["title"] = title
        metadata["source"] = msg.source
        metadata["source_file"] = f"raw/{copied_name}"
        body = f"![[raw/{copied_name}]]\n"

    elif msg.kind == "voice":
        if msg.voice_path is None:
            raise ValueError("voice_path required for kind=voice")
        src = Path(msg.voice_path)
        if not src.is_file():
            raise FileNotFoundError(f"voice_path does not exist: {src}")
        copied_name = f"{ts}-{src.name}"
        copied = raw_dir / copied_name
        shutil.copy2(src, copied)
        stem = Path(copied_name).stem
        filename = f"{stem}.md"
        title = msg.title or src.stem
        metadata["title"] = title
        metadata["source"] = msg.source
        metadata["source_file"] = f"raw/{copied_name}"
        body = f"![[raw/{copied_name}]]\n"
        kind_default_tags = ["task/voice"]

    else:
        raise ValueError(f"unknown kind: {msg.kind}")

    tags = _dedup_preserve(list(cfg.default_tags) + list(msg.tags) + kind_default_tags)
    if tags:
        metadata["tags"] = tags

    target = raw_dir / filename
    post = frontmatter.Post(content=body, **metadata)
    data = frontmatter.dumps(post)
    _atomic_write(target, data)
    return target
