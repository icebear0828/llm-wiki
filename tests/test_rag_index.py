from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.rag.index import WikiIndex
from llmwiki.vault import Note, Vault

pytestmark = pytest.mark.slow


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _write(vault: Vault, name: str, title: str, body: str) -> Path:
    p = vault.wiki / name
    p.write_text(
        f"---\ntitle: {title}\n---\n{body}\n",
        encoding="utf-8",
    )
    return p


def test_reindex_query_upsert_remove_roundtrip(vault: Vault) -> None:
    _write(
        vault,
        "cats.md",
        "Cats",
        "Cats are small carnivorous mammals. They purr and chase mice.",
    )
    _write(
        vault,
        "rockets.md",
        "Rockets",
        "Rockets use thrust from combustion to escape Earth's gravity into orbit.",
    )
    _write(
        vault,
        "pasta.md",
        "Pasta",
        "Pasta is an Italian dish made from wheat flour, eggs, and water, often boiled.",
    )

    index = WikiIndex(vault)
    n = index.reindex_all()
    assert n == 3

    stats = index.stats()
    assert stats["count"] == 3
    assert "multilingual" in str(stats["model"])

    hits = index.query("feline pet purring", k=3)
    assert len(hits) >= 1
    assert hits[0].rel_path.endswith("cats.md")

    rockets_hits = index.query("spacecraft propulsion launch", k=3)
    assert rockets_hits[0].rel_path.endswith("rockets.md")

    cats_path = vault.wiki / "cats.md"
    cats_path.write_text(
        "---\ntitle: Cats\n---\nQuantum chromodynamics describes strong nuclear force.\n",
        encoding="utf-8",
    )
    index.upsert(Note(cats_path))

    qcd_hits = index.query("quark gluon strong force physics", k=3)
    assert qcd_hits[0].rel_path.endswith("cats.md")

    index.remove(cats_path)
    after = index.stats()
    assert after["count"] == 2
    remaining = index.query("anything", k=5)
    assert all(not h.rel_path.endswith("cats.md") for h in remaining)
