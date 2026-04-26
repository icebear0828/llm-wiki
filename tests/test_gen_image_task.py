from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from llmwiki.tasks import gen_image
from llmwiki.vault import Note


def _make_vault(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets" / "images").mkdir(parents=True)
    return tmp_path


def _write_note(vault: Path, frontmatter_block: str, body: str = "") -> Note:
    note_path = vault / "raw" / "n.md"
    note_path.write_text(f"---\n{frontmatter_block}---\n{body}", encoding="utf-8")
    return Note(note_path)


class _FakeClient:
    def __init__(self, paths_per_call: list[list[Path]]) -> None:
        self._paths = list(paths_per_call)
        self.calls: list[dict[str, Any]] = []

    def generate(self, prompt: str, *, n: int, out_dir: Path) -> list[Path]:
        self.calls.append({"prompt": prompt, "n": n, "out_dir": out_dir})
        out_dir.mkdir(parents=True, exist_ok=True)
        result = self._paths.pop(0)
        for p in result:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"png")
        return result


def _patch_build(monkeypatch: pytest.MonkeyPatch, fake: _FakeClient) -> None:
    monkeypatch.setattr(gen_image, "_build_client", lambda _vault_root: fake)


def test_single_prompt_string(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    note = _write_note(vault, 'image_prompt: "a cat"\n', body="original body\n")

    img = vault / "assets" / "images" / "20260101T000000-0.png"
    fake = _FakeClient(paths_per_call=[[img]])
    _patch_build(monkeypatch, fake)

    result = gen_image.run(note)

    assert "image_0" in result
    assert result["image_0"] == img
    assert fake.calls[0]["prompt"] == "a cat"
    assert fake.calls[0]["n"] == 1
    assert fake.calls[0]["out_dir"] == vault / "assets" / "images"
    assert note._post.content.startswith("![[assets/images/20260101T000000-0.png]]")
    assert "original body" in note._post.content
    artifacts = note._post.metadata["artifacts"]
    assert isinstance(artifacts, dict)
    assert artifacts["image_0"] == "assets/images/20260101T000000-0.png"


def test_multiple_prompts_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = _make_vault(tmp_path)
    note = _write_note(vault, 'image_prompt:\n  - "cat"\n  - "dog"\n')

    img0 = vault / "assets" / "images" / "a.png"
    img1 = vault / "assets" / "images" / "b.png"
    fake = _FakeClient(paths_per_call=[[img0], [img1]])
    _patch_build(monkeypatch, fake)

    result = gen_image.run(note)

    assert set(result.keys()) == {"image_0", "image_1"}
    assert result["image_0"] == img0
    assert result["image_1"] == img1
    assert [c["prompt"] for c in fake.calls] == ["cat", "dog"]
    body = note._post.content
    assert "![[assets/images/a.png]]" in body
    assert "![[assets/images/b.png]]" in body


def test_missing_image_prompt_raises(tmp_path: Path) -> None:
    vault = _make_vault(tmp_path)
    note = _write_note(vault, 'title: "no prompt here"\n')
    with pytest.raises(ValueError, match="image_prompt"):
        gen_image.run(note)
