from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from llmwiki.git_autopilot import GitAutopilot
from llmwiki.vault import Vault


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return Vault(root=tmp_path)


def test_commit_one_shot_default_message(vault: Vault) -> None:
    a = GitAutopilot(vault, debounce_seconds=0.1)
    (vault.wiki / "x.md").write_text("hello", encoding="utf-8")
    a._commit()
    log = _git(vault.root, "log", "-1", "--pretty=%s").stdout.strip()
    assert log == "[Auto] vault sync"


def test_commit_uses_marker_message(vault: Vault) -> None:
    a = GitAutopilot(vault, debounce_seconds=0.1)
    (vault.wiki / "x.md").write_text("hello", encoding="utf-8")
    (vault.root / ".git-commit-msg").write_text("[Auto] custom", encoding="utf-8")
    a._commit()
    log = _git(vault.root, "log", "-1", "--pretty=%s").stdout.strip()
    assert log == "[Auto] custom"
    assert not (vault.root / ".git-commit-msg").exists()


def test_commit_skipped_when_no_changes(vault: Vault) -> None:
    a = GitAutopilot(vault, debounce_seconds=0.1)
    head_before = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    a._commit()
    head_after = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    assert head_before == head_after


def test_debounced_commit_via_observer(vault: Vault) -> None:
    a = GitAutopilot(vault, debounce_seconds=0.1)
    import threading

    t = threading.Thread(target=a.start, daemon=True)
    t.start()
    time.sleep(0.3)
    head_before = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    (vault.wiki / "n.md").write_text("hi", encoding="utf-8")
    deadline = time.time() + 5.0
    head_after = head_before
    while time.time() < deadline:
        head_after = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
        if head_after != head_before:
            break
        time.sleep(0.1)
    a.stop()
    t.join(timeout=2)
    assert head_after != head_before
