from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_NOTEBOOK_INDEX_SCHEMA_VERSION = 2
_NOTEBOOK_INDEX_SCHEMA_KEY = "_schema_version"
_NOTEBOOK_SCOPE_NOTE = "note"
_NOTEBOOK_SCOPE_TOPIC = "topic"
_SOURCE_MANIFEST_SCHEMA_VERSION = 1
_SOURCE_MANIFEST_SCHEMA_KEY = "_schema_version"
_SOURCE_MANIFEST_RECORDS_KEY = "sources"
_SOURCE_STATUS_ADDED = "added"
_VOICE_EXTS = {".flac", ".m4a", ".mp3", ".ogg", ".wav"}


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


@dataclass(frozen=True)
class SourceRecord:
    workspace_key: str
    notebook_id: str
    source_ref: str
    source_type: str
    local_path: str | None = None
    added_at: str | None = None
    status: str = _SOURCE_STATUS_ADDED
    title: str | None = None
    source_url: str | None = None
    source_file: str | None = None
    artifact_paths: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "workspace_key": self.workspace_key,
            "notebook_id": self.notebook_id,
            "source_ref": self.source_ref,
            "source_type": self.source_type,
            "local_path": self.local_path,
            "added_at": self.added_at,
            "status": self.status,
            "title": self.title,
            "source_url": self.source_url,
            "source_file": self.source_file,
            "artifact_paths": list(self.artifact_paths),
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


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _http_url(value: object) -> str | None:
    text = _optional_str(value)
    if text and text.startswith(("http://", "https://")):
        return text
    return None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _source_record_from_dict(raw: object) -> SourceRecord | None:
    if not isinstance(raw, dict):
        return None
    workspace_key = _optional_str(raw.get("workspace_key"))
    notebook_id = _optional_str(raw.get("notebook_id"))
    source_ref = _optional_str(raw.get("source_ref"))
    source_type = _optional_str(raw.get("source_type"))
    if not (workspace_key and notebook_id and source_ref and source_type):
        return None
    return SourceRecord(
        workspace_key=workspace_key,
        notebook_id=notebook_id,
        source_ref=source_ref,
        source_type=source_type,
        local_path=_optional_str(raw.get("local_path")),
        added_at=_optional_str(raw.get("added_at")),
        status=_optional_str(raw.get("status")) or _SOURCE_STATUS_ADDED,
        title=_optional_str(raw.get("title")),
        source_url=_optional_str(raw.get("source_url")),
        source_file=_optional_str(raw.get("source_file")),
        artifact_paths=_string_tuple(raw.get("artifact_paths")),
    )


