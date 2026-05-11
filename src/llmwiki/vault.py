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
