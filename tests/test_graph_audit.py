from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from llmwiki.cli import app


def _make_vault(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "assets" / "report").mkdir(parents=True)


def _run_graph_audit(root: Path) -> dict[str, object]:
    result = CliRunner().invoke(app, ["graph", "audit", "--vault", str(root), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert isinstance(payload, dict)
    return payload


def _checks_by_name(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    result: dict[str, dict[str, object]] = {}
    for item in checks:
        assert isinstance(item, dict)
        result[str(item["name"])] = item
    return result


def test_graph_audit_json_reports_graph_quality_problems(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    (tmp_path / "raw" / "source-one.md").write_text(
        "---\ntitle: Source One\nstatus: done\n---\nOriginal source.\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "concept-a.md").write_text(
        "---\n"
        "title: Concept A\n"
        "status: done\n"
        "sources:\n"
        "  - '[[source-one]]'\n"
        "---\n"
        "Links to [[concept-b|Concept B]], [[Missing Concept#intro]], "
        "and ![[assets/report/missing.pdf]].\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "concept-b.md").write_text(
        "---\ntitle: Concept B\nstatus: done\nsource: https://example.com/b\n---\n"
        "[[Concept A]]\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "no-source.md").write_text(
        "---\ntitle: No Source\nstatus: done\n---\nNo provenance.\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "stale-task.md").write_text(
        "---\ntitle: Stale Task\nstatus: done\ntags: [task/audio]\nsource: e2e://task\n---\n"
        "[[Concept A]]\n",
        encoding="utf-8",
    )
    for name in ("dup-one", "dup-two"):
        (tmp_path / "wiki" / f"{name}.md").write_text(
            "---\ntitle: Duplicate\nstatus: done\nsource: e2e://duplicate\n---\n",
            encoding="utf-8",
        )

    payload = _run_graph_audit(tmp_path)
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["wiki_notes"] == 6
    assert summary["raw_notes"] == 1
    assert summary["broken_links"] == 1
    assert summary["broken_embeds"] == 1
    assert summary["missing_sources"] == 1
    assert summary["ambiguous_links"] == 1
    assert summary["task_tags_after_done"] == 1

    checks = _checks_by_name(payload)
    assert checks["links"]["status"] == "error"
    assert checks["embeds"]["status"] == "error"
    assert checks["sources"]["status"] == "warn"
    assert checks["ambiguous_links"]["status"] == "warn"
    assert checks["task_tags"]["status"] == "warn"
    assert checks["links"]["items"] == [
        {
            "path": "wiki/concept-a.md",
            "target": "Missing Concept",
            "raw": "[[Missing Concept#intro]]",
        }
    ]


def test_graph_audit_clean_vault_reports_ok(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    (tmp_path / "assets" / "report" / "concept-a.md").write_text(
        "# Report\n", encoding="utf-8"
    )
    (tmp_path / "raw" / "source-one.md").write_text(
        "---\ntitle: Source One\nstatus: done\n---\nOriginal source.\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "concept-a.md").write_text(
        "---\n"
        "title: Concept A\n"
        "status: done\n"
        "sources:\n"
        "  - '[[source-one]]'\n"
        "---\n"
        "[[concept-b]]\n\n![[assets/report/concept-a.md]]\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "concept-b.md").write_text(
        "---\ntitle: Concept B\nstatus: done\nsource: https://example.com/b\n---\n"
        "[[Concept A]]\n",
        encoding="utf-8",
    )

    payload = _run_graph_audit(tmp_path)
    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["broken_links"] == 0
    assert summary["broken_embeds"] == 0
    assert summary["missing_sources"] == 0
    assert summary["ambiguous_links"] == 0
    assert summary["task_tags_after_done"] == 0
    assert payload["status"] == "ok"


def test_graph_audit_warns_on_unresolved_source_wikilink(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    (tmp_path / "wiki" / "a.md").write_text(
        "---\n"
        "title: A\n"
        "status: done\n"
        "sources:\n"
        "  - '[[missing-source]]'\n"
        "---\n"
        "[[b]]\n",
        encoding="utf-8",
    )
    (tmp_path / "wiki" / "b.md").write_text(
        "---\ntitle: B\nstatus: done\nsource: e2e://b\n---\n"
        "[[A]]\n",
        encoding="utf-8",
    )

    payload = _run_graph_audit(tmp_path)

    summary = payload["summary"]
    assert isinstance(summary, dict)
    assert summary["missing_sources"] == 1
    assert payload["status"] == "warn"

    checks = _checks_by_name(payload)
    assert checks["sources"]["status"] == "warn"
    assert checks["sources"]["items"] == [
        {
            "path": "wiki/a.md",
            "target": "missing-source",
            "raw": "[[missing-source]]",
            "reason": "unresolved_source",
        }
    ]
