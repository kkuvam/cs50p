"""
HPO search: in-memory regex search (primary) + Meilisearch hybrid search (fallback).
In-memory search loads data/hp.json once at startup; no external dependencies needed.
Meilisearch is used for the AutoHPO LLM pipeline when available.
Initialised once at app startup via init_app().
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

HPO_INDEX_UID = "hpo"
HPO_EMBEDDING_DIMENSIONS = int(os.environ.get("HPO_EMBEDDING_DIMENSIONS", "384"))
HPO_EMBEDDING_MODEL = (os.environ.get("HPO_EMBEDDING_MODEL") or "all-MiniLM-L6-v2").strip()

_client = None
_index = None
_embedding_model = None

# --- In-memory HPO search ---
_hpo_terms: list[dict] = []

_DEFAULT_HPO_JSON_PATHS = [
    Path(os.environ.get("HPO_JSON_PATH") or "") if os.environ.get("HPO_JSON_PATH") else None,
    Path("/opt/data/hp.json"),
    Path(__file__).resolve().parent.parent / "data" / "hp.json",
]


def _curie_from_id(node_id: str) -> str:
    if not node_id:
        return ""
    if "://" in node_id:
        part = node_id.split("/")[-1]
        if "_" in part:
            ns, rest = part.split("_", 1)
            return f"{ns.upper()}:{rest}"
        return part
    return node_id.replace("_", ":", 1) if "_" in node_id else node_id


def _parse_obographs(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out = []
    for graph in data.get("graphs", []):
        for node in graph.get("nodes", []):
            node_id = node.get("id") or ""
            curie = _curie_from_id(node_id)
            name = (node.get("lbl") or "").strip()
            meta = node.get("meta") or {}
            defn = ""
            if isinstance(meta.get("definition"), dict):
                defn = (meta["definition"].get("val") or "").strip()
            synonyms = [str(s["val"]).strip() for s in meta.get("synonyms", []) if isinstance(s, dict) and s.get("val")]
            out.append({
                "hpo_id": curie,
                "name": name,
                "definition": defn,
                "synonyms_str": " | ".join(synonyms) if synonyms else "",
            })
    return out


def _load_hpo_memory() -> None:
    global _hpo_terms
    if _hpo_terms:
        return
    for path in _DEFAULT_HPO_JSON_PATHS:
        if path and path.exists():
            try:
                _hpo_terms[:] = _parse_obographs(path)
                logger.info("Loaded %d HPO terms from %s", len(_hpo_terms), path)
                return
            except Exception as exc:
                logger.warning("Failed to load HPO JSON from %s: %s", path, exc)
    logger.warning("hp.json not found — in-memory HPO search disabled")


def search_hpo_memory(query: str, limit: int = 20) -> list[dict]:
    """Regex search over in-memory HPO terms (hpo_id, name, definition, synonyms_str)."""
    _load_hpo_memory()
    if not _hpo_terms:
        return []
    q = (query or "").strip()
    if not q:
        return _hpo_terms[:limit]
    pattern = re.compile(re.escape(q), re.IGNORECASE)
    matched = []
    for t in _hpo_terms:
        if (
            pattern.search(t.get("hpo_id") or "")
            or pattern.search(t.get("name") or "")
            or pattern.search(t.get("definition") or "")
            or pattern.search(t.get("synonyms_str") or "")
        ):
            matched.append({
                "hpo_id": t["hpo_id"],
                "name": t["name"],
                "definition": (t.get("definition") or "")[:500],
                "synonyms_str": t.get("synonyms_str") or "",
            })
            if len(matched) >= limit:
                break
    return matched


def init_app() -> None:
    """Initialise in-memory HPO search, Meilisearch client, and embedding model. Idempotent."""
    _load_hpo_memory()
    global _client, _index, _embedding_model
    if _client is None:
        try:
            from meilisearch import Client as MeilisearchClient
            url = (os.environ.get("MEILISEARCH_URL") or "http://localhost:7700").strip()
            api_key = (os.environ.get("MEILI_MASTER_KEY") or "").strip() or None
            _client = MeilisearchClient(url, api_key=api_key)
            _index = _client.index(HPO_INDEX_UID)
            health = _client.health()
            logger.info("Meilisearch health OK: %s — %s", url, health)
        except ImportError:
            logger.warning("meilisearch package not installed — AutoHPO disabled")
        except Exception as exc:
            logger.error("Meilisearch init FAILED: %s", exc)

    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedding_model = SentenceTransformer(HPO_EMBEDDING_MODEL)
            logger.info("Embedding model loaded: %s", HPO_EMBEDDING_MODEL)
        except ImportError:
            logger.warning("sentence-transformers not installed — vector search disabled")
        except Exception as exc:
            logger.warning("Embedding model load failed: %s", exc)


def _get_index():
    global _client, _index
    if _index is None:
        if _client is None:
            init_app()
        if _client is not None:
            _index = _client.index(HPO_INDEX_UID)
    return _index


def _embed_query(text: str) -> list[float] | None:
    if not (text or "").strip():
        return None
    if _embedding_model is None:
        return None
    vec = _embedding_model.encode(text.strip(), convert_to_numpy=True)
    return vec.tolist()


def prepare_search_query(query: str) -> str:
    if not (query or "").strip():
        return ""
    return " ".join(query.strip().split())


def search_hpo_results(query: str, limit: int = 5) -> tuple[list[dict], dict]:
    """
    Hybrid search over HPO index; returns (results, debug_info).
    Falls back to keyword-only if embeddings unavailable.
    """
    debug: dict = {"query_raw": query, "query_sent": "", "hit_count": 0, "error": None}
    q = prepare_search_query(query)
    search_q = q if q else query.strip()
    debug["query_sent"] = search_q
    if not search_q:
        debug["error"] = "empty query"
        return [], debug

    index = _get_index()
    if index is None:
        debug["error"] = "Meilisearch not available"
        return [], debug

    try:
        search_params: dict = {"limit": limit}
        query_vector = _embed_query(search_q)
        if query_vector is not None:
            search_params["vector"] = query_vector
            search_params["hybrid"] = {"embedder": HPO_EMBEDDING_MODEL}

        response = index.search(search_q, search_params)
        hits = response.get("hits") or []
        debug["hit_count"] = len(hits)
        results = [
            {
                "hpo_id": h.get("hpo_id"),
                "name": h.get("name"),
                "definition": (h.get("definition") or "")[:500],
                "synonyms_str": h.get("synonyms_str") or "",
            }
            for h in hits
        ]
        return results, debug
    except Exception as exc:
        logger.error("search_hpo_results(%r) FAILED: %s", search_q, exc)
        debug["error"] = str(exc)
        return [], debug
