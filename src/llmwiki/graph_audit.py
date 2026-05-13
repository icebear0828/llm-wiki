from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import frontmatter

AuditStatus = Literal["ok", "warn", "error"]
AuditItem = dict[str, object]
AuditCheck = dict[str, object]

_EMBED_RE = re.compile(r"!\[\[([^\]]+)\]\]")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]]+)\]\]")
_SOURCE_KEYS = ("source", "source_url", "source_file", "sources")


@dataclass(frozen=True)
class NoteRecord:
    path: Path
    rel_path: str
    zone: Literal["raw", "wiki"]
    metadata: dict[str, object]
    body: str


def audit_vault_graph(root: Path) -> dict[str, object]:
    vault_root = root.resolve()
    raw_notes = _load_notes(vault_root, "raw")
    wiki_notes = _load_notes(vault_root, "wiki")
    all_notes = [*raw_notes, *wiki_notes]
    link_index = _build_link_index(vault_root, all_notes)

    broken_links: list[AuditItem] = []
    broken_embeds: list[AuditItem] = []
    missing_sources: list[AuditItem] = []
    task_tags_after_done: list[AuditItem] = []
    inbound: dict[str, set[str]] = defaultdict(set)
    outbound: dict[str, set[str]] = defaultdict(set)

    for note in wiki_notes:
        for match in _WIKILINK_RE.finditer(note.body):
            raw = match.group(0)
            target = _link_target(match.group(1))
            if target == "":
                continue
            matches = _resolve_target(link_index, target)
            if not matches:
                broken_links.append(
                    {"path": note.rel_path, "target": target, "raw": raw}
                )
                continue
            outbound[note.rel_path].add(target)
            if len(matches) == 1:
                inbound[matches[0].rel_path].add(note.rel_path)

        for match in _EMBED_RE.finditer(note.body):
            raw = match.group(0)
            target = _link_target(match.group(1))
            if target == "":
                continue
            if not _embed_exists(vault_root, link_index, target):
                broken_embeds.append(
                    {"path": note.rel_path, "target": target, "raw": raw}
                )

        missing_sources.extend(_source_trace_items(note, link_index))

        task_tags = [
            tag for tag in _metadata_strings(note.metadata.get("tags")) if tag.startswith("task/")
        ]
        if str(note.metadata.get("status", "")).lower() == "done" and task_tags:
            task_tags_after_done.append({"path": note.rel_path, "tags": task_tags})

    ambiguous_links = _ambiguous_link_items(link_index)
    orphan_items = [
        {"path": note.rel_path}
        for note in wiki_notes
        if not inbound.get(note.rel_path) and not outbound.get(note.rel_path)
    ]

    checks = [
        _check("links", "error" if broken_links else "ok", broken_links),
        _check("embeds", "error" if broken_embeds else "ok", broken_embeds),
        _check("sources", "warn" if missing_sources else "ok", missing_sources),
        _check(
            "ambiguous_links",
            "warn" if ambiguous_links else "ok",
            ambiguous_links,
        ),
        _check("orphans", "warn" if orphan_items else "ok", orphan_items),
        _check(
            "task_tags",
            "warn" if task_tags_after_done else "ok",
            task_tags_after_done,
        ),
    ]
    status = _overall_status(checks)
    summary: dict[str, object] = {
        "root": str(vault_root),
        "raw_notes": len(raw_notes),
        "wiki_notes": len(wiki_notes),
        "broken_links": len(broken_links),
        "broken_embeds": len(broken_embeds),
        "missing_sources": len(missing_sources),
        "ambiguous_links": len(ambiguous_links),
        "orphans": len(orphan_items),
        "task_tags_after_done": len(task_tags_after_done),
    }
    return {"status": status, "summary": summary, "checks": checks}


def _load_notes(root: Path, zone: Literal["raw", "wiki"]) -> list[NoteRecord]:
    base = root / zone
    if not base.is_dir():
        return []
    notes: list[NoteRecord] = []
    for path in sorted(base.rglob("*.md")):
        try:
            post = frontmatter.load(str(path))
            metadata = dict(post.metadata)
            body = str(post.content)
        except Exception:
            metadata = {}
            body = path.read_text(encoding="utf-8", errors="replace")
        notes.append(
            NoteRecord(
                path=path,
                rel_path=path.relative_to(root).as_posix(),
                zone=zone,
                metadata=metadata,
                body=body,
            )
        )
    return notes


