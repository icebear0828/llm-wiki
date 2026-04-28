from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

import httpx

from llmwiki import notecraft

from ._types import NoteLike


# YouTube video IDs are 11 chars from base64url alphabet.
# Anchored to start / `/` / `=` / `:` so we accept watch?v=, /shorts/<id>,
# /embed/<id>, youtu.be/<id>, bare id, and `youtube:<id>` prefix forms.
# Trailing `(?![A-Za-z0-9_-])` rejects 12+ char overmatch (e.g. `tj8ggd8UvB0extra`).
_ID_PATTERN = re.compile(
    r"(?:^|(?<=[/:=]))(?P<id>[A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])",
)
_OEMBED_URL = "https://www.youtube.com/oembed"
_CANONICAL_URL = "https://www.youtube.com/watch?v={id}"


class _PostLike(Protocol):
    metadata: dict[str, object]
    content: str


class _NoteWithPost(Protocol):
    path: Path
    title: str
    source_url: str | None
    source_file: Path | None
    _post: _PostLike

    def prepend_body(self, text: str) -> None: ...
    def save(self) -> None: ...


@dataclass
class _Meta:
    title: str
    author_name: str
    thumbnail_url: str


def _parse_video_id(raw: str) -> str:
    """Extract canonical 11-char YouTube video id from any common URL form, bare id, or `youtube:<id>` prefix."""
    if not raw or not isinstance(raw, str):
        raise notecraft.NotecraftError(f"could not parse youtube id from {raw!r}")
    s = raw.strip()
    # Try urllib first for ?v= queries (handles &t=42s etc. cleanly).
    try:
        parsed = urlparse(s)
        if parsed.query:
            qs = parse_qs(parsed.query)
            v = qs.get("v")
            if v and v[0]:
                cand = v[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", cand):
                    return cand
    except ValueError:
        pass
    match = _ID_PATTERN.search(s)
    if not match:
        raise notecraft.NotecraftError(f"could not parse youtube id from {raw!r}")
    return match.group("id")


def _resolve_video_id(note: NoteLike, arg: str | None) -> str:
    if arg:
        return _parse_video_id(arg)
    post = getattr(note, "_post", None)
    meta = getattr(post, "metadata", None) if post is not None else None
    if isinstance(meta, dict):
        candidate = meta.get("youtube_id")
        if candidate is not None:
            try:
                return _parse_video_id(str(candidate).strip())
            except notecraft.NotecraftError:
                pass
    if note.source_url:
        try:
            return _parse_video_id(note.source_url)
        except notecraft.NotecraftError:
            pass
    raise notecraft.NotecraftError(
        "youtube task requires an id (tag arg, youtube_id frontmatter, or youtube source URL)"
    )


def _http_get(url: str, *, timeout: float = 10.0) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        return client.get(url)


_RETRYABLE_STATUS = {429, 502, 503, 504}


def _assets_youtube_dir(vault_root: Path) -> Path:
    d = vault_root / "assets" / "youtube"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_oembed(video_id: str) -> _Meta:
    target = _CANONICAL_URL.format(id=video_id)
    url = f"{_OEMBED_URL}?url={target}&format=json"
    last_status: int | None = None
    last_err: Exception | None = None
    resp: httpx.Response | None = None
    for attempt in range(2):
        try:
            resp = _http_get(url)
        except httpx.HTTPError as exc:
            last_err = exc
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise notecraft.NotecraftError(f"youtube oembed fetch failed: {exc}") from exc
        last_status = getattr(resp, "status_code", 200)
        if last_status in _RETRYABLE_STATUS and attempt == 0:
            time.sleep(0.5)
            continue
        break
    if resp is None:
        raise notecraft.NotecraftError(f"youtube oembed fetch failed: {last_err}")
    if last_status is not None and last_status >= 400:
        raise notecraft.NotecraftError(f"youtube oembed returned {last_status}")
    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise notecraft.NotecraftError(f"youtube oembed returned non-JSON: {exc}") from exc
    return _Meta(
        title=str(data.get("title") or "").strip(),
        author_name=str(data.get("author_name") or "").strip(),
        thumbnail_url=str(data.get("thumbnail_url") or "").strip(),
    )


def _download_transcript(video_id: str, vault_root: Path) -> Path | None:
    """Download YouTube captions to assets/youtube/<id>.txt. Returns None when no captions available."""
    out_dir = _assets_youtube_dir(vault_root)
    out_path = out_dir / f"{video_id}.txt"
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path

    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import (
        NoTranscriptFound,
        TranscriptsDisabled,
        VideoUnavailable,
    )

    try:
        fetched = YouTubeTranscriptApi().fetch(
            video_id, languages=("zh-Hans", "zh", "en")
        )
    except (TranscriptsDisabled, NoTranscriptFound):
        return None
    except VideoUnavailable as exc:
        raise notecraft.NotecraftError(f"youtube video unavailable: {video_id}") from exc
    except Exception as exc:  # network or parsing failures from the lib
        raise notecraft.NotecraftError(f"youtube transcript fetch failed: {exc}") from exc

    text = "\n".join(getattr(seg, "text", "") for seg in fetched).strip()
    if not text:
        return None
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, out_path)
    return out_path


def _vault_root_for(note_path: Path) -> Path:
    parents = list(note_path.resolve().parents)
    for base in parents:
        if (base / "pyproject.toml").is_file():
            return base
    for base in parents:
        if (base / "raw").is_dir() and (base / "wiki").is_dir():
            return base
    return note_path.resolve().parent


def _writeback(
    note: NoteLike,
    video_id: str,
    meta: _Meta,
    transcript_path: Path | None,
) -> None:
    n: _NoteWithPost = note  # type: ignore[assignment]
    md = n._post.metadata
    md["youtube_id"] = video_id
    md["source"] = _CANONICAL_URL.format(id=video_id)

    existing_title = md.get("title")
    stub_marker = f"youtube:{video_id}"
    is_stub = (
        not isinstance(existing_title, str)
        or not existing_title.strip()
        or existing_title.strip() in (stub_marker, video_id)
    )
    if is_stub and meta.title:
        md["title"] = meta.title

    if meta.author_name:
        md["youtube_author"] = meta.author_name
    if meta.thumbnail_url:
        md["youtube_thumbnail"] = meta.thumbnail_url

    if transcript_path is not None:
        vault_root = _vault_root_for(Path(n.path))
        try:
            rel = transcript_path.resolve().relative_to(vault_root.resolve())
            md["source_file"] = str(rel)
        except ValueError:
            md["source_file"] = str(transcript_path)

    if meta.title and not n._post.content.strip():
        header = f"## {meta.title}\n\n"
        if meta.author_name:
            header += f"_{meta.author_name}_\n\n"
        n.prepend_body(header)

    n.save()


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    video_id = _resolve_video_id(note, arg)
    vault_root = _vault_root_for(Path(note.path))
    meta = _fetch_oembed(video_id)
    transcript_path = _download_transcript(video_id, vault_root)
    _writeback(note, video_id, meta, transcript_path)
    if transcript_path is not None:
        return {"youtube_transcript": transcript_path}
    return {}
