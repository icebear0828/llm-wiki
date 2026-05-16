from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_NOTEBOOK_INDEX_SCHEMA_VERSION = 2
_NOTEBOOK_INDEX_SCHEMA_KEY = "_schema_version"
_NOTEBOOK_SCOPE_NOTE = "note"
_NOTEBOOK_SCOPE_TOPIC = "topic"


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass
class Vault:
    root: Path

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    @property
    def assets(self) -> Path:
        return self.root / "assets"

    @classmethod
    def discover(cls, start: Path | None = None) -> "Vault":
        cur = (start or Path.cwd()).resolve()
        for candidate in [cur, *cur.parents]:
            if (
                (candidate / "pyproject.toml").is_file()
                and (candidate / "raw").is_dir()
                and (candidate / "wiki").is_dir()
            ):
                return cls(root=candidate)
        raise FileNotFoundError(
            f"No vault found from {cur}: need pyproject.toml + raw/ + wiki/"
        )


@dataclass(frozen=True)
class NotebookWorkspace:
    key: str
    notebook_id: str
    scope: str
    status: str
    local_paths: tuple[str, ...] = ()
    source_refs: tuple[str, ...] = ()
    title: str | None = None
    indexed_notebook_id: str | None = None
    frontmatter_notebook_ids: tuple[str, ...] = ()
    last_verified_at: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "notebook_id": self.notebook_id,
            "scope": self.scope,
            "status": self.status,
            "local_paths": list(self.local_paths),
            "source_refs": list(self.source_refs),
            "title": self.title,
            "indexed_notebook_id": self.indexed_notebook_id,
            "frontmatter_notebook_ids": list(self.frontmatter_notebook_ids),
            "last_verified_at": self.last_verified_at,
        }


@dataclass
class _NotebookWorkspaceBuilder:
    key: str
    indexed_notebook_id: str | None = None
    scope: str = _NOTEBOOK_SCOPE_NOTE
    local_paths: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)
    frontmatter_notebook_ids: list[str] = field(default_factory=list)
    last_verified_at: str | None = None

    def add_unique(self, values: list[str], value: str | None) -> None:
        if value and value not in values:
            values.append(value)


@dataclass
class NotebookIndex:
    """Persisted `<vault>/.llmwiki/notebooks.json` mapping (key → notebook_id).

    Lets all generation tasks share / reuse a stable NotebookLM workspace per
    note instead of recreating one on every run.
    """

    vault: Vault
    _data: dict[str, str] = field(default_factory=dict)
    _loaded: bool = False
    _schema_version: int = _NOTEBOOK_INDEX_SCHEMA_VERSION

    @property
    def path(self) -> Path:
        return self.vault.root / ".llmwiki" / "notebooks.json"

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        version_raw = raw.get(_NOTEBOOK_INDEX_SCHEMA_KEY)
        self._schema_version = version_raw if isinstance(version_raw, int) else 1
        self._data = {
            str(k): str(v)
            for k, v in raw.items()
            if k != _NOTEBOOK_INDEX_SCHEMA_KEY and isinstance(v, str)
        }
        if self._schema_version < _NOTEBOOK_INDEX_SCHEMA_VERSION:
            self._migrate_legacy_stem_keys()

    def _migrate_legacy_stem_keys(self) -> None:
        legacy_keys = [key for key in self._data if "/" not in key]
        new_data = {key: value for key, value in self._data.items() if "/" in key}
        for stem in legacy_keys:
            matches: list[Path] = []
            for root in (self.vault.raw, self.vault.wiki):
                if not root.is_dir():
                    continue
                for md in root.rglob("*.md"):
                    if md.stem == stem:
                        matches.append(md)
            if not matches:
                logger.warning(
                    "NotebookIndex migration dropping orphan legacy key %r", stem
                )
                continue
            chosen = matches[0]
            if len(matches) > 1:
                logger.warning(
                    "NotebookIndex migration key %r has %d matches; using %s",
                    stem,
                    len(matches),
                    chosen,
                )
            try:
                rel = chosen.resolve().relative_to(self.vault.root.resolve()).as_posix()
            except ValueError:
                logger.warning(
                    "NotebookIndex migration cannot relativize %s; dropping %r",
                    chosen,
                    stem,
                )
                continue
            new_data[rel] = self._data[stem]
        self._data = new_data
        self._schema_version = _NOTEBOOK_INDEX_SCHEMA_VERSION
        try:
            self.save()
        except OSError as exc:
            logger.warning("NotebookIndex migration save failed: %s", exc)

    def get(self, key: str) -> str | None:
        self._ensure_loaded()
        return self._data.get(key)

    def set(self, key: str, notebook_id: str) -> None:
        self._ensure_loaded()
        self._data[key] = notebook_id

    def rekey(self, old_key: str, new_key: str) -> None:
        self._ensure_loaded()
        value = self._data.pop(old_key, None)
        if value is None:
            return
        self._data[new_key] = value

    def items(self) -> list[tuple[str, str]]:
        self._ensure_loaded()
        return list(self._data.items())

    def remove(self, key: str) -> None:
        self._ensure_loaded()
        self._data.pop(key, None)

    def save(self) -> None:
        self._ensure_loaded()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload_dict: dict[str, int | str] = {
            _NOTEBOOK_INDEX_SCHEMA_KEY: _NOTEBOOK_INDEX_SCHEMA_VERSION
        }
        payload_dict.update(self._data)
        payload = json.dumps(payload_dict, ensure_ascii=False, indent=2, sort_keys=True)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        _fsync_dir(self.path.parent)


