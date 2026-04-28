from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from llmwiki import notecraft

from ._common import REPO_ROOT
from ._types import NoteLike


_ID_PATTERN = re.compile(
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})",
    re.IGNORECASE,
)
_VERSION_RE = re.compile(r"v\d+$")
_API_URL = "https://export.arxiv.org/api/query"
_PDF_URL = "https://arxiv.org/pdf/{id}.pdf"
_ABS_URL = "https://arxiv.org/abs/{id}"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


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
    abstract: str
    authors: list[str]
    published: str


def _parse_arxiv_id(raw: str) -> str:
    """Extract canonical arxiv id from any of: bare id, abs/pdf URL, `arxiv:` prefix."""
    match = _ID_PATTERN.search(raw)
    if not match:
        raise notecraft.NotecraftError(f"could not parse arxiv id from {raw!r}")
    return match.group("id")


def _strip_version(arxiv_id: str) -> str:
    return _VERSION_RE.sub("", arxiv_id)


def _resolve_arxiv_id(note: NoteLike, arg: str | None) -> str:
    if arg:
        return _parse_arxiv_id(arg)
    post = getattr(note, "_post", None)
    meta = getattr(post, "metadata", None) if post is not None else None
    if isinstance(meta, dict):
        candidate = meta.get("arxiv_id")
        if candidate is not None:
            try:
                return _parse_arxiv_id(str(candidate).strip())
            except notecraft.NotecraftError:
                pass
    if note.source_url:
        try:
            return _parse_arxiv_id(note.source_url)
        except notecraft.NotecraftError:
            pass
    raise notecraft.NotecraftError(
        "arxiv task requires an id (tag arg, arxiv_id frontmatter, or arxiv source URL)"
    )


def _http_get(url: str, *, timeout: float = 10.0) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
    resp.raise_for_status()
    return resp


def _http_get_bytes(url: str, *, timeout: float = 60.0) -> httpx.Response:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
    resp.raise_for_status()
    return resp


def _assets_arxiv_dir(vault_root: Path | None = None) -> Path:
    base = vault_root if vault_root is not None else REPO_ROOT
    d = base / "assets" / "arxiv"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _fetch_metadata(arxiv_id: str) -> _Meta:
    url = f"{_API_URL}?id_list={_strip_version(arxiv_id)}"
    try:
        resp = _http_get(url)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise notecraft.NotecraftError(f"arxiv api fetch failed: {exc}") from exc
    if getattr(resp, "status_code", 200) >= 400:
        raise notecraft.NotecraftError(f"arxiv api returned {resp.status_code}")
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise notecraft.NotecraftError(f"arxiv api returned non-XML: {exc}") from exc
    entry = root.find(f"{_ATOM_NS}entry")
    if entry is None:
        raise notecraft.NotecraftError(f"arxiv api returned no entry for {arxiv_id}")
    title = _normalize_whitespace((entry.findtext(f"{_ATOM_NS}title") or "").strip())
    abstract = (entry.findtext(f"{_ATOM_NS}summary") or "").strip()
    published = (entry.findtext(f"{_ATOM_NS}published") or "").strip()
    authors: list[str] = []
    for a in entry.findall(f"{_ATOM_NS}author"):
        name = a.findtext(f"{_ATOM_NS}name")
        if name:
            authors.append(name.strip())
    return _Meta(title=title, abstract=abstract, authors=authors, published=published)


def _id_to_filename(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_") + ".pdf"


def _download_pdf(arxiv_id: str, vault_root: Path | None = None) -> Path:
    out_dir = _assets_arxiv_dir(vault_root)
    out_path = out_dir / _id_to_filename(arxiv_id)
    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    url = _PDF_URL.format(id=arxiv_id)
    try:
        resp = _http_get_bytes(url)
    except (httpx.HTTPError, RuntimeError) as exc:
        raise notecraft.NotecraftError(f"arxiv pdf download failed: {exc}") from exc
    if getattr(resp, "status_code", 200) >= 400:
        raise notecraft.NotecraftError(f"arxiv pdf download returned {resp.status_code}")
    out_path.write_bytes(resp.content)
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
    note: NoteLike, arxiv_id: str, pdf_path: Path, meta: _Meta
) -> None:
    n: _NoteWithPost = note  # type: ignore[assignment]
    md = n._post.metadata
    md["arxiv_id"] = arxiv_id
    md["source"] = _ABS_URL.format(id=arxiv_id)
    md["title"] = meta.title or md.get("title") or arxiv_id
    if meta.authors:
        md["arxiv_authors"] = list(meta.authors)
    if meta.published:
        md["arxiv_published"] = meta.published

    vault_root = _vault_root_for(Path(n.path))
    try:
        rel = pdf_path.resolve().relative_to(vault_root.resolve())
        md["source_file"] = str(rel)
    except ValueError:
        md["source_file"] = str(pdf_path)

    if meta.abstract and meta.abstract not in n._post.content:
        n.prepend_body(f"## Abstract\n\n{meta.abstract}\n\n")

    n.save()


def run(note: NoteLike, *, arg: str | None = None) -> dict[str, Path]:
    arxiv_id = _resolve_arxiv_id(note, arg)
    vault_root = _vault_root_for(Path(note.path))
    pdf_path = _download_pdf(arxiv_id, vault_root)
    meta = _fetch_metadata(arxiv_id)
    _writeback(note, arxiv_id, pdf_path, meta)
    return {"arxiv_pdf": pdf_path}
