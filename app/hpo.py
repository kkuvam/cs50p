"""
Meilisearch HPO search client.
Supports hybrid search (keyword + vector) when sentence-transformers is installed.
Initialised once at app startup via init_app().
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

HPO_INDEX_UID = "hpo"
HPO_EMBEDDING_DIMENSIONS = int(os.environ.get("HPO_EMBEDDING_DIMENSIONS", "384"))
HPO_EMBEDDING_MODEL = (os.environ.get("HPO_EMBEDDING_MODEL") or "all-MiniLM-L6-v2").strip()

_client = None
_index = None
_embedding_model = None


def init_app() -> None:
    """Initialise Meilisearch client and embedding model. Idempotent."""
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
