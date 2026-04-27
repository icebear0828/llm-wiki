from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "autopilot.toml"

_VALID_STRATEGIES = {"fast-forward", "force-with-lease"}

DEFAULT_TEMPLATE = """\
# Auto-push for the vault. Default off — opt in by setting enabled = true.
# Authentication is delegated to git's credential helper (osxkeychain on macOS,
# libsecret on Linux). Never paste tokens here.

[push]
enabled = false
remote = "origin"
branch = ""                # empty = current HEAD
strategy = "fast-forward"  # fast-forward | force-with-lease
debounce_seconds = 30      # wait this long after a commit before pushing
"""


@dataclass(frozen=True)
class AutopilotConfig:
    push_enabled: bool = False
    push_remote: str = "origin"
    push_branch: str = ""
    push_strategy: str = "fast-forward"
    push_debounce_seconds: float = 30.0

    @classmethod
    def load(cls, vault_root: Path) -> "AutopilotConfig":
        toml_path = Path(vault_root) / CONFIG_FILENAME
        data: dict[str, object] = {}
        if toml_path.is_file():
            with toml_path.open("rb") as f:
                data = tomllib.load(f)

        push_raw = data.get("push") if isinstance(data.get("push"), dict) else {}
        push: dict[str, object] = push_raw if isinstance(push_raw, dict) else {}

        enabled = bool(push.get("enabled", False))
        remote = str(push.get("remote", "origin"))
        branch = str(push.get("branch", ""))
        strategy = str(push.get("strategy", "fast-forward"))
        if strategy not in _VALID_STRATEGIES:
            raise ValueError(
                f"autopilot.toml [push] strategy must be one of {sorted(_VALID_STRATEGIES)}; got {strategy!r}"
            )
        debounce_raw = push.get("debounce_seconds", 30)
        debounce = float(debounce_raw) if isinstance(debounce_raw, (int, float)) else 30.0

        return cls(
            push_enabled=enabled,
            push_remote=remote,
            push_branch=branch,
            push_strategy=strategy,
            push_debounce_seconds=debounce,
        )


def write_default_template(vault_root: Path) -> tuple[Path, bool]:
    target = Path(vault_root) / CONFIG_FILENAME
    if target.exists():
        return target, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(DEFAULT_TEMPLATE, encoding="utf-8")
    return target, True
