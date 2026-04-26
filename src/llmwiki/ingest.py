from __future__ import annotations

import os
from pathlib import Path

import frontmatter

from llmwiki.vault import Note, Vault


def _embed_lines(artifacts: dict[str, Path], vault: Vault) -> list[str]:
    lines: list[str] = []
    for p in artifacts.values():
        try:
            rel = p.resolve().relative_to(vault.root.resolve())
        except ValueError:
            rel = p
        lines.append(f"![[{rel}]]")
    return lines


def move_to_wiki(note: Note, vault: Vault, artifacts: dict[str, Path]) -> Note:
    for name, path in artifacts.items():
        note.add_artifact(name, path)
    note.set_status("done")

    new_path = vault.wiki / note.path.name
    embeds = _embed_lines(artifacts, vault)

    body = note.body
    body_lines = body.splitlines()
    existing_top = set()
    for line in body_lines:
        if line.strip() == "":
            continue
        if line.startswith("![[") and line.endswith("]]"):
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

    if note.path.resolve() != new_path.resolve():
        note.path.unlink()

    return Note(new_path)
