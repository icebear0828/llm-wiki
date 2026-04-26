from __future__ import annotations

from pathlib import Path
from typing import Protocol

from llmwiki.imagen.client import ImagenClient
from llmwiki.imagen.config import ImagenConfig


class _PostLike(Protocol):
    metadata: dict[str, object]


class _NoteWithBody(Protocol):
    path: Path
    _post: _PostLike

    def prepend_body(self, text: str) -> None: ...

    def add_artifact(self, name: str, path: Path) -> None: ...


def _vault_root_for(note_path: Path) -> Path:
    for base in note_path.resolve().parents:
        if (base / "pyproject.toml").is_file():
            return base
    return note_path.resolve().parent


def _read_prompts(note: _NoteWithBody) -> list[str]:
    metadata = note._post.metadata
    raw = metadata.get("image_prompt")
    if raw is None:
        raise ValueError("note has no image_prompt frontmatter")
    if isinstance(raw, str):
        prompts = [raw]
    elif isinstance(raw, list):
        prompts = [str(p) for p in raw if isinstance(p, (str, int, float))]
    else:
        raise ValueError("note has no image_prompt frontmatter")
    if not prompts:
        raise ValueError("note has no image_prompt frontmatter")
    return prompts


def _build_client(vault_root: Path) -> ImagenClient:
    cfg = ImagenConfig.load(vault_root)
    return ImagenClient(cfg)


def run(note: _NoteWithBody) -> dict[str, Path]:
    prompts = _read_prompts(note)
    vault_root = _vault_root_for(note.path)
    out_dir = vault_root / "assets" / "images"

    client = _build_client(vault_root)

    paths: list[Path] = []
    for prompt in prompts:
        generated = client.generate(prompt, n=1, out_dir=out_dir)
        paths.extend(generated)

    embeds: list[str] = []
    for p in paths:
        try:
            rel = p.resolve().relative_to(vault_root.resolve())
        except ValueError:
            rel = p
        embeds.append(f"![[{rel}]]")
    if embeds:
        note.prepend_body("\n".join(embeds) + "\n\n")

    artifacts: dict[str, Path] = {}
    for i, p in enumerate(paths):
        key = f"image_{i}"
        note.add_artifact(key, p)
        artifacts[key] = p
    return artifacts
