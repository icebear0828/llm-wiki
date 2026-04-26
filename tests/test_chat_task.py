from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from llmwiki import notecraft
from llmwiki.tasks import chat
from llmwiki.vault import Note


def _make_note(tmp_path: Path, frontmatter: str, body: str = "hi\n") -> Note:
    p = tmp_path / "n.md"
    p.write_text(f"---\n{frontmatter}---\n{body}", encoding="utf-8")
    return Note(p)


class _FakeCompleted:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_chat_runs_and_appends_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = list(argv)
        captured["cwd"] = kwargs.get("cwd")
        return _FakeCompleted(returncode=0, stdout="The answer is 42.\n")

    monkeypatch.setattr(chat.subprocess, "run", fake_run)

    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/chat']\nnotebook_id: nb-7\n"
        "chat_question: 'What is the meaning?'\nstatus: pending\n",
    )

    result = chat.run(note)
    assert result == {}

    argv = captured["argv"]
    assert argv == [
        "npx",
        "notebooklm",
        "chat",
        "nb-7",
        "--transport",
        "auto",
        "--question",
        "What is the meaning?",
    ]

    # body must include the answer
    n2 = Note(note.path)
    assert "## Chat: What is the meaning?" in n2.body
    assert "The answer is 42." in n2.body


def test_chat_missing_notebook_id_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(chat.subprocess, "run", fake_run)

    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/chat']\nchat_question: hi\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        chat.run(note)


def test_chat_missing_question_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv, **kwargs):
        raise AssertionError("subprocess.run should not be called")

    monkeypatch.setattr(chat.subprocess, "run", fake_run)

    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/chat']\nnotebook_id: nb-1\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        chat.run(note)


def test_chat_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv, **kwargs):
        return _FakeCompleted(returncode=2, stderr="boom: something failed")

    monkeypatch.setattr(chat.subprocess, "run", fake_run)

    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/chat']\nnotebook_id: nb-1\n"
        "chat_question: 'q?'\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError) as exc:
        chat.run(note)
    assert "boom" in str(exc.value)


def test_chat_timeout_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=300)

    monkeypatch.setattr(chat.subprocess, "run", fake_run)

    note = _make_note(
        tmp_path,
        "title: T\ntags: ['task/chat']\nnotebook_id: nb-1\n"
        "chat_question: 'q?'\nstatus: pending\n",
    )

    with pytest.raises(notecraft.NotecraftError):
        chat.run(note)