@dataclass
class SourceManifest:
    """Persisted source provenance for NotebookLM workspace feeds."""

    vault: Vault
    _records: list[SourceRecord] = field(default_factory=list)
    _loaded: bool = False

    @property
    def path(self) -> Path:
        return self.vault.root / ".llmwiki" / "sources.json"

    @classmethod
    def from_vault_root(cls, root: Path) -> "SourceManifest":
        return cls(Vault(Path(root)))

    @classmethod
    def from_path(cls, path: Path) -> "SourceManifest":
        source_path = Path(path)
        return cls(Vault(source_path.parent.parent))

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
        records_raw = raw.get(_SOURCE_MANIFEST_RECORDS_KEY)
        if not isinstance(records_raw, list):
            return
        records: list[SourceRecord] = []
        for item in records_raw:
            record = _source_record_from_dict(item)
            if record is not None:
                records.append(record)
        self._records = records

    def records(self) -> list[SourceRecord]:
        self._ensure_loaded()
        return list(self._records)

    def upsert(self, record: SourceRecord) -> None:
        self._ensure_loaded()
        identity = (record.notebook_id, record.source_ref)
        self._records = [
            existing
            for existing in self._records
            if (existing.notebook_id, existing.source_ref) != identity
        ]
        self._records.append(record)

    def find_added(
        self, *, workspace_key: str, notebook_id: str, source_ref: str
    ) -> SourceRecord | None:
        self._ensure_loaded()
        for record in self._records:
            if (
                record.workspace_key == workspace_key
                and record.notebook_id == notebook_id
                and record.source_ref == source_ref
                and record.status == _SOURCE_STATUS_ADDED
            ):
                return record
        return None

    def find_added_source(
        self, *, notebook_id: str, source_ref: str
    ) -> SourceRecord | None:
        self._ensure_loaded()
        for record in self._records:
            if (
                record.notebook_id == notebook_id
                and record.source_ref == source_ref
                and record.status == _SOURCE_STATUS_ADDED
            ):
                return record
        return None

    def records_for(self, target: str) -> list[SourceRecord]:
        self._ensure_loaded()
        return [
            record
            for record in self._records
            if record.workspace_key == target or record.notebook_id == target
        ]

    def rekey_local_path(
        self,
        old_key: str,
        new_key: str,
        *,
        artifact_paths: tuple[str, ...] = (),
    ) -> bool:
        self._ensure_loaded()
        changed = False
        updated: list[SourceRecord] = []
        for record in self._records:
            matched = (
                record.workspace_key == old_key
                or record.local_path == old_key
                or record.source_ref == old_key
            )
            if not matched:
                updated.append(record)
                continue
            merged_artifacts = tuple(
                dict.fromkeys([*record.artifact_paths, *artifact_paths])
            )
            updated.append(
                replace(
                    record,
                    workspace_key=new_key if record.workspace_key == old_key else record.workspace_key,
                    local_path=new_key if record.local_path == old_key else record.local_path,
                    source_ref=new_key if record.source_ref == old_key else record.source_ref,
                    artifact_paths=merged_artifacts,
                )
            )
            changed = True
        self._records = updated
        return changed

    def save(self) -> None:
        self._ensure_loaded()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        records = sorted(
            self._records,
            key=lambda record: (
                record.workspace_key,
                record.notebook_id,
                record.source_ref,
            ),
        )
        payload = json.dumps(
            {
                _SOURCE_MANIFEST_SCHEMA_KEY: _SOURCE_MANIFEST_SCHEMA_VERSION,
                _SOURCE_MANIFEST_RECORDS_KEY: [
                    record.as_dict() for record in records
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        _fsync_dir(self.path.parent)


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


def _source_file_ref(note: "Note", vault: Vault) -> str | None:
    source_file = _metadata_str(note, "source_file")
    if source_file:
        path = Path(source_file)
        if path.is_absolute():
            rel = _relpath(path, vault)
            return rel if rel else str(path)
        return path.as_posix()
    if note.source_file is None:
        return None
    rel = _relpath(note.source_file, vault)
    return rel if rel else str(note.source_file)


def _source_artifact_paths(note: "Note", vault: Vault) -> tuple[str, ...]:
    artifact_paths: list[str] = []
    for value in note.artifacts.values():
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            artifact_paths.append(value)
            continue
        path = Path(value)
        rel = _relpath(path, vault)
        artifact_paths.append(rel if rel else path.as_posix())
    return tuple(dict.fromkeys(artifact_paths))


def _source_type(note: "Note", source_ref: str, source_file: str | None) -> str:
    if _metadata_str(note, "arxiv_id") or "arxiv.org/" in source_ref:
        return "arxiv"
    if _metadata_str(note, "youtube_id") or "youtube.com/" in source_ref or "youtu.be/" in source_ref:
        return "youtube"
    if _metadata_str(note, "stt_model"):
        return "voice-transcript"
    if source_file:
        suffix = Path(source_file).suffix.lower()
        if suffix == ".pdf":
            return "pdf"
        if suffix in _VOICE_EXTS:
            return "voice-transcript"
        return "file"
    if note.source_url:
        return "web"
    return "local-note"


def source_record_from_note(
    note: "Note",
    vault: Vault,
    *,
    workspace_key: str,
    notebook_id: str,
    added_at: str,
    status: str = _SOURCE_STATUS_ADDED,
) -> SourceRecord:
    local_path = _relpath(note.path, vault)
    source_file = _source_file_ref(note, vault)
    source_url = note.source_url
    source_ref = source_file or source_url or local_path or str(note.path)
    return SourceRecord(
        workspace_key=workspace_key,
        notebook_id=notebook_id,
        source_ref=source_ref,
        source_type=_source_type(note, source_ref, source_file),
        local_path=local_path,
        added_at=added_at,
        status=status,
        title=note.title,
        source_url=source_url,
        source_file=source_file,
        artifact_paths=_source_artifact_paths(note, vault),
    )


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
        return _http_url(self._post.metadata.get("source_url")) or _http_url(
            self._post.metadata.get("source")
        )

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