def _relpath(path: Path, vault: Vault) -> str | None:
    try:
        return Path(path).resolve().relative_to(vault.root.resolve()).as_posix()
    except ValueError:
        return None


def _metadata(note: object) -> dict[object, object]:
    post = getattr(note, "_post", None)
    meta = getattr(post, "metadata", None)
    if isinstance(meta, dict):
        return meta
    return {}


def _metadata_str(note: object, key: str) -> str | None:
    value = _metadata(note).get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _normalize_workspace_key(value: str) -> str | None:
    key = value.replace("\\", "/").strip().strip("/")
    while "//" in key:
        key = key.replace("//", "/")
    if not key or key == "." or key.startswith("../") or "/../" in key:
        return None
    return key


def notebook_workspace_key(note: object, vault: Vault) -> str | None:
    explicit = _metadata_str(note, "notebook_key")
    if explicit:
        normalized = _normalize_workspace_key(explicit)
        if normalized:
            return normalized
    path = getattr(note, "path", None)
    if path is None:
        return None
    return _relpath(Path(path), vault)


def _notebook_workspace_scope(note: object, key: str, relpath: str | None) -> str:
    explicit = _metadata_str(note, "notebook_scope")
    if explicit == _NOTEBOOK_SCOPE_TOPIC:
        return _NOTEBOOK_SCOPE_TOPIC
    if explicit == _NOTEBOOK_SCOPE_NOTE:
        return _NOTEBOOK_SCOPE_NOTE
    if relpath is not None and key != relpath:
        return _NOTEBOOK_SCOPE_TOPIC
    return _NOTEBOOK_SCOPE_NOTE


def _notebook_last_verified_at(note: object) -> str | None:
    for key in ("notebook_verified_at", "notebook_last_verified_at"):
        value = _metadata(note).get(key)
        if value is None:
            continue
        if hasattr(value, "isoformat"):
            text = str(value.isoformat())
            return text.removesuffix("+00:00") + "Z" if text.endswith("+00:00") else text
        text = str(value).strip()
        if text:
            return text
    return None


def _note_source_refs(note: "Note", vault: Vault) -> list[str]:
    refs: list[str] = []
    if note.source_url:
        refs.append(note.source_url)
    source_file = _metadata_str(note, "source_file")
    if source_file:
        refs.append(source_file)
    elif note.source_file is not None:
        rel = _relpath(note.source_file, vault)
        refs.append(rel if rel else str(note.source_file))
    return refs


def _iter_workspace_notes(vault: Vault) -> list[tuple[str, "Note"]]:
    notes: list[tuple[str, Note]] = []
    for root in (vault.raw, vault.wiki):
        if not root.is_dir():
            continue
        for md in sorted(root.rglob("*.md")):
            rel = _relpath(md, vault)
            if rel is None:
                continue
            try:
                notes.append((rel, Note(md)))
            except Exception as exc:
                logger.warning("cannot read note for workspace inventory %s: %s", md, exc)
    return notes


def _workspace_status(builder: _NotebookWorkspaceBuilder) -> str:
    frontmatter_ids = set(builder.frontmatter_notebook_ids)
    indexed_id = builder.indexed_notebook_id
    if indexed_id and not builder.local_paths:
        return "missing-note"
    if indexed_id and frontmatter_ids and any(nb_id != indexed_id for nb_id in frontmatter_ids):
        return "conflict"
    if indexed_id and not frontmatter_ids:
        return "index-only"
    if not indexed_id and frontmatter_ids:
        return "frontmatter-only"
    return "ok"


def _active_notebook_id(builder: _NotebookWorkspaceBuilder, status: str) -> str:
    if status == "conflict" and builder.frontmatter_notebook_ids:
        return builder.frontmatter_notebook_ids[0]
    if builder.indexed_notebook_id:
        return builder.indexed_notebook_id
    if builder.frontmatter_notebook_ids:
        return builder.frontmatter_notebook_ids[0]
    return ""


