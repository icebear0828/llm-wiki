from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from llmwiki.label_watcher import LabelWatcher
from llmwiki.vault import Note, Vault
from tests.e2e.helpers import make_vault

pytestmark = pytest.mark.e2e


def test_raw_task_to_wiki_closed_loop_with_run_record(tmp_path: Path) -> None:
    vault_root = make_vault(tmp_path)
    vault = Vault(vault_root)
    artifact = vault.assets / "report" / "local-e2e.md"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("# Local E2E Report\n", encoding="utf-8")

    raw = vault.raw / "local-e2e.md"
    raw.write_text(
        "---\n"
        "title: Local E2E\n"
        "source: e2e://local\n"
        "status: pending\n"
        "tags:\n"
        "  - task/local-report\n"
        "---\n"
        "This note links to [[Existing Concept]].\n",
        encoding="utf-8",
    )

    def local_report(note: Note, *, arg: str | None = None) -> dict[str, Path]:
        note.prepend_body("Generated local report.\n\n")
        return {"report": artifact}

    registry: dict[str, Callable[..., dict[str, Path]]] = {
        "local-report": local_report
    }
    watcher = LabelWatcher(vault, task_registry=registry)
    watcher.scan_once()

    wiki_note = vault.wiki / "local-e2e.md"
    assert wiki_note.is_file()
    assert not raw.exists()

    final = Note(wiki_note)
    assert final.status == "done"
    assert final.task_tags == []
    assert final.artifacts["report"] == Path("assets/report/local-e2e.md")
    assert "![[assets/report/local-e2e.md]]" in final.body
    assert "Generated local report." in final.body
    assert "[[Existing Concept]]" in final.body

    records = sorted((vault.root / ".llmwiki" / "runs").glob("*.json"))
    assert len(records) == 1
    payload = json.loads(records[0].read_text(encoding="utf-8"))
    assert payload["status"] == "done"
    assert payload["note"] == "raw/local-e2e.md"
    assert payload["final_note"] == "wiki/local-e2e.md"
    assert payload["artifacts"] == {"report": "assets/report/local-e2e.md"}
