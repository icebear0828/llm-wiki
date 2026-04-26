from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import frontmatter


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
    def artifacts(self) -> dict[str, Path]:
        raw = self._post.metadata.get("artifacts") or {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): Path(str(v)) for k, v in raw.items()}

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

    def add_artifact(self, name: str, path: Path) -> None:
        root = self._vault_root()
        try:
            rel = path.resolve().relative_to(root.resolve())
        except ValueError:
            rel = path
        existing = self.artifacts
        existing[name] = Path(str(rel))
        self._post.metadata["artifacts"] = {k: str(v) for k, v in existing.items()}

    def prepend_body(self, text: str) -> None:
        self._post.content = text + self._post.content

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
