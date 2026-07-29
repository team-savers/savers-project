"""Chunk -> Chroma metadata mapping — the boundary between disaster-agnostic chunking and
the `ai_engine.models.DisasterType` contract.

`chunking.Chunk.disaster_type` carries whatever Korean label the CSV has (`safety_cate_nm2`:
호우, 홍수, 태풍, ...) — chunking stays disaster-agnostic on purpose (see its module
docstring). This module is where that label meets the contract (currently
`Literal["flood"]`): `DISASTER_TYPE_MAP` maps labels that mean "flood" for this MVP onto
`"flood"`, and `source_category` keeps the original label so it's never lost. A label with
no contract mapping yet (e.g. 태풍) keeps its own name in `disaster_type` too — there is
nowhere else for it to go until a matching `DisasterType` exists.
"""

from __future__ import annotations

from ai_engine.chunking import Chunk

# 호우/홍수 둘 다 MVP의 "flood" 타겟(호우·도시침수)에 해당한다 — 사용자 확인 완료.
DISASTER_TYPE_MAP: dict[str, str] = {
    "호우": "flood",
    "홍수": "flood",
}


def chunk_metadata(chunk: Chunk) -> dict[str, str | int]:
    # Chroma metadata rejects None values outright, so optional fields are only included
    # when present rather than passed as null.
    metadata: dict[str, str | int] = {
        "disaster_type": DISASTER_TYPE_MAP.get(chunk.disaster_type, chunk.disaster_type),
        "source_category": chunk.disaster_type,
        "stage": chunk.stage,
    }
    if chunk.url is not None:
        metadata["url"] = chunk.url
    if chunk.step_order is not None:
        metadata["step_order"] = chunk.step_order
    if chunk.step_total is not None:
        metadata["step_total"] = chunk.step_total
    return metadata
