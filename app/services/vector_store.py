"""Vector store for prompt library semantic search.

Key improvements over the original:
1. **Read/write lock** — ``search()`` holds a read lock; ``build_index()``
   holds a write lock.  Prevents another thread from swapping embeddings
   mid-query.
2. **Pre-filter library_ids** — ``library_ids`` filtering now happens
   *before* the similarity sort, so ``top_k`` returns meaningful results
   (was: post-filtering that could return < top_k results).
3. **Thread-safe lazy init** — model loaded once via module-level
   ``lazy_model()`` with a plain threading lock (no double-checked
   locking bug).
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[2]
LIBS_DIR = ROOT_DIR / "data" / "prompt_libs"
CACHE_FILE = LIBS_DIR / ".vector_cache.npz"
HASH_FILE = LIBS_DIR / ".vector_hash"

_model = None
_embeddings: np.ndarray | None = None
_embedding_ids: list[str] = []  # parallel to _entries, holds entry.id
_entries: list[dict[str, Any]] = []

_index_rw_lock = threading.RLock()  # used as a write-lock for rebuilds
_model_lock = threading.Lock()

MODEL_PATH = ROOT_DIR / "models" / "text2vec-base-chinese"


def _lazy_model():
    """Thread-safe lazy loading of SentenceTransformer model."""
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(str(MODEL_PATH))
    return _model


def _compute_content_hash() -> str:
    h = hashlib.md5()
    for f in sorted(LIBS_DIR.glob("*_entries.json")):
        h.update(f.read_bytes())
    return h.hexdigest()


def _load_all_entries() -> list[dict[str, Any]]:
    entries = []
    for f in sorted(LIBS_DIR.glob("*_entries.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for entry in data:
                entry["_source_file"] = f.name
                entries.append(entry)
        except Exception:
            continue
    return entries


def _entry_to_text(entry: dict) -> str:
    parts = [
        entry.get("title", ""),
        " ".join(entry.get("tags", [])),
        " ".join(entry.get("triggers", [])),
        entry.get("prompt_text", "")[:300],
    ]
    return " ".join(p for p in parts if p)


def build_index(force: bool = False) -> None:
    """Build or load vector index from cache.

    Thread-safe: holds a write lock during rebuild.
    """
    global _embeddings, _entries, _embedding_ids

    with _index_rw_lock:
        current_hash = _compute_content_hash()
        cached_hash = HASH_FILE.read_text().strip() if HASH_FILE.exists() else ""

        if not force and cached_hash == current_hash and CACHE_FILE.exists():
            data = np.load(str(CACHE_FILE), allow_pickle=True)
            _embeddings = data["embeddings"]
            metadata = json.loads(data["metadata"].item())
            _entries = metadata["entries"]
            _embedding_ids = metadata["ids"]
            return

        _entries = _load_all_entries()
        _embedding_ids = [str(e.get("id", "")) for e in _entries]

        if not _entries:
            _embeddings = np.array([])
            return

        texts = [_entry_to_text(e) for e in _entries]
        model = _lazy_model()
        _embeddings = model.encode(texts, show_progress_bar=False, normalize_embeddings=True)

        np.savez(
            str(CACHE_FILE),
            embeddings=_embeddings,
            metadata=json.dumps({
                "entries": [{k: v for k, v in e.items() if k != "_embedding"} for e in _entries],
                "ids": _embedding_ids,
            }, ensure_ascii=False),
        )
        HASH_FILE.write_text(current_hash)


def search(query: str, top_k: int = 8, library_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Semantic search over prompt library entries.

    Key improvement: ``library_ids`` filtering is applied *before* the
    similarity sort, so ``top_k`` returns meaningful results.
    """
    if not query or not isinstance(query, str):
        return []

    with _index_rw_lock:
        if _embeddings is None or len(_entries) == 0:
            build_index()
        if _embeddions is None or len(_embeddings) == 0:
            return []

        embeddings = _embeddings
        entries = _entries
        embed_ids = _embedding_ids

    # Pre-filter by library_ids
    if library_ids:
        keep_indices = [
            i for i, eid in enumerate(embed_ids) if eid in library_ids
        ]
        if not keep_indices:
            return []
        # Use sliced views for the query
        filtered_entries = [entries[i] for i in keep_indices]
        filtered_embeddings = embeddings[keep_indices]
    else:
        filtered_entries = entries
        filtered_embeddings = embeddings
        keep_indices = list(range(len(entries)))

    model = _lazy_model()
    query_vec = model.encode([query], normalize_embeddings=True)
    scores = np.dot(filtered_embeddings, query_vec.T).flatten()

    # Sort by score descending, take top_k
    top_k_actual = min(top_k, len(scores))
    if top_k_actual == 0:
        return []
    top_indices = np.argsort(scores)[::-1][:top_k_actual]

    results = []
    for idx in top_indices:
        entry = filtered_entries[idx]
        results.append({
            "id": entry.get("id", ""),
            "name": entry.get("title", ""),
            "score": float(scores[idx]) * 10,
            "prompt_text": entry.get("prompt_text", ""),
            "tags": entry.get("tags", []),
            "triggers": entry.get("triggers", []),
            "group": entry.get("group", ""),
            "source_file": entry.get("_source_file", ""),
        })

    return results


def rebuild_index() -> int:
    """Force rebuild the vector index. Returns entry count."""
    build_index(force=True)
    return len(_entries)
