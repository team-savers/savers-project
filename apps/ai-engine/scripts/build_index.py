"""Build (or refresh) the Chroma index from a 국민행동요령 CSV export.

Requires the `rag` extra: `pip install -e "./apps/ai-engine[rag]"`.

Metadata mapping (Korean disaster label -> `DisasterType` contract value) lives in
`ai_engine.indexing` — see that module's docstring — so it stays importable and testable
without the `rag` extra. This script is just the CLI: chunk -> embed -> upsert.

Usage:
    python scripts/build_index.py --csv src/ai_engine/fixtures/flood_action_manual.csv
"""

from __future__ import annotations

import argparse
import contextlib
from pathlib import Path

from ai_engine.chunking import chunk_csv, chunk_id
from ai_engine.config import get_settings
from ai_engine.indexing import chunk_metadata


def build_index(
    csv_path: Path,
    *,
    persist_dir: str,
    collection_name: str,
    model_name: str,
) -> int:
    import chromadb
    from chromadb.errors import NotFoundError
    from sentence_transformers import SentenceTransformer

    chunks = chunk_csv(csv_path)
    if not chunks:
        print(f"no chunks produced from {csv_path}")
        return 0

    model = SentenceTransformer(model_name)
    # normalize_embeddings=True: cosine similarity is only well-defined for unit vectors —
    # explicit here rather than relying on BAAI/bge-m3 happening to normalize by default.
    embeddings = model.encode([c.text for c in chunks], normalize_embeddings=True).tolist()

    client = chromadb.PersistentClient(path=persist_dir)
    # Drop and recreate rather than upsert-only: chunk ids are content hashes
    # (chunking.chunk_id), so a row whose text changed (or was removed from the source)
    # gets a new id and its old entry would otherwise linger forever as a stale duplicate.
    with contextlib.suppress(NotFoundError):
        client.delete_collection(collection_name)  # first run: nothing to clean up yet
    # hnsw:space="cosine": Chroma's default is "l2", which `ChromaRetriever.search()`'s
    # `1 - distance` score would silently misinterpret as a cosine distance.
    collection = client.get_or_create_collection(collection_name, metadata={"hnsw:space": "cosine"})
    collection.upsert(
        ids=[chunk_id(c) for c in chunks],
        embeddings=embeddings,
        documents=[c.text for c in chunks],
        metadatas=[chunk_metadata(c) for c in chunks],
    )
    print(f"indexed {len(chunks)} chunks -> {persist_dir} ({collection_name})")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True, help="국민행동요령 CSV 경로")
    parser.add_argument(
        "--persist-dir", default=None, help="기본값: CHROMA_PERSIST_DIR 환경변수/설정"
    )
    parser.add_argument("--collection", default="action_manual")
    parser.add_argument("--model", default="BAAI/bge-m3")
    args = parser.parse_args()

    persist_dir = args.persist_dir or get_settings().chroma_persist_dir
    build_index(
        args.csv,
        persist_dir=persist_dir,
        collection_name=args.collection,
        model_name=args.model,
    )


if __name__ == "__main__":
    main()
