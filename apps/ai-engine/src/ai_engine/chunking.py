"""CSV ingestion + chunking stage for the 국민행동요령 corpus.

Pipeline direction is one-way (parsing -> chunking -> embedding -> retrieval ->
generation); this module must not import retrieval or generation.

The source CSV (행정안전부 국민행동요령 export, see `fixtures/typhoon_sample.csv`) has one
guidance sentence per row, tagged with a disaster type + lifecycle stage (예보시/특보중/
이후). The row text itself decides how it should be chunked:

- "- ..." rows are already complete, standalone instructions -> one row, one chunk.
- "1. ..." rows are numbered steps of an ordered procedure -> grouped by
  (safety_cate_nm2, safety_cate_nm3) so a chunk carries its position (`step_order`) and the
  size of its procedure (`step_total`); without that, an ordered list would be presented to
  the model as unrelated isolated facts.
- Rows with neither prefix but a non-empty stage are, on inspection, complete standalone
  sentences (e.g. a "이웃과 협력" instruction living next to a numbered list, not a
  fragment of it) -> chunked like the "-" rows rather than forced into the numbered group.
- Rows with only a `contentsUrl` and no stage are video-teaser rows with no actionable
  text -> excluded; there is nothing here for the guardrail to cite.
- Rows with an empty `actRmks` are excluded regardless of stage — the real flood corpus
  has icon-image rows (`contentsUrl` pointing at a `.png`, not a video) that carry a stage
  but no text at all. Same reasoning as the video-teaser case: no text, nothing to cite.

⚠️ Known backlog (tracked here, not blocking this pass):
- 실제 코퍼스 확보 후 KURE(한국어 특화 임베딩)와 BGE-M3의 근거 일치율을 비교해 볼 것.
- BGE-M3 CPU 추론 지연이 알림 도달 속도 KPI(≤30s, ADR-0003 단일 CPU VM/GPU 없음)에
  영향을 주는지 아직 실측하지 않았음 — 임베딩을 실제로 붙이는 시점에 반드시 측정.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

# The CSV export repeats the column description as its own data row (원본 다운로드 그대로),
# not a per-file quirk — filtered out by matching the fixed sentinel text, not by position,
# so a re-exported CSV with the header row removed still parses correctly.
_HEADER_ECHO_SENTINEL = "콘텐츠 내용"

_NUMBERED_PREFIX = re.compile(r"^(\d+)\.\s*")


@dataclass(frozen=True)
class Chunk:
    """One retrievable unit before embedding.

    Kept separate from `ai_engine.models.Passage`: that model is the retrieval-facing
    backend<->engine contract (ADR-0006), and `step_order`/`step_total` are a chunking-only
    concern that must not leak into it.
    """

    text: str
    disaster_type: str
    stage: str
    url: str | None = None
    step_order: int | None = None
    step_total: int | None = None


def parse_rows(path: Path) -> list[dict[str, str]]:
    """Read the CSV export, dropping the repeated-header decoy row.

    A trailing blank line at end-of-file needs no special handling here: `csv.DictReader`
    already skips a genuinely empty line without producing a row for it.
    """
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return [row for row in reader if not row["actRmks"].startswith(_HEADER_ECHO_SENTINEL)]


def chunk_rows(rows: list[dict[str, str]]) -> list[Chunk]:
    """Apply the standalone / numbered-group / excluded rules described above."""
    standalone: list[Chunk] = []
    numbered_groups: dict[tuple[str, str], list[dict[str, str]]] = {}

    for row in rows:
        text = row["actRmks"].strip()
        if not text:
            # Icon-image / video-teaser row (no body text) -> nothing here to chunk,
            # regardless of whether a stage is present.
            continue

        stage = row["safety_cate_nm3"].strip()
        if not stage:
            # contentsUrl-only teaser row (no stage) -> nothing here to chunk.
            continue

        disaster_type = row["safety_cate_nm2"].strip()
        url = row["contentsUrl"].strip() or None

        if _NUMBERED_PREFIX.match(text):
            numbered_groups.setdefault((disaster_type, stage), []).append(row)
            continue

        standalone.append(Chunk(text=text, disaster_type=disaster_type, stage=stage, url=url))

    chunks = list(standalone)
    for (disaster_type, stage), group_rows in numbered_groups.items():
        total = len(group_rows)
        for row in group_rows:
            text = row["actRmks"].strip()
            match = _NUMBERED_PREFIX.match(text)
            order = int(match.group(1)) if match else None
            chunks.append(
                Chunk(
                    text=text,
                    disaster_type=disaster_type,
                    stage=stage,
                    url=row["contentsUrl"].strip() or None,
                    step_order=order,
                    step_total=total,
                )
            )
    return chunks


def chunk_csv(path: Path) -> list[Chunk]:
    return chunk_rows(parse_rows(path))


def chunk_id(chunk: Chunk) -> str:
    """Stable id for indexing (Chroma upsert key).

    Hashed from content, not row position: re-exporting the same CSV with rows reordered
    (or re-running the indexing script) must land on the same ids, or upsert becomes
    silent duplication instead of an update.
    """
    key = f"{chunk.disaster_type}|{chunk.stage}|{chunk.step_order}|{chunk.text}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]  # noqa: S324 -- content id, not security
