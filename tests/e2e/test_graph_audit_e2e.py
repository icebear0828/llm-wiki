from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.e2e.helpers import REPO_ROOT, make_vault

pytestmark = pytest.mark.e2e


def test_wikictl_graph_audit_validates_sample_vault_over_real_cli(
    tmp_path: Path,
) -> None:
    vault = make_vault(tmp_path)
    (vault / "assets" / "report").mkdir()
    (vault / "assets" / "report" / "concept-a.md").write_text(
        "# Report\n", encoding="utf-8"
    )
    (vault / "raw" / "source-one.md").write_text(
        "---\ntitle: Source One\nstatus: done\n---\nOriginal source.\n",
        encoding="utf-8",
    )
    (vault / "wiki" / "concept-a.md").write_text(
        "---\n"
        "title: Concept A\n"
        "status: done\n"
        "sources:\n"
        "  - '[[source-one]]'\n"
        "---\n"
        "[[concept-b]]\n\n![[assets/report/concept-a.md]]\n",
        encoding="utf-8",
    )
    (vault / "wiki" / "concept-b.md").write_text(
        "---\ntitle: Concept B\nstatus: done\nsource: https://example.com/b\n---\n"
        "[[Concept A]]\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        ["uv", "run", "wikictl", "graph", "audit", "--vault", str(vault), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "ok"
    assert payload["summary"]["wiki_notes"] == 2
    assert payload["summary"]["raw_notes"] == 1
    assert payload["summary"]["broken_links"] == 0
    assert payload["summary"]["broken_embeds"] == 0
    assert payload["summary"]["missing_sources"] == 0
