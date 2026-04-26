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


class WikiIndex:
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

    def upsert(self, note: Note) -> None:
        coll = self._ensure_collection()
        doc = (note.title or note.path.stem) + "\n\n" + note.body
        rel_id = self._rel_id(note.path)
        try:
            mtime = note.path.stat().st_mtime
        except OSError:
            mtime = 0.0
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
        count = 0
        if not self.vault.wiki.is_dir():
            return 0
        for md in sorted(self.vault.wiki.glob("*.md")):
            try:
                note = Note(md)
            except Exception:
                continue
            self.upsert(note)
            count += 1
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


def get_index(vault: Vault) -> WikiIndex:
    return WikiIndex(vault)
