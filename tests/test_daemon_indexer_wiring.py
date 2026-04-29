from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmwiki.cli import _build_rag_indexer
from llmwiki.vault import Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def test_disabled_when_rag_disabled_in_config(vault: Vault) -> None:
    (vault.root / "gateway.toml").write_text(
        "rag_enabled = false\n", encoding="utf-8"
    )
    assert _build_rag_indexer(vault) is None


def test_returns_started_service_when_enabled(vault: Vault) -> None:
    (vault.root / "gateway.toml").write_text(
        "rag_enabled = true\n", encoding="utf-8"
    )
    fake_index = MagicMock()
    fake_index.stats.return_value = {"count": 5}  # skip cold-start reindex
    fake_service = MagicMock()

    with (
        patch("llmwiki.rag.index.WikiIndex", return_value=fake_index) as mock_idx,
        patch(
            "llmwiki.rag.indexer_service.IndexerService", return_value=fake_service
        ) as mock_svc,
    ):
        result = _build_rag_indexer(vault)

    assert result is fake_service
    mock_idx.assert_called_once_with(vault)
    mock_svc.assert_called_once_with(vault, fake_index)
    fake_service.start.assert_called_once()
    fake_index.reindex_all.assert_not_called()


def test_cold_start_triggers_reindex_all(vault: Vault) -> None:
    (vault.root / "gateway.toml").write_text(
        "rag_enabled = true\n", encoding="utf-8"
    )
    fake_index = MagicMock()
    fake_index.stats.return_value = {"count": 0}
    fake_index.reindex_all.return_value = 0
    fake_service = MagicMock()

    with (
        patch("llmwiki.rag.index.WikiIndex", return_value=fake_index),
        patch("llmwiki.rag.indexer_service.IndexerService", return_value=fake_service),
    ):
        result = _build_rag_indexer(vault)

    assert result is fake_service
    fake_index.reindex_all.assert_called_once()


def test_init_failure_returns_none(vault: Vault) -> None:
    (vault.root / "gateway.toml").write_text(
        "rag_enabled = true\n", encoding="utf-8"
    )
    with patch(
        "llmwiki.rag.index.WikiIndex", side_effect=RuntimeError("model download failed")
    ):
        result = _build_rag_indexer(vault)
    assert result is None
