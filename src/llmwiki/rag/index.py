from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from llmwiki.vault import Note, Vault

if TYPE_CHECKING:
    from chromadb.api import ClientAPI
    from chromadb.api.models.Collection import Collection
    from fastembed import TextEmbedding


@dataclass(frozen=True)
class Hit:
    path: Path
    rel_path: str
    title: str
    snippet: str
    score: float


def _make_snippet(body: str, limit: int = 400) -> str:
    flat = " ".join(body.split())
    return flat[:limit]


class _DenseIndex:
    # Default: multilingual MiniLM (~220MB, 384-dim) — fastembed only ships
    # multilingual-e5-large (2.24GB) for the e5 family, too heavy for MVP.
    # MiniLM covers CN+EN reasonably without the e5 "passage:/query:" prefix.
    def __init__(
        self,
        vault: Vault,
        *,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        self.vault = vault
        self.model_name = model_name
        self.persist_path = vault.root / ".llmwiki" / "chroma"
        self._embedder: TextEmbedding | None = None
        self._client: ClientAPI | None = None
        self._collection: Collection | None = None
        self._last_updated: dt.datetime | None = None

    def _ensure_embedder(self) -> TextEmbedding:
        if self._embedder is None:
            from fastembed import TextEmbedding

            self._embedder = TextEmbedding(model_name=self.model_name)
        return self._embedder

    def _ensure_collection(self) -> Collection:
        if self._collection is not None:
            return self._collection
        import chromadb
        from chromadb.config import Settings

        self.persist_path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.persist_path),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
        self._collection = self._client.get_or_create_collection(
            name="wiki_notes",
            metadata={"hnsw:space": "cosine", "model": self.model_name},
        )
        return self._collection

    def _is_e5(self) -> bool:
        return "e5" in self.model_name.lower()

    def _embed_passages(self, texts: list[str]) -> list[list[float]]:
        emb = self._ensure_embedder()
        inputs = [f"passage: {t}" for t in texts] if self._is_e5() else texts
        return [vec.tolist() for vec in emb.embed(inputs)]

    def _embed_query(self, text: str) -> list[float]:
        emb = self._ensure_embedder()
        inp = f"query: {text}" if self._is_e5() else text
        vecs = list(emb.embed([inp]))
        return cast(list[float], vecs[0].tolist())

    def _rel_id(self, path: Path) -> str:
        try:
            rel = path.resolve().relative_to(self.vault.root.resolve())
        except ValueError:
            rel = path
        return str(rel)

    def _existing_mtime(self, coll: Collection, rel_id: str) -> float | None:
        try:
            existing = coll.get(ids=[rel_id], include=["metadatas"])
        except Exception:
            return None
        metas = existing.get("metadatas") or []
        if not metas:
            return None
        meta = metas[0]
        if not meta:
            return None
        try:
            return float(meta.get("mtime", 0.0))
        except (TypeError, ValueError):
            return None

    def upsert(self, note: Note) -> None:
        coll = self._ensure_collection()
        rel_id = self._rel_id(note.path)
        try:
            mtime = note.path.stat().st_mtime
        except OSError:
            mtime = 0.0
        # Mtime short-circuit: skip the (expensive) fastembed encode if the
        # file content hasn't changed since the last upsert. Saves the bulk of
        # daemon-startup cost when LabelWatcher.scan_once enqueues every
        # wiki/*.md and most notes are unchanged.
        existing = self._existing_mtime(coll, rel_id)
        if existing is not None and mtime > 0.0 and existing == mtime:
            return
        doc = (note.title or note.path.stem) + "\n\n" + note.body
        embedding = self._embed_passages([doc])[0]
        meta: dict[str, Any] = {
            "title": note.title,
            "rel_path": rel_id,
            "mtime": mtime,
            "snippet": _make_snippet(note.body),
        }
        coll.upsert(
            ids=[rel_id],
            embeddings=[embedding],
            documents=[doc],
            metadatas=[meta],
        )
        self._last_updated = dt.datetime.now(dt.UTC)

    def remove(self, path: Path) -> None:
        coll = self._ensure_collection()
        rel_id = self._rel_id(path)
        try:
            coll.delete(ids=[rel_id])
        except Exception:
            return
        self._last_updated = dt.datetime.now(dt.UTC)

    def query(self, text: str, k: int = 5) -> list[Hit]:
        coll = self._ensure_collection()
        if coll.count() == 0:
            return []
        embedding = self._embed_query(text)
        n = min(k, coll.count())
        result = coll.query(
            query_embeddings=[embedding],
            n_results=n,
            include=["metadatas", "distances"],
        )
        hits: list[Hit] = []
        ids_lst = result.get("ids") or [[]]
        metas_lst = result.get("metadatas") or [[]]
        dists_lst = result.get("distances") or [[]]
        ids = ids_lst[0] if ids_lst else []
        metas = metas_lst[0] if metas_lst else []
        dists = dists_lst[0] if dists_lst else []
        for rel_id, meta, dist in zip(ids, metas, dists, strict=False):
            meta_dict = dict(meta) if meta else {}
            title = str(meta_dict.get("title", ""))
            rel_path = str(meta_dict.get("rel_path", rel_id))
            snippet = str(meta_dict.get("snippet", ""))
            score = max(0.0, 1.0 - float(dist))
            hits.append(
                Hit(
                    path=(self.vault.root / rel_path),
                    rel_path=rel_path,
                    title=title,
                    snippet=snippet,
                    score=score,
                )
            )
        return hits

    def reindex_all(self) -> int:
        if not self.vault.wiki.is_dir():
            return 0
        coll = self._ensure_collection()
        # Reconcile against disk: collect ids currently on disk, then delete
        # anything in the collection that isn't there anymore (orphans from
        # files deleted while daemon was offline).
        on_disk: list[tuple[Path, str]] = []
        for md in sorted(self.vault.wiki.rglob("*.md")):
            on_disk.append((md, self._rel_id(md)))
        disk_ids = {rel_id for _, rel_id in on_disk}
        try:
            existing = coll.get(include=[])
            existing_ids = list(existing.get("ids") or [])
        except Exception:
            existing_ids = []
        orphans = [eid for eid in existing_ids if eid not in disk_ids]
        if orphans:
            try:
                coll.delete(ids=orphans)
            except Exception:
                pass
        count = 0
        for md, _ in on_disk:
            try:
                note = Note(md)
            except Exception:
                continue
            self.upsert(note)
            count += 1
        if orphans:
            self._last_updated = dt.datetime.now(dt.UTC)
        return count

    def stats(self) -> dict[str, object]:
        coll = self._ensure_collection()
        return {
            "model": self.model_name,
            "count": coll.count(),
            "persist_path": str(self.persist_path),
            "last_updated_iso": (
                self._last_updated.isoformat() if self._last_updated else None
            ),
        }


