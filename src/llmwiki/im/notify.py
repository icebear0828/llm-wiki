from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path

import httpx

from .config import TelegramConfig

log = logging.getLogger(__name__)


def push_telegram(
    text: str,
    *,
    cfg: TelegramConfig,
    vault_root: Path,
    throttle_key: str = "default",
    window_seconds: int = 3600,
) -> None:
    if not cfg.bot_token or cfg.notify_chat_id is None:
        log.warning(
            "push_telegram skipped: bot_token=%s notify_chat_id=%s",
            bool(cfg.bot_token),
            cfg.notify_chat_id,
        )
        return

    state_dir = Path(vault_root) / ".llmwiki"
    state_file = state_dir / "notify-state.json"

    state: dict[str, str] = {}
    if state_file.is_file():
        try:
            raw = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                state = {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}
        except (OSError, ValueError) as e:
            log.warning("notify state unreadable: %s", e)
            state = {}

    now = dt.datetime.now(dt.UTC)
    last_iso = state.get(throttle_key)
    if last_iso:
        try:
            last_ts = dt.datetime.fromisoformat(last_iso)
            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=dt.UTC)
            if (now - last_ts).total_seconds() < window_seconds:
                log.debug("push_telegram throttled key=%s", throttle_key)
                return
        except ValueError:
            pass

    url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
    try:
        response = httpx.post(
            url,
            json={"chat_id": cfg.notify_chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001 — best-effort notify
        log.error("push_telegram failed: %s", e)
        return

    if getattr(response, "status_code", 0) != 200:
        log.error("push_telegram non-200: %s", getattr(response, "status_code", "?"))
        return

    state[throttle_key] = now.isoformat()
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        tmp = state_file.with_suffix(state_file.suffix + ".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, state_file)
    except OSError as e:
        log.error("push_telegram state write failed: %s", e)
