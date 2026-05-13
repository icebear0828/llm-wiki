from __future__ import annotations

import os
import logging
from pathlib import Path

import frontmatter

from llmwiki.r2 import R2Config, upload_asset
from llmwiki.vault import Note, NotebookIndex, Vault, _fsync_dir

logger = logging.getLogger(__name__)


class IngestConflict(Exception):
    """Raised when moving a raw note would overwrite an existing wiki note."""

    def __init__(self, dest: Path) -> None:
        super().__init__(f"refusing to overwrite existing wiki note: {dest}")
        self.dest = dest


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def move_to_wiki(note: Note, vault: Vault, artifacts: dict[str, Path]) -> Note:
    r2_cfg = R2Config.load(vault.root)
    embeds: list[str] = []

    new_path = vault.wiki / note.path.name
    if new_path.exists() and not _same_file(note.path, new_path):
        raise IngestConflict(new_path)

    for name, path in artifacts.items():
        url = None
        if r2_cfg.enabled:
            try:
                key_for_log = path.resolve().relative_to(vault.root.resolve()).as_posix()
            except ValueError:
                key_for_log = path.name
            try:
                url = upload_asset(r2_cfg, path, vault.root)
            except Exception as exc:
                logger.error(
                    "R2 upload failed for %s (key=%s type=%s)",
                    path.name,
                    key_for_log,
                    type(exc).__name__,
                    exc_info=False,
                )

        if url:
            note.add_artifact(name, url)
            embeds.append(f"![{name}]({url})")
            if path.is_file():
                try:
                    path.unlink()
                except OSError:
                    pass
        else:
            note.add_artifact(name, path)
            try:
                rel = path.resolve().relative_to(vault.root.resolve())
            except ValueError:
                rel = path
            embeds.append(f"![[{rel}]]")

    note.set_status("done")

    body = note.body
    body_lines = body.splitlines()
    existing_top = set()
    for line in body_lines:
        if line.strip() == "":
            continue
        if (line.startswith("![[") and line.endswith("]]")) or (
            line.startswith("![") and line.endswith(")")
        ):
            existing_top.add(line.strip())
            continue
        break
    new_embeds = [e for e in embeds if e not in existing_top]

    if new_embeds:
        prefix = "\n".join(new_embeds) + "\n\n"
        note.prepend_body(prefix)

    new_post = frontmatter.Post(note.body, **note._post.metadata)
    data = frontmatter.dumps(new_post)
    if not data.endswith("\n"):
        data += "\n"

    new_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = new_path.with_suffix(new_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, new_path)
    _fsync_dir(new_path.parent)

    if not _same_file(note.path, new_path):
        old_path = note.path
        try:
            old_path.unlink()
        finally:
            try:
                _fsync_dir(old_path.parent)
            except OSError:
                pass
        try:
            old_rel = old_path.resolve().relative_to(vault.root.resolve()).as_posix()
            new_rel = new_path.resolve().relative_to(vault.root.resolve()).as_posix()
        except ValueError:
            old_rel = None
            new_rel = None
        if old_rel is not None and new_rel is not None and old_rel != new_rel:
            idx = NotebookIndex(vault)
            idx.rekey(old_rel, new_rel)
            idx.save()

    return Note(new_path)
