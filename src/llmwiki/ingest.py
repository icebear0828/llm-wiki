from __future__ import annotations

import os
from pathlib import Path

import frontmatter

from llmwiki.vault import Note, Vault
from llmwiki.r2 import R2Config, upload_asset


def move_to_wiki(note: Note, vault: Vault, artifacts: dict[str, Path]) -> Note:
    r2_cfg = R2Config.load(vault.root)
    embeds: list[str] = []
    
    for name, path in artifacts.items():
        url = None
        if r2_cfg.enabled:
            try:
                url = upload_asset(r2_cfg, path, vault.root)
            except Exception as e:
                print(f"R2 upload failed for {path}: {e}")
                
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

    new_path = vault.wiki / note.path.name

    body = note.body
    body_lines = body.splitlines()
    existing_top = set()
    for line in body_lines:
        if line.strip() == "":
            continue
        if (line.startswith("![[") and line.endswith("]]")) or (line.startswith("![") and line.endswith(")")):
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