def collect_notebook_workspaces(vault: Vault) -> list[NotebookWorkspace]:
    index = NotebookIndex(vault)
    builders: dict[str, _NotebookWorkspaceBuilder] = {}
    for key, notebook_id in index.items():
        builders[key] = _NotebookWorkspaceBuilder(
            key=key,
            indexed_notebook_id=notebook_id,
            scope=_NOTEBOOK_SCOPE_TOPIC if key.startswith("topics/") else _NOTEBOOK_SCOPE_NOTE,
        )

    for relpath, note in _iter_workspace_notes(vault):
        key = notebook_workspace_key(note, vault)
        if key is None:
            continue
        note_notebook_id = note.notebook_id
        if key not in builders and not note_notebook_id:
            continue
        builder = builders.setdefault(key, _NotebookWorkspaceBuilder(key=key))
        builder.scope = _notebook_workspace_scope(note, key, relpath)
        builder.add_unique(builder.local_paths, relpath)
        builder.add_unique(builder.titles, note.title)
        builder.add_unique(builder.frontmatter_notebook_ids, note_notebook_id)
        for source_ref in _note_source_refs(note, vault):
            builder.add_unique(builder.source_refs, source_ref)
        verified_at = _notebook_last_verified_at(note)
        if verified_at and (
            builder.last_verified_at is None or verified_at > builder.last_verified_at
        ):
            builder.last_verified_at = verified_at

    workspaces: list[NotebookWorkspace] = []
    for builder in builders.values():
        status = _workspace_status(builder)
        notebook_id = _active_notebook_id(builder, status)
        if not notebook_id:
            continue
        workspaces.append(
            NotebookWorkspace(
                key=builder.key,
                notebook_id=notebook_id,
                scope=builder.scope,
                status=status,
                local_paths=tuple(builder.local_paths),
                source_refs=tuple(builder.source_refs),
                title=builder.titles[0] if builder.titles else None,
                indexed_notebook_id=builder.indexed_notebook_id,
                frontmatter_notebook_ids=tuple(builder.frontmatter_notebook_ids),
                last_verified_at=builder.last_verified_at,
            )
        )
    return sorted(workspaces, key=lambda workspace: workspace.key)


class Note:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._post = frontmatter.load(str(path))

    @property
    def title(self) -> str:
        value = self._post.metadata.get("title")
        if isinstance(value, str):
            return value
        return self.path.stem

    @property
    def tags(self) -> list[str]:
        raw = self._post.metadata.get("tags") or []
        if isinstance(raw, str):
            return [raw]
        if isinstance(raw, list):
            return [str(t) for t in raw]
        return []

    @property
    def task_tags(self) -> list[tuple[str, str | None]]:
        result: list[tuple[str, str | None]] = []
        for t in self.tags:
            if not t.startswith("task/"):
                continue
            body = t.removeprefix("task/")
            if ":" in body:
                name, arg = body.split(":", 1)
                result.append((name, arg))
            else:
                result.append((body, None))
        return result

    @property
    def status(self) -> str:
        value = self._post.metadata.get("status", "pending")
        return str(value)

    @property
    def source_url(self) -> str | None:
        value = self._post.metadata.get("source") or self._post.metadata.get("source_url")
        return str(value) if value is not None else None

    @property
    def source_file(self) -> Path | None:
        value = self._post.metadata.get("source_file")
        if value is None:
            return None
        p = Path(str(value))
        if p.is_absolute():
            return p
        for base in self.path.parents:
            if (base / "pyproject.toml").is_file():
                return base / p
        return self.path.parent / p

    @property
    def notebook_id(self) -> str | None:
        value = self._post.metadata.get("notebook_id")
        return str(value) if isinstance(value, str) and value else None

    def set_notebook_id(self, notebook_id: str) -> None:
        self._post.metadata["notebook_id"] = notebook_id

    @property
    def artifacts(self) -> dict[str, str | Path]:
        raw = self._post.metadata.get("artifacts") or {}
        if not isinstance(raw, dict):
            return {}
        result: dict[str, str | Path] = {}
        for k, v in raw.items():
            s = str(v)
            if s.startswith("http://") or s.startswith("https://"):
                result[str(k)] = s
            else:
                result[str(k)] = Path(s)
        return result

    @property
    def body(self) -> str:
        return self._post.content

    def remove_task(self, name: str) -> None:
        target = f"task/{name}"
        prefix = f"{target}:"
        tags = [t for t in self.tags if t != target and not t.startswith(prefix)]
        self._post.metadata["tags"] = tags

    def set_status(self, status: str, *, error: str | None = None) -> None:
        self._post.metadata["status"] = status
        if error is not None:
            self._post.metadata["error"] = error
        elif "error" in self._post.metadata and status != "error":
            del self._post.metadata["error"]

    def _vault_root(self) -> Path:
        for base in self.path.parents:
            if (base / "pyproject.toml").is_file():
                return base
        return self.path.parent

    def add_artifact(self, name: str, value: str | Path) -> None:
        if isinstance(value, str) and (value.startswith("http://") or value.startswith("https://")):
            rel_str = value
        else:
            path = Path(value) if isinstance(value, str) else value
            root = self._vault_root()
            try:
                rel = path.resolve().relative_to(root.resolve())
            except ValueError:
                rel = path
            rel_str = str(rel)
            
        existing = self.artifacts
        existing[name] = rel_str  # type: ignore
        self._post.metadata["artifacts"] = {k: str(v) for k, v in existing.items()}

    def prepend_body(self, text: str) -> None:
        self._post.content = text + self._post.content

    def append_body(self, text: str) -> None:
        self._post.content = self._post.content + text

    def save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = frontmatter.dumps(self._post)
        if not data.endswith("\n"):
            data += "\n"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        _fsync_dir(self.path.parent)
