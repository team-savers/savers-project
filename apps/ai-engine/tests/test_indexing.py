"""Chunk -> Chroma metadata mapping.

Pure function, no chromadb/sentence-transformers needed — runs in core CI.

Convention: tests/ mirrors src/ (src/ai_engine/indexing.py -> tests/test_indexing.py).
"""

from ai_engine.chunking import Chunk
from ai_engine.indexing import chunk_metadata


def test_known_labels_map_to_the_flood_contract_type() -> None:
    """호우/홍수 둘 다 disaster_type="flood"로 매핑되고, 원본 한글명은 source_category에 남는다."""
    for label in ("호우", "홍수"):
        chunk = Chunk(text="- 지침", disaster_type=label, stage="특보중")
        metadata = chunk_metadata(chunk)
        assert metadata["disaster_type"] == "flood"
        assert metadata["source_category"] == label


def test_unmapped_label_keeps_its_own_name() -> None:
    """계약에 아직 없는 재난유형(태풍 등)은 disaster_type도 원본 라벨을 그대로 쓴다."""
    chunk = Chunk(text="- 지침", disaster_type="태풍", stage="특보중")
    metadata = chunk_metadata(chunk)
    assert metadata["disaster_type"] == "태풍"
    assert metadata["source_category"] == "태풍"


def test_optional_fields_are_omitted_when_absent() -> None:
    """Chroma 메타데이터는 None을 허용하지 않으므로, 없는 필드는 아예 키를 빼야 한다."""
    chunk = Chunk(text="- 지침", disaster_type="호우", stage="특보중")
    metadata = chunk_metadata(chunk)
    assert "url" not in metadata
    assert "step_order" not in metadata
    assert "step_total" not in metadata


def test_optional_fields_are_included_when_present() -> None:
    chunk = Chunk(
        text="1. 지침",
        disaster_type="호우",
        stage="특보중",
        url="http://example.com",
        step_order=1,
        step_total=3,
    )
    metadata = chunk_metadata(chunk)
    assert metadata["url"] == "http://example.com"
    assert metadata["step_order"] == 1
    assert metadata["step_total"] == 3