def _rrf_fuse(
    dense: list[Hit],
    sparse: list[Hit],
    k: int,
    *,
    c: int = 60,
) -> list[Hit]:
    by_path: dict[str, Hit] = {}
    scores: dict[str, float] = {}
    for rank, hit in enumerate(dense):
        scores[hit.rel_path] = scores.get(hit.rel_path, 0.0) + 1.0 / (c + rank + 1)
        by_path[hit.rel_path] = hit
    for rank, hit in enumerate(sparse):
        scores[hit.rel_path] = scores.get(hit.rel_path, 0.0) + 1.0 / (c + rank + 1)
        # Prefer dense Hit metadata when both sides have the doc — its mtime
        # field round-trips through Chroma. Sparse-only hits use sparse meta.
        if hit.rel_path not in by_path:
            by_path[hit.rel_path] = hit
    if not scores:
        return []
    # Normalize so the top hit is 1.0 — raw RRF values (~0.033 max for c=60)
    # are not interpretable for end users. Relative ordering is preserved.
    max_score = max(scores.values())
    fused: list[Hit] = []
    for rel_path, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        h = by_path[rel_path]
        normalized = score / max_score if max_score > 0 else 0.0
        fused.append(
            Hit(
                path=h.path,
                rel_path=h.rel_path,
                title=h.title,
                snippet=h.snippet,
                score=normalized,
            )
        )
        if len(fused) >= k:
            break
    return fused


class WikiIndex:
    def __init__(
        self,
        vault: Vault,
        *,
        model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        from llmwiki.rag.bm25_index import BM25Index

        self.vault = vault
        self.model_name = model_name
        self._dense = _DenseIndex(vault, model_name=model_name)
        self._sparse = BM25Index(vault)
        self.persist_path = self._dense.persist_path
        # Sparse index is in-memory only and lazy-loaded: first call to
        # query() (or an explicit reindex_all()) bootstraps from wiki/. This
        # avoids paying jieba init + tokenize cost on every WikiIndex
        # instantiation (CLI one-shots, gateway worker boot, etc.). Watcher
        # upserts that arrive before bootstrap are dropped on the sparse
        # side — they'll be re-picked up from disk during bootstrap because
        # the file already exists by the time the watcher fires.
        self._sparse_loaded = False

    def upsert(self, note: Note) -> None:
        self._dense.upsert(note)
        if self._sparse_loaded:
            self._sparse.upsert(note)

    def remove(self, path: Path) -> None:
        self._dense.remove(path)
        if self._sparse_loaded:
            self._sparse.remove(path)

    def reindex_all(self) -> int:
        n = self._dense.reindex_all()
        self._sparse.reindex_all()
        self._sparse_loaded = True
        return n

    def query(self, text: str, k: int = 5) -> list[Hit]:
        if not self._sparse_loaded:
            self._sparse.reindex_all()
            self._sparse_loaded = True
        pool = max(k * 2, k)
        dense_hits = self._dense.query(text, k=pool)
        sparse_hits = self._sparse.query(text, k=pool)
        return _rrf_fuse(dense_hits, sparse_hits, k=k)

    def stats(self) -> dict[str, object]:
        info = dict(self._dense.stats())
        info["sparse_count"] = len(self._sparse._docs)
        return info


def get_index(vault: Vault) -> WikiIndex:
    return WikiIndex(vault)
