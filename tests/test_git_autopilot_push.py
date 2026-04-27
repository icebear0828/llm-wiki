"""Push behavior on top of git_autopilot — covers enabled/disabled, success,
and failure paths (mocked + real local push to a bare remote)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmwiki.autopilot_config import AutopilotConfig
from llmwiki.git_autopilot import GitAutopilot, PushFailed
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
def vault_with_remote(tmp_path: Path) -> tuple[Vault, Path]:
    """Init a vault repo + a sibling bare repo as `origin`."""
    work = tmp_path / "vault"
    bare = tmp_path / "remote.git"
    work.mkdir()
    _git(work, "init", "-q", "-b", "main")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "Test")
    _git(work, "config", "commit.gpgsign", "false")
    (work / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (work / "raw").mkdir()
    (work / "wiki").mkdir()
    (work / "assets").mkdir()
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "init")

    subprocess.run(
        ["git", "init", "--bare", "-q", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    _git(work, "remote", "add", "origin", str(bare))
    _git(work, "push", "-q", "origin", "main")
    return Vault(root=work), bare


def test_push_disabled_by_default_is_noop(vault_with_remote: tuple[Vault, Path]) -> None:
    vault, bare = vault_with_remote
    cfg = AutopilotConfig()  # push_enabled=False
    a = GitAutopilot(vault, debounce_seconds=0.1, autopilot_cfg=cfg)
    (vault.wiki / "x.md").write_text("hi", encoding="utf-8")
    a._commit()

    # Local HEAD advanced
    local_head = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    # Remote HEAD did NOT advance (push disabled)
    remote_head = _git(bare, "rev-parse", "main").stdout.strip()
    assert local_head != remote_head


def test_push_enabled_advances_remote(vault_with_remote: tuple[Vault, Path]) -> None:
    vault, bare = vault_with_remote
    cfg = AutopilotConfig(push_enabled=True, push_remote="origin")
    a = GitAutopilot(vault, debounce_seconds=0.1, autopilot_cfg=cfg)
    (vault.wiki / "x.md").write_text("hi", encoding="utf-8")
    a._commit()
    a._push()

    local_head = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    remote_head = _git(bare, "rev-parse", "main").stdout.strip()
    assert local_head == remote_head


def test_push_explicit_branch(vault_with_remote: tuple[Vault, Path]) -> None:
    vault, bare = vault_with_remote
    cfg = AutopilotConfig(push_enabled=True, push_remote="origin", push_branch="main")
    a = GitAutopilot(vault, debounce_seconds=0.1, autopilot_cfg=cfg)
    (vault.wiki / "y.md").write_text("y", encoding="utf-8")
    a._commit()
    a._push()
    local_head = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    remote_head = _git(bare, "rev-parse", "main").stdout.strip()
    assert local_head == remote_head


def test_push_force_with_lease_recovers_diverged_history(
    vault_with_remote: tuple[Vault, Path],
) -> None:
    """When the remote diverges (rare for a single-author vault but possible
    if another device pushed), `force-with-lease` rewrites the remote ref;
    plain fast-forward would refuse with non-FF."""
    vault, bare = vault_with_remote

    # Simulate a diverged remote: clone, commit, push, then rewrite local history
    other = vault.root.parent / "other"
    subprocess.run(
        ["git", "clone", "-q", str(bare), str(other)], check=True, capture_output=True
    )
    _git(other, "config", "user.email", "o@example.com")
    _git(other, "config", "user.name", "Other")
    _git(other, "config", "commit.gpgsign", "false")
    (other / "remote-only.md").write_text("from other device", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-q", "-m", "from other")
    _git(other, "push", "-q", "origin", "main")

    # Local doesn't know about it; create a different commit that is not FF
    (vault.root / "wiki" / "local.md").write_text("local-only", encoding="utf-8")
    _git(vault.root, "add", "-A")
    _git(vault.root, "commit", "-q", "-m", "local")

    # plain fast-forward must fail
    cfg_ff = AutopilotConfig(push_enabled=True, push_strategy="fast-forward")
    a_ff = GitAutopilot(vault, autopilot_cfg=cfg_ff)
    with pytest.raises(PushFailed):
        a_ff._push()

    # force-with-lease only succeeds if local saw the latest remote (it didn't).
    # First fetch to update remote-tracking ref, then push with lease.
    _git(vault.root, "fetch", "-q", "origin")
    cfg_lease = AutopilotConfig(push_enabled=True, push_strategy="force-with-lease")
    a_lease = GitAutopilot(vault, autopilot_cfg=cfg_lease)
    a_lease._push()  # should not raise


def test_push_failure_raises_pushfailed(
    vault_with_remote: tuple[Vault, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _ = vault_with_remote
    cfg = AutopilotConfig(push_enabled=True, push_remote="nonexistent")
    a = GitAutopilot(vault, autopilot_cfg=cfg)
    with pytest.raises(PushFailed):
        a._push()


def test_fire_pushes_when_enabled(vault_with_remote: tuple[Vault, Path]) -> None:
    vault, bare = vault_with_remote
    cfg = AutopilotConfig(
        push_enabled=True, push_remote="origin", push_debounce_seconds=0.0
    )
    a = GitAutopilot(vault, debounce_seconds=0.1, autopilot_cfg=cfg)
    (vault.wiki / "z.md").write_text("z", encoding="utf-8")
    a._fire()
    local = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    remote = _git(bare, "rev-parse", "main").stdout.strip()
    assert local == remote


def test_fire_no_push_when_disabled(vault_with_remote: tuple[Vault, Path]) -> None:
    vault, bare = vault_with_remote
    cfg = AutopilotConfig(push_enabled=False)
    a = GitAutopilot(vault, debounce_seconds=0.1, autopilot_cfg=cfg)
    (vault.wiki / "z.md").write_text("z", encoding="utf-8")
    a._fire()
    local = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    remote = _git(bare, "rev-parse", "main").stdout.strip()
    assert local != remote
