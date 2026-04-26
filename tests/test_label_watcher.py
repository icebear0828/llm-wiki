from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from llmwiki.label_watcher import LabelWatcher
from llmwiki.vault import Note, Vault


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    (tmp_path / "assets").mkdir()
    return Vault(root=tmp_path)


def _make_note(vault: Vault, tag: str = "fake", name: str = "foo.md") -> Path:
    p = vault.raw / name
    p.write_text(
        f"---\ntitle: Foo\ntags:\n  - task/{tag}\nstatus: pending\n---\nhello\n",
        encoding="utf-8",
    )
    return p


def test_scan_once_happy(vault: Vault) -> None:
    art = vault.assets / "fake.bin"
    art.write_bytes(b"x")

    def fake_task(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        return {"fake": art}

    registry: dict[str, Callable[..., dict[str, Path]]] = {"fake": fake_task}
    watcher = LabelWatcher(vault, task_registry=registry)
    _make_note(vault, tag="fake")
    watcher.scan_once()

    moved = vault.wiki / "foo.md"
    assert moved.exists()
    assert not (vault.raw / "foo.md").exists()
    n = Note(moved)
    assert n.status == "done"
    assert n.task_tags == []
    assert "![[assets/fake.bin]]" in n.body


def test_scan_once_session_expired_keeps_tags(vault: Vault) -> None:
    class SessionExpired(Exception):
        pass

    def bad_task(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        raise SessionExpired("no session")

    watcher = LabelWatcher(vault, task_registry={"fake": bad_task})
    raw_path = _make_note(vault, tag="fake")
    watcher.scan_once()

    assert raw_path.exists()
    n = Note(raw_path)
    assert "task/fake" in n.tags
    assert n.status == "error"
    assert (vault.assets / "ALERT-session-expired.md").exists()


def test_session_expired_pushes_telegram(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    from llmwiki import label_watcher as lw_mod
    from llmwiki.im.config import ImConfig, TelegramConfig

    class SessionExpired(Exception):
        pass

    def bad_task(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        raise SessionExpired("no session")

    calls: list[dict[str, object]] = []

    def fake_push(text: str, *, cfg: TelegramConfig, vault_root: Path, throttle_key: str = "default", window_seconds: int = 3600) -> None:
        calls.append({"text": text, "cfg": cfg, "vault_root": vault_root, "throttle_key": throttle_key})

    monkeypatch.setattr(lw_mod, "push_telegram", fake_push)

    im_cfg = ImConfig(telegram=TelegramConfig(bot_token="t", notify_chat_id=99))
    watcher = LabelWatcher(vault, task_registry={"fake": bad_task}, im_config=im_cfg)
    _make_note(vault, tag="fake")
    watcher.scan_once()

    assert len(calls) == 1
    assert calls[0]["throttle_key"] == "session_expired"
    assert calls[0]["vault_root"] == vault.root
    assert calls[0]["cfg"] is im_cfg.telegram


def test_session_expired_no_push_without_im_config(vault: Vault, monkeypatch: pytest.MonkeyPatch) -> None:
    from llmwiki import label_watcher as lw_mod

    class SessionExpired(Exception):
        pass

    def bad_task(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        raise SessionExpired("no session")

    calls: list[object] = []
    monkeypatch.setattr(lw_mod, "push_telegram", lambda *a, **kw: calls.append(1))

    watcher = LabelWatcher(vault, task_registry={"fake": bad_task})
    _make_note(vault, tag="fake")
    watcher.scan_once()

    assert calls == []


def test_scan_once_generic_error_keeps_tags(vault: Vault) -> None:
    def bad_task(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        raise RuntimeError("boom")

    watcher = LabelWatcher(vault, task_registry={"fake": bad_task})
    raw_path = _make_note(vault, tag="fake")
    watcher.scan_once()

    assert raw_path.exists()
    n = Note(raw_path)
    assert "task/fake" in n.tags
    assert n.status == "error"


def test_scan_once_no_task_tags_skipped(vault: Vault) -> None:
    p = vault.raw / "x.md"
    p.write_text("---\ntags:\n  - foo\nstatus: pending\n---\nbody\n", encoding="utf-8")
    watcher = LabelWatcher(vault, task_registry={})
    watcher.scan_once()
    assert p.exists()
    assert not (vault.wiki / "x.md").exists()


def test_scan_once_passes_tag_arg_to_task(vault: Vault) -> None:
    captured: dict[str, str | None] = {}

    def fake_task(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        captured["arg"] = arg
        return {}

    watcher = LabelWatcher(vault, task_registry={"fake": fake_task})
    p = vault.raw / "argnote.md"
    p.write_text(
        "---\ntitle: T\ntags:\n  - 'task/fake:hello'\nstatus: pending\n---\nhi\n",
        encoding="utf-8",
    )
    watcher.scan_once()
    assert captured["arg"] == "hello"


def test_scan_once_source_add_stays_in_raw(vault: Vault) -> None:
    def fake_source_add(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        return {}

    watcher = LabelWatcher(vault, task_registry={"source-add": fake_source_add})
    p = vault.raw / "feed.md"
    p.write_text(
        "---\ntitle: F\ntags:\n  - 'task/source-add:nb-1'\nstatus: pending\nsource: https://x\n---\nhi\n",
        encoding="utf-8",
    )
    watcher.scan_once()

    assert p.exists()
    assert not (vault.wiki / "feed.md").exists()
    n = Note(p)
    assert n.status == "done"
    assert n.task_tags == []


def test_scan_once_chat_stays_in_raw(vault: Vault) -> None:
    def fake_chat(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        # mimic real chat: append to body and return {}
        note.append_body("\n\n## Chat: q\n\nA.\n")
        note.save()
        return {}

    watcher = LabelWatcher(vault, task_registry={"chat": fake_chat})
    p = vault.raw / "ask.md"
    p.write_text(
        "---\ntitle: Q\ntags:\n  - 'task/chat'\nstatus: pending\n"
        "notebook_id: nb-9\nchat_question: q\n---\nhi\n",
        encoding="utf-8",
    )
    watcher.scan_once()

    assert p.exists()
    assert not (vault.wiki / "ask.md").exists()
    n = Note(p)
    assert n.status == "done"
    assert n.task_tags == []
    assert "## Chat: q" in n.body


def test_scan_once_enqueues_when_worker_alive(vault: Vault) -> None:
    # Regression: previously scan_once called _process_note inline from the
    # main thread, racing with the watchdog-driven worker on the same file
    # (caused duplicate task runs). Now it enqueues so processing stays
    # serialized on the worker thread.
    import threading

    watcher = LabelWatcher(vault, task_registry={})
    fake_worker = threading.Thread(target=lambda: None)
    fake_worker.start()
    fake_worker.join()
    # Replace the joined thread with a still-alive one
    alive = threading.Event()
    started = threading.Event()

    def hold() -> None:
        started.set()
        alive.wait()

    t = threading.Thread(target=hold)
    t.start()
    started.wait()
    watcher._worker = t
    try:
        _make_note(vault, tag="fake", name="enqueue-me.md")
        watcher.scan_once()
        assert watcher._queue.qsize() == 1
        assert (vault.raw / "enqueue-me.md").exists()
        assert not (vault.wiki / "enqueue-me.md").exists()
    finally:
        alive.set()
        t.join()
