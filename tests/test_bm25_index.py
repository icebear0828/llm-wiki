from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.rag.bm25_index import BM25Index, _tokenize
from llmwiki.rag.index import Hit
from llmwiki.vault import Note, Vault


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


def test_tokenize_chinese_search_mode_yields_overlap() -> None:
    # cut_for_search splits long compound words AND emits substrings.
    tokens = _tokenize("量子色动力学")
    assert "量子" in tokens
    assert "动力学" in tokens
    assert "动力" in tokens
    assert "力学" in tokens


def test_tokenize_mixed_lowercases_ascii_keeps_cjk() -> None:
    tokens = _tokenize("Python 神经网络 Tutorial")
    assert "python" in tokens
    assert "tutorial" in tokens
    assert "神经网络" in tokens
    assert "Python" not in tokens


def test_tokenize_filters_whitespace_and_punct() -> None:
    tokens = _tokenize("hello, world! 你好，世界。")
    assert "," not in tokens
    assert "!" not in tokens
    assert "，" not in tokens
    assert "。" not in tokens
    assert " " not in tokens
    assert "" not in tokens
    assert "hello" in tokens
    assert "world" in tokens


def test_upsert_query_returns_hit_with_fields(vault: Vault) -> None:
    p = _write(vault, "qcd.md", "量子色动力学", "量子色动力学描述强相互作用。")
    index = BM25Index(vault)
    index.upsert(Note(p))
    hits = index.query("量子色动力学", k=3)
    assert len(hits) == 1
    h = hits[0]
    assert isinstance(h, Hit)
    assert h.rel_path.endswith("qcd.md")
    assert h.title == "量子色动力学"
    assert "量子色动力学" in h.snippet
    assert h.score > 0
    assert h.path == p


def test_chinese_keyword_picks_correct_doc(vault: Vault) -> None:
    _write(vault, "rockets.md", "Rockets", "Rockets use combustion thrust to reach orbit.")
    _write(vault, "pasta.md", "Pasta", "Italian dish from wheat flour and eggs.")
    qcd_path = _write(vault, "qcd.md", "量子色动力学", "量子色动力学是描述夸克与胶子相互作用的理论。")

    index = BM25Index(vault)
    n = index.reindex_all()
    assert n == 3

    hits = index.query("量子色动力学", k=3)
    assert hits, "expected at least one hit for CN keyword"
    assert hits[0].rel_path.endswith("qcd.md")
    assert hits[0].path == qcd_path


def test_upsert_remove_lifecycle(vault: Vault) -> None:
    p = _write(vault, "alpha.md", "Alpha", "machine learning paper")
    index = BM25Index(vault)
    index.upsert(Note(p))
    assert index.query("machine learning", k=1)[0].rel_path.endswith("alpha.md")

    index.remove(p)
    assert index.query("machine learning", k=5) == []


def test_upsert_overwrites_same_doc(vault: Vault) -> None:
    p = _write(vault, "doc.md", "Doc", "原始内容关于宇宙学")
    index = BM25Index(vault)
    index.upsert(Note(p))
    assert index.query("宇宙学", k=1)

    p.write_text("---\ntitle: Doc\n---\n更新后内容关于神经网络\n", encoding="utf-8")
    index.upsert(Note(p))
    assert index.query("神经网络", k=1)
    assert index.query("宇宙学", k=5) == []


def test_query_empty_index_returns_empty(vault: Vault) -> None:
    index = BM25Index(vault)
    assert index.query("anything", k=5) == []


def test_reindex_all_skips_non_md(vault: Vault) -> None:
    _write(vault, "a.md", "A", "alpha content")
    (vault.wiki / "ignore.txt").write_text("not markdown", encoding="utf-8")
    index = BM25Index(vault)
    n = index.reindex_all()
    assert n == 1
