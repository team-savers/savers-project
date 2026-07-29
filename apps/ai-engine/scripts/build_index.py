"""Build (or refresh) the Chroma index from a 국민행동요령 CSV export.

Requires the `rag` extra: `pip install -e "./apps/ai-engine[rag]"`.

⚠️ 배관 검증용. `fixtures/typhoon_sample.csv`는 실제 MVP 재난유형(호우·도시침수)이 아닌
태풍 샘플이라, `disaster_type` 메타데이터는 CSV의 `safety_cate_nm2` 값(예: "태풍")을 그대로
저장합니다 — `ai_engine.models.DisasterType`(현재 `Literal["flood"]`) 계약과는 별개입니다.
실제 호우 코퍼스가 들어오면 이 스크립트는 그대로 두고 `--csv`만 바꾸면 됩니다.

Usage:
    python scripts/build_index.py --csv src/ai_engine/fixtures/typhoon_sample.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ai_engine.chunking import Chunk, chunk_csv, chunk_id
from ai_engine.config import get_settings


def _metadata(chunk: Chunk) -> dict[str, str | int]:
    # Chroma metadata rejects None values outright, so optional fields are only included
    # when present rather than passed as null.
    metadata: dict[str, str | int] = {
        "disaster_type": chunk.disaster_type,
        "stage": chunk.stage,
    }
    if chunk.url is not None:
        metadata["url"] = chunk.url
    if chunk.step_order is not None:
        metadata["step_order"] = chunk.step_order
    if chunk.step_total is not None:
        metadata["step_total"] = chunk.step_total
    return metadata


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
        metadatas=[_metadata(c) for c in chunks],
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
