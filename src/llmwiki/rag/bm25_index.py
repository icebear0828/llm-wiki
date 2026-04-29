from __future__ import annotations

import threading
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING, Any

import jieba

from llmwiki.rag.index import Hit, _make_snippet
from llmwiki.vault import Note, Vault

if TYPE_CHECKING:
    import bm25s

# Silence jieba's startup chatter the first time it builds the prefix dict.
jieba.setLogLevel(60)


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    for raw in jieba.cut_for_search(text):
        if not raw:
            continue
        first = raw[0]
        cat = unicodedata.category(first)
        if cat[0] in ("Z", "C") or cat[0] == "P":
            continue
        if raw.isascii():
            out.append(raw.lower())
        else:
            out.append(raw)
    return out


class BM25Index:
    def __init__(self, vault: Vault) -> None:
        self.vault = vault
        self._docs: dict[str, list[str]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._bm25: bm25s.BM25 | None = None
        self._order: list[str] = []
        self._dirty = False
        # All mutating ops (upsert/remove/reindex_all/_rebuild) and the read
        # path (query) take this lock. Reentrancy is needed because query
        # calls _rebuild while holding the lock.
        self._lock = threading.RLock()

    def _rel_id(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self.vault.root.resolve())
        except ValueError:
            rel = path
        return str(rel)

    def upsert(self, note: Note) -> None:
        rel_id = self._rel_id(note.path)
        doc_text = (note.title or note.path.stem) + "\n\n" + note.body
        try:
            mtime = note.path.stat().st_mtime
        except OSError:
            mtime = 0.0
        # Tokenize outside the lock — pure CPU work, no shared state.
        tokens = _tokenize(doc_text)
        snippet = _make_snippet(note.body)
        with self._lock:
            self._docs[rel_id] = tokens
            self._meta[rel_id] = {
                "title": note.title,
                "snippet": snippet,
                "mtime": mtime,
            }
            self._dirty = True

    def remove(self, path: Path) -> None:
        rel_id = self._rel_id(path)
        with self._lock:
            if rel_id in self._docs:
                del self._docs[rel_id]
                self._meta.pop(rel_id, None)
                self._dirty = True

    def reindex_all(self) -> int:
        if not self.vault.wiki.is_dir():
            return 0
        # Tokenize all notes outside the lock, then swap in atomically.
        new_docs: dict[str, list[str]] = {}
        new_meta: dict[str, dict[str, Any]] = {}
        for md in sorted(self.vault.wiki.glob("*.md")):
            try:
                note = Note(md)
            except Exception:
                continue
            rel_id = self._rel_id(md)
            doc_text = (note.title or md.stem) + "\n\n" + note.body
            try:
                mtime = md.stat().st_mtime
            except OSError:
                mtime = 0.0
            new_docs[rel_id] = _tokenize(doc_text)
            new_meta[rel_id] = {
                "title": note.title,
                "snippet": _make_snippet(note.body),
                "mtime": mtime,
            }
        with self._lock:
            self._docs = new_docs
            self._meta = new_meta
            self._dirty = True
        return len(new_docs)

    def _rebuild(self) -> None:
        import bm25s

        # Caller holds self._lock.
        if not self._docs:
            self._bm25 = None
            self._order = []
            self._dirty = False
            return
        order = list(self._docs.keys())
        corpus = [self._docs[rid] for rid in order]
        bm = bm25s.BM25()
        bm.index(corpus, show_progress=False)
        self._order = order
        self._bm25 = bm
        self._dirty = False

    def query(self, text: str, k: int = 5) -> list[Hit]:
        tokens = _tokenize(text)
        if not tokens:
            return []
        with self._lock:
            if self._dirty or self._bm25 is None:
                self._rebuild()
            if self._bm25 is None or not self._order:
                return []
            n = min(k, len(self._order))
            result = self._bm25.retrieve(
                [tokens], k=n, show_progress=False, return_as="tuple"
            )
            doc_ids = result.documents[0]
            scores = result.scores[0]
            hits: list[Hit] = []
            for doc_idx, score in zip(doc_ids, scores, strict=False):
                if float(score) <= 0.0:
                    continue
                rel_id = self._order[int(doc_idx)]
                meta = self._meta.get(rel_id, {})
                title = str(meta.get("title", ""))
                snippet = str(meta.get("snippet", ""))
                hits.append(
                    Hit(
                        path=(self.vault.root / rel_id),
                        rel_path=rel_id,
                        title=title,
                        snippet=snippet,
                        score=float(score),
                    )
                )
            return hits
