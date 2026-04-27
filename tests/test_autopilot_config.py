from __future__ import annotations

from pathlib import Path

import pytest

from llmwiki.autopilot_config import AutopilotConfig, write_default_template


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    return tmp_path


def test_load_defaults_when_no_file(vault_dir: Path) -> None:
    cfg = AutopilotConfig.load(vault_dir)
    assert cfg.push_enabled is False
    assert cfg.push_remote == "origin"
    assert cfg.push_branch == ""
    assert cfg.push_strategy == "fast-forward"
    assert cfg.push_debounce_seconds == 30.0


def test_load_reads_toml(vault_dir: Path) -> None:
    (vault_dir / "autopilot.toml").write_text(
        "[push]\n"
        "enabled = true\n"
        "remote = \"backup\"\n"
        "branch = \"private\"\n"
        "strategy = \"force-with-lease\"\n"
        "debounce_seconds = 5\n",
        encoding="utf-8",
    )
    cfg = AutopilotConfig.load(vault_dir)
    assert cfg.push_enabled is True
    assert cfg.push_remote == "backup"
    assert cfg.push_branch == "private"
    assert cfg.push_strategy == "force-with-lease"
    assert cfg.push_debounce_seconds == 5.0


def test_load_rejects_unknown_strategy(vault_dir: Path) -> None:
    (vault_dir / "autopilot.toml").write_text(
        "[push]\nenabled = true\nstrategy = \"force\"\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="strategy"):
        AutopilotConfig.load(vault_dir)


def test_write_default_template(vault_dir: Path) -> None:
    target, created = write_default_template(vault_dir)
    assert created is True
    assert target == vault_dir / "autopilot.toml"
    cfg = AutopilotConfig.load(vault_dir)
    assert cfg.push_enabled is False  # safe default

    # Idempotent
    target2, created2 = write_default_template(vault_dir)
    assert created2 is False
    assert target2 == target
