"""Credential-leak guards on the git autopilot commit/push path."""

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
def vault(tmp_path: Path) -> Vault:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "assets").mkdir()
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return Vault(root=tmp_path)


@pytest.fixture
def vault_with_remote(tmp_path: Path) -> tuple[Vault, Path]:
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


def _committed_paths(root: Path) -> set[str]:
    out = _git(root, "show", "--name-only", "--pretty=format:", "HEAD").stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def test_commit_does_not_stage_r2_toml(vault: Vault) -> None:
    (vault.root / "r2.toml").write_text(
        '[r2]\naccess_key="AKIAEXAMPLE"\nsecret_key="topsecret"\n',
        encoding="utf-8",
    )
    (vault.raw / "foo.md").write_text("hello", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "raw/foo.md" in paths
    assert "r2.toml" not in paths


def test_commit_blocks_all_credential_tomls(vault: Vault) -> None:
    credential_files = (
        "r2.toml",
        "autopilot.toml",
        "im.toml",
        "imagen.toml",
        "gateway.toml",
    )
    for name in credential_files:
        (vault.root / name).write_text(f"# secrets for {name}\n", encoding="utf-8")
    (vault.root / "wiki").mkdir()
    (vault.wiki / "ok.md").write_text("ok", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "wiki/ok.md" in paths
    for name in credential_files:
        assert name not in paths


def test_commit_blocks_env_and_keylike_names(vault: Vault) -> None:
    (vault.root / ".env").write_text("OPENAI_API_KEY=sk-xxx", encoding="utf-8")
    (vault.root / "prod.env").write_text("X=Y", encoding="utf-8")
    (vault.root / "my_token.txt").write_text("hf_xxx", encoding="utf-8")
    (vault.root / "service_account_key.json").write_text("{}", encoding="utf-8")
    (vault.root / "credentials.yaml").write_text("a: b", encoding="utf-8")
    (vault.raw / "ok.md").write_text("ok", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "raw/ok.md" in paths
    for name in (
        ".env",
        "prod.env",
        "my_token.txt",
        "service_account_key.json",
        "credentials.yaml",
    ):
        assert name not in paths


def test_commit_blocks_credential_shaped_configs_via_substring(vault: Vault) -> None:
    (vault.root / "api_key.toml").write_text("k = 1", encoding="utf-8")
    (vault.root / "tokens.yaml").write_text("a: b", encoding="utf-8")
    (vault.root / "password.env").write_text("X=Y", encoding="utf-8")
    (vault.raw / "ok.md").write_text("ok", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "raw/ok.md" in paths
    for name in ("api_key.toml", "tokens.yaml", "password.env"):
        assert name not in paths


def test_commit_blocks_extensionless_credential_basenames(vault: Vault) -> None:
    (vault.root / "secret").write_text("hunter2", encoding="utf-8")
    (vault.root / "key").write_text("AKIA...", encoding="utf-8")
    (vault.raw / "ok.md").write_text("ok", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "raw/ok.md" in paths
    assert "secret" not in paths
    assert "key" not in paths


@pytest.mark.parametrize(
    "rel",
    [
        "wiki/keys-overview.md",
        "wiki/cryptography-keys.md",
        "wiki/tokenization.md",
        "wiki/access-token-flow-notes.md",
        "wiki/monkey-patching.md",
        "wiki/whiskey.md",
        "raw/donkey.md",
        "wiki/keynote-summary.md",
        "raw/secret-history-of-x.md",
        "wiki/secrets-of-x.md",
    ],
)
def test_commit_stages_legitimate_notes_with_credential_substrings(
    vault: Vault, rel: str
) -> None:
    (vault.raw / "_seed.md").write_text("seed", encoding="utf-8")
    wiki_dir = vault.root / "wiki"
    wiki_dir.mkdir(exist_ok=True)
    (wiki_dir / "_seed.md").write_text("seed", encoding="utf-8")
    _git(vault.root, "add", "-A")
    _git(vault.root, "commit", "-q", "-m", "seed")

    target = vault.root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("body", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert rel in paths


def test_commit_expands_untracked_dirs_before_filtering_credentials(
    vault: Vault,
) -> None:
    wiki_dir = vault.root / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "ok.md").write_text("ok", encoding="utf-8")
    (wiki_dir / ".env").write_text("OPENAI_API_KEY=sk-xxx", encoding="utf-8")
    (wiki_dir / "api_key.toml").write_text("secret = true", encoding="utf-8")

    status = _git(vault.root, "status", "--porcelain=v1").stdout
    assert "?? wiki/" in status

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "wiki/ok.md" in paths
    assert "wiki/.env" not in paths
    assert "wiki/api_key.toml" not in paths


def test_commit_skips_vendor_dir(vault: Vault) -> None:
    vendor = vault.root / "vendor" / "notebooklm"
    vendor.mkdir(parents=True)
    (vendor / "session.json").write_text("{}", encoding="utf-8")
    (vault.raw / "ok.md").write_text("ok", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "raw/ok.md" in paths
    assert not any(p.startswith("vendor/") for p in paths)


def test_commit_noop_when_only_denied_paths_change(vault: Vault) -> None:
    head_before = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    (vault.root / "r2.toml").write_text("[r2]\nsecret_key='x'\n", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    head_after = _git(vault.root, "rev-parse", "HEAD").stdout.strip()
    assert head_before == head_after


def test_commit_allows_normal_paths(vault: Vault) -> None:
    (vault.raw / "n.md").write_text("n", encoding="utf-8")
    wiki_dir = vault.root / "wiki"
    wiki_dir.mkdir()
    (wiki_dir / "w.md").write_text("w", encoding="utf-8")
    (vault.assets / "a.bin").write_bytes(b"a")
    (vault.root / "README.md").write_text("readme", encoding="utf-8")
    (vault.root / "uv.lock").write_text("# lock", encoding="utf-8")
    llmwiki = vault.root / ".llmwiki"
    llmwiki.mkdir()
    (llmwiki / "notebooks.json").write_text("{}", encoding="utf-8")

    a = GitAutopilot(vault, debounce_seconds=0.1)
    a._commit()

    paths = _committed_paths(vault.root)
    assert "raw/n.md" in paths
    assert "wiki/w.md" in paths
    assert "assets/a.bin" in paths
    assert "README.md" in paths
    assert "uv.lock" in paths
    assert ".llmwiki/notebooks.json" in paths


def test_push_aborts_if_denied_path_already_staged(
    vault_with_remote: tuple[Vault, Path],
) -> None:
    vault, bare = vault_with_remote
    (vault.root / "r2.toml").write_text(
        '[r2]\naccess_key="AKIA"\nsecret_key="leaked"\n', encoding="utf-8"
    )
    _git(vault.root, "add", "r2.toml")

    cfg = AutopilotConfig(push_enabled=True, push_remote="origin")
    a = GitAutopilot(vault, autopilot_cfg=cfg)
    with pytest.raises(PushFailed):
        a._push()

    remote_log = subprocess.run(
        ["git", "log", "--all", "--name-only", "--pretty=format:"],
        cwd=bare,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "r2.toml" not in remote_log
