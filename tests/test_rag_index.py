from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.rag.index import Hit, WikiIndex, _rrf_fuse
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


def test_reindex_all_drops_orphan_dense_entries(vault: Vault) -> None:
    # If a note is deleted while the daemon is offline, the next reindex
    # should drop it from chroma — sparse already does this; dense used to
    # leave a ghost.
    _write(vault, "alpha.md", "Alpha", "alpha body about cats")
    _write(vault, "beta.md", "Beta", "beta body about dogs")

    index = WikiIndex(vault)
    assert index.reindex_all() == 2
    assert index.stats()["count"] == 2

    # User deletes a note while index is "offline".
    (vault.wiki / "beta.md").unlink()

    n = index.reindex_all()
    assert n == 1
    assert index.stats()["count"] == 1
    remaining = index.query("anything", k=5)
    assert all(not h.rel_path.endswith("beta.md") for h in remaining)


def test_dense_upsert_mtime_short_circuit(vault: Vault) -> None:
    # Re-upserting an unchanged note should not re-run fastembed encode.
    p = _write(vault, "alpha.md", "Alpha", "alpha body")
    index = WikiIndex(vault)
    index.upsert(Note(p))

    encode_calls: list[int] = []
    real_embed = index._dense._embed_passages  # type: ignore[attr-defined]

    def counting(texts: list[str]) -> list[list[float]]:
        encode_calls.append(len(texts))
        return real_embed(texts)

    index._dense._embed_passages = counting  # type: ignore[attr-defined,method-assign]

    # Same file, same mtime — should short-circuit.
    index.upsert(Note(p))
    assert encode_calls == [], f"unexpected encode call: {encode_calls}"

    # Touch mtime — should encode again.
    import os
    import time
    new_mtime = time.time() + 5.0
    os.utime(p, (new_mtime, new_mtime))
    index.upsert(Note(p))
    assert encode_calls == [1]


def test_rrf_fuse_normalizes_top_score_to_one() -> None:
    dense = [
        Hit(path=Path("a"), rel_path="a", title="A", snippet="", score=0.9),
        Hit(path=Path("b"), rel_path="b", title="B", snippet="", score=0.8),
    ]
    sparse = [
        Hit(path=Path("a"), rel_path="a", title="A", snippet="", score=5.0),
        Hit(path=Path("c"), rel_path="c", title="C", snippet="", score=3.0),
    ]
    fused = _rrf_fuse(dense, sparse, k=3)
    assert fused, "expected at least one fused hit"
    assert fused[0].score == pytest.approx(1.0)
    for h in fused[1:]:
        assert 0.0 < h.score < 1.0
    # Ordering preserved (a wins because it appears in both rankers).
    assert fused[0].rel_path == "a"


def test_init_does_not_eagerly_load_sparse(vault: Vault) -> None:
    # Eager bootstrap on every WikiIndex(...) made one-shot CLI commands
    # (`wikictl rag stats`, etc.) tokenize the whole vault for nothing.
    # Sparse must lazy-load on first query instead.
    _write(vault, "alpha.md", "Alpha", "alpha body")

    index = WikiIndex(vault)
    # Sparse should be empty until something asks for it.
    assert len(index._sparse._docs) == 0  # type: ignore[attr-defined]

    # Reaching into query should bootstrap from disk on demand.
    hits = index.query("alpha", k=1)
    assert hits
    assert len(index._sparse._docs) >= 1  # type: ignore[attr-defined]


def test_hybrid_chinese_keyword_recall(vault: Vault) -> None:
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
        "Pasta is an Italian dish made from wheat flour, eggs, and water.",
    )
    _write(
        vault,
        "qcd.md",
        "量子色动力学",
        "量子色动力学是描述夸克与胶子之间强相互作用的非阿贝尔规范场论。",
    )

    index = WikiIndex(vault)
    n = index.reindex_all()
    assert n == 3

    hits = index.query("量子色动力学", k=3)
    assert hits, "expected hybrid retrieval to return CN keyword hits"
    assert hits[0].rel_path.endswith("qcd.md")

    stats = index.stats()
    assert stats["sparse_count"] == 3