def _build_link_index(
    root: Path, notes: list[NoteRecord]
) -> dict[str, list[NoteRecord]]:
    index: dict[str, list[NoteRecord]] = defaultdict(list)
    for note in notes:
        for key in _note_keys(root, note):
            normalized = _normalize_key(key)
            if normalized:
                index[normalized].append(note)
    return dict(index)


def _note_keys(root: Path, note: NoteRecord) -> set[str]:
    keys: set[str] = {note.path.stem}
    rel_to_root = note.path.relative_to(root).with_suffix("").as_posix()
    keys.add(rel_to_root)
    zone_root = root / note.zone
    keys.add(note.path.relative_to(zone_root).with_suffix("").as_posix())

    title = note.metadata.get("title")
    if isinstance(title, str):
        keys.add(title)
    for alias in _metadata_strings(note.metadata.get("aliases")):
        keys.add(alias)
    for alias in _metadata_strings(note.metadata.get("alias")):
        keys.add(alias)
    return keys


def _metadata_strings(value: object) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, tuple):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _link_target(inner: str) -> str:
    target = inner.split("|", 1)[0].split("#", 1)[0].strip()
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target


def _normalize_key(value: str) -> str:
    key = value.strip().replace("\\", "/").strip("/")
    if key.lower().endswith(".md"):
        key = key[:-3]
    while "//" in key:
        key = key.replace("//", "/")
    return key.casefold()


def _resolve_target(
    link_index: dict[str, list[NoteRecord]], target: str
) -> list[NoteRecord]:
    return link_index.get(_normalize_key(target), [])


def _embed_exists(
    root: Path, link_index: dict[str, list[NoteRecord]], target: str
) -> bool:
    candidate = root / target
    if candidate.exists():
        return True
    if candidate.suffix == "" and candidate.with_suffix(".md").exists():
        return True
    return bool(_resolve_target(link_index, target))


def _source_trace_items(
    note: NoteRecord, link_index: dict[str, list[NoteRecord]]
) -> list[AuditItem]:
    has_trace = False
    items: list[AuditItem] = []
    for key in _SOURCE_KEYS:
        value = note.metadata.get(key)
        if not _source_value_present(value):
            continue
        has_trace = True
        for source in _source_strings(value):
            for match in _WIKILINK_RE.finditer(source):
                raw = match.group(0)
                target = _link_target(match.group(1))
                if target == "":
                    continue
                if not _resolve_target(link_index, target):
                    items.append(
                        {
                            "path": note.rel_path,
                            "target": target,
                            "raw": raw,
                            "reason": "unresolved_source",
                        }
                    )
    if not has_trace:
        return [{"path": note.rel_path, "reason": "missing_source"}]
    return items


def _source_value_present(value: object) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list | tuple):
        return any(_source_value_present(item) for item in value)
    if isinstance(value, dict):
        return bool(value)
    return False


def _source_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list | tuple):
        strings: list[str] = []
        for item in value:
            strings.extend(_source_strings(item))
        return strings
    if isinstance(value, dict):
        strings = []
        for item in value.values():
            strings.extend(_source_strings(item))
        return strings
    text = str(value).strip()
    return [text] if text else []


def _ambiguous_link_items(link_index: dict[str, list[NoteRecord]]) -> list[AuditItem]:
    items: list[AuditItem] = []
    for target, records in sorted(link_index.items()):
        paths = sorted({record.rel_path for record in records})
        if len(paths) > 1:
            items.append({"target": target, "paths": paths})
    return items


def _check(name: str, status: AuditStatus, items: list[AuditItem]) -> AuditCheck:
    return {"name": name, "status": status, "count": len(items), "items": items}


def _overall_status(checks: list[AuditCheck]) -> AuditStatus:
    statuses = {str(check.get("status", "warn")) for check in checks}
    if "error" in statuses:
        return "error"
    if "warn" in statuses:
        return "warn"
    return "ok"
