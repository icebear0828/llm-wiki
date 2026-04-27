from __future__ import annotations

from llmwiki.notecraft import parse_notebook_id


def test_parse_notebook_id_basic() -> None:
    stderr = "[progress] uploading...\nNotebook: https://notebooklm.google.com/notebook/abc-123\n"
    assert parse_notebook_id(stderr) == "abc-123"


def test_parse_notebook_id_with_query_string() -> None:
    stderr = "Notebook: https://notebooklm.google.com/notebook/xyz789?foo=bar\n"
    assert parse_notebook_id(stderr) == "xyz789"


def test_parse_notebook_id_missing() -> None:
    assert parse_notebook_id("just some unrelated stderr\n") is None


def test_parse_notebook_id_empty() -> None:
    assert parse_notebook_id("") is None


def test_parse_notebook_id_picks_last_when_multiple() -> None:
    stderr = (
        "Notebook: https://notebooklm.google.com/notebook/first-id\n"
        "later log line\n"
        "Notebook: https://notebooklm.google.com/notebook/second-id\n"
    )
    assert parse_notebook_id(stderr) == "second-id"
