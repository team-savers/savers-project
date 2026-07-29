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
    from sentence_transformers import SentenceTransformer

    chunks = chunk_csv(csv_path)
    if not chunks:
        print(f"no chunks produced from {csv_path}")
        return 0

    model = SentenceTransformer(model_name)
    embeddings = model.encode([c.text for c in chunks]).tolist()

    client = chromadb.PersistentClient(path=persist_dir)
    collection = client.get_or_create_collection(collection_name)
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
