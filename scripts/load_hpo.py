#!/usr/bin/env python3
"""
Parse HPO obographs JSON (data/hp.json), embed terms, push to Meilisearch.

Run scripts/download_hpo.py first to get data/hp.json.

Env:
  MEILISEARCH_URL          - Meilisearch URL (default: http://localhost:7700)
  MEILI_MASTER_KEY         - API key if your instance requires one
  ENABLE_EMBEDDING         - "true" (default) = keyword + vector; "false" = keyword-only
  EMBEDDING_MODEL          - sentence-transformers model (default: sentence-transformers/all-MiniLM-L6-v2)
  FORCE_EMBEDDING_DOWNLOAD - "true" to re-download the model
  REPLACE_INDEX            - "true" to delete and recreate the index (clean load)

Usage:
    python scripts/load_hpo.py
    python scripts/load_hpo.py --replace-index
    python scripts/load_hpo.py --no-embed
    MEILISEARCH_URL=http://192.168.1.10:7700 python scripts/load_hpo.py
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

try:
    from meilisearch import Client as MeilisearchClient
except ImportError:
    print("Install meilisearch: pip install meilisearch", file=sys.stderr)
    sys.exit(1)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HPO_INDEX_UID = "hpo"
MEILISEARCH_PRIMARY_KEY = "id"
SEARCHABLE_ATTRIBUTES = ["hpo_id", "name", "definition", "synonyms_str"]
DEFAULT_EMBEDDER_NAME = "all-MiniLM-L6-v2"
DEFAULT_EMBEDDING_DIMENSIONS = 384


def _curie_to_safe_id(curie: str) -> str:
    if not curie:
        return ""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "_", curie)
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        safe = "unknown"
    if len(safe.encode("utf-8")) > 511:
        safe = safe[:500]
    return safe


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


def parse_obographs(path: Path) -> list[dict]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        raise SystemExit(f"Failed to read {path}: {e}") from e
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON in {path}: {e}") from e
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
            synonyms = []
            for s in meta.get("synonyms", []):
                if isinstance(s, dict) and s.get("val"):
                    synonyms.append(str(s["val"]).strip())
            synonyms_str = " | ".join(synonyms) if synonyms else ""
            out.append({
                "id": _curie_to_safe_id(curie),
                "hpo_id": curie,
                "name": name,
                "definition": defn,
                "synonyms_str": synonyms_str,
            })
    return out


def _embedding_enabled() -> bool:
    return os.environ.get("ENABLE_EMBEDDING", "true").strip().lower() in ("1", "true", "yes")


def _embedding_model_id() -> str:
    return (os.environ.get("EMBEDDING_MODEL") or "sentence-transformers/all-MiniLM-L6-v2").strip()


def _embedder_name() -> str:
    return (os.environ.get("HPO_EMBEDDER_NAME") or os.environ.get("EMBEDDER_NAME") or DEFAULT_EMBEDDER_NAME).strip()


def _embedding_dimensions() -> int:
    return int(os.environ.get("HPO_EMBEDDING_DIMENSIONS") or os.environ.get("EMBEDDING_DIMENSIONS") or DEFAULT_EMBEDDING_DIMENSIONS)


def create_index(client, index_uid, primary_key, embedder_name, dimensions, replace=False):
    if replace:
        try:
            idx = client.get_index(index_uid)
            print(f"Deleting existing index '{index_uid}' ...")
            task_info = idx.delete()
            idx.wait_for_task(task_info.task_uid, timeout_in_ms=15_000)
            print(f"Index '{index_uid}' deleted.")
        except Exception as e:
            print(f"Note: could not delete index (may not exist): {e}", file=sys.stderr)

    try:
        idx = client.get_index(index_uid)
        idx.fetch_info()
        current_pk = getattr(idx, "primary_key", None)
        if current_pk != primary_key:
            print(f"Recreating index with primary key '{primary_key}' (was '{current_pk}') ...")
            task_info = idx.delete()
            idx.wait_for_task(task_info.task_uid, timeout_in_ms=10_000)
            client.create_index(index_uid, {"primaryKey": primary_key})
            idx = client.index(index_uid)
        else:
            print(f"Index '{index_uid}' already exists (primary key: {primary_key}).")
    except Exception:
        print(f"Creating new index '{index_uid}' ...")
        client.create_index(index_uid, {"primaryKey": primary_key})
        idx = client.index(index_uid)

    idx.update_searchable_attributes(SEARCHABLE_ATTRIBUTES)

    print(f"Configuring embedder '{embedder_name}' (userProvided, dimensions={dimensions}) ...")
    try:
        task_info = idx.update_embedders({
            embedder_name: {"source": "userProvided", "dimensions": dimensions},
        })
        if getattr(task_info, "task_uid", None):
            idx.wait_for_task(task_info.task_uid, timeout_in_ms=15_000)
        print(f"Embedder '{embedder_name}' configured.")
    except Exception as e:
        print(f"Note: embedder settings: {e}", file=sys.stderr)
    return idx


def _compute_embeddings(terms, model_id, force_download=False):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("sentence-transformers not installed; skipping embeddings.", file=sys.stderr)
        return False, terms

    print(f"Loading embedding model ({model_id}) ...")
    try:
        if force_download:
            import tempfile
            tmp_cache = tempfile.mkdtemp(prefix="exomiser_embed_")
            model = SentenceTransformer(model_id, cache_folder=tmp_cache)
        else:
            model = SentenceTransformer(model_id)
    except Exception as e:
        print(f"Failed to load model {model_id}: {e}", file=sys.stderr)
        return False, terms

    texts = [
        f"{t['name']}. {t['definition']}. {t['synonyms_str']}".strip() or t["hpo_id"]
        for t in terms
    ]
    print(f"Computing embeddings for {len(texts)} terms ...")
    try:
        embeddings = model.encode(texts, show_progress_bar=True)
        for t, vec in zip(terms, embeddings, strict=True):
            t["_embedding"] = vec.tolist()
        print(f"Generated {len(embeddings)} embeddings.")
        return True, terms
    except Exception as e:
        print(f"Embedding failed: {e}", file=sys.stderr)
        return False, terms


def load_hpo(
    json_path: Path,
    meilisearch_url: str,
    api_key: str | None = None,
    embed: bool = True,
    embedding_model: str | None = None,
    force_embedding_download: bool = False,
    replace_index: bool = False,
    batch_size: int = 500,
) -> None:
    if not json_path.exists():
        raise FileNotFoundError(f"HPO JSON not found: {json_path}. Run scripts/download_hpo.py first.")
    if not meilisearch_url.strip():
        raise ValueError("MEILISEARCH_URL is required")

    use_embedding = embed and _embedding_enabled()
    model_id = (embedding_model or _embedding_model_id()).strip()

    print(f"Parsing {json_path} ...")
    terms = parse_obographs(json_path)
    print(f"Parsed {len(terms)} terms.")

    if use_embedding:
        use_embedding, terms = _compute_embeddings(terms, model_id, force_embedding_download)

    print(f"Search mode: {'keyword + embedding (hybrid)' if use_embedding else 'keyword-only'}.")

    client = MeilisearchClient(meilisearch_url, api_key=api_key or None)
    name = _embedder_name()
    dims = _embedding_dimensions()
    idx = create_index(client, HPO_INDEX_UID, MEILISEARCH_PRIMARY_KEY, name, dims, replace=replace_index)

    print(f"Building {len(terms)} documents ...")
    seen_ids: dict[str, dict] = {}
    for t in terms:
        doc = {
            "id": t["id"],
            "hpo_id": t["hpo_id"],
            "name": t["name"],
            "definition": t["definition"],
            "synonyms_str": t["synonyms_str"],
            "_vectors": {name: t["_embedding"] if use_embedding and "_embedding" in t else None},
        }
        seen_ids[t["id"]] = doc
    documents = list(seen_ids.values())
    if len(documents) < len(terms):
        print(f"Deduplicated: {len(terms)} -> {len(documents)} documents.")

    timeout_ms = 300_000
    print(f"Indexing {len(documents)} documents (batch_size={batch_size}) ...")
    failed_batches = []
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        try:
            task_info = idx.add_documents(batch)
            task = idx.wait_for_task(task_info.task_uid, timeout_in_ms=timeout_ms)
            if getattr(task, "status", None) == "failed":
                err = getattr(task, "error", None) or {}
                msg = err.get("message", err) if isinstance(err, dict) else err
                print(f"  Batch {i // batch_size + 1} failed: {msg}", file=sys.stderr)
                failed_batches.append((i, msg))
            else:
                print(f"  {min(i + batch_size, len(documents))}/{len(documents)}")
        except Exception as e:
            print(f"  Batch {i // batch_size + 1} error: {e}", file=sys.stderr)
            failed_batches.append((i, str(e)))

    if failed_batches:
        print(f"{len(failed_batches)} batch(es) failed.", file=sys.stderr)
        sys.exit(1)
    print("Done. All documents indexed successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load HPO from data/hp.json into Meilisearch")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR,
                        help=f"Directory containing hp.json (default: {DEFAULT_DATA_DIR})")
    parser.add_argument("--input", type=Path, default=None,
                        help="Path to hp.json (overrides --data-dir/hp.json)")
    parser.add_argument("--meilisearch-url",
                        default=os.environ.get("MEILISEARCH_URL", ""),
                        help="Meilisearch URL (default: MEILISEARCH_URL env)")
    parser.add_argument("--meili-master-key",
                        default=os.environ.get("MEILI_MASTER_KEY", ""),
                        help="Meilisearch API key (default: MEILI_MASTER_KEY env)")
    parser.add_argument("--no-embed", action="store_true",
                        help="Skip embedding (keyword-only search)")
    parser.add_argument("--embed-model", default=os.environ.get("EMBEDDING_MODEL", ""),
                        help="sentence-transformers model ID")
    parser.add_argument("--force-embedding-download", action="store_true",
                        help="Re-download embedding model (fixes stale cache)")
    parser.add_argument("--replace-index", action="store_true",
                        help="Delete existing index and load fresh")
    parser.add_argument("--batch-size", type=int, default=500,
                        help="Documents per batch (default: 500)")
    args = parser.parse_args()

    json_path = args.input or (args.data_dir / "hp.json")
    url = (args.meilisearch_url or "").strip()
    if not url:
        print("Error: set MEILISEARCH_URL env var or pass --meilisearch-url", file=sys.stderr)
        sys.exit(1)

    try:
        load_hpo(
            json_path,
            url,
            api_key=(args.meili_master_key or "").strip() or None,
            embed=not args.no_embed,
            embedding_model=(args.embed_model or "").strip() or None,
            force_embedding_download=args.force_embedding_download,
            replace_index=args.replace_index,
            batch_size=args.batch_size,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
