"""ChromaRetriever behaviour.

Most tests here exercise `ChromaRetriever.search` against a fake collection/model — no
`chromadb`/`sentence_transformers` needed — so they run in core CI (which never installs
the `rag` extra) exactly like every other test in this app (AGENTS.md: tests run offline).

One test (`test_from_persist_dir_round_trip`) is a real, opt-in integration check against
the actual BGE-M3 model + an on-disk Chroma index. It downloads the model on first run, so
it is gated behind both the `rag` extra being installed *and* an explicit env var — a
plain `pytest` run must stay network-free even on a machine that has `rag` installed for
indexing work.

Convention: tests/ mirrors src/ (src/ai_engine/retrieval.py -> tests/test_retrieval.py,
tests/test_chroma_retriever.py for the Chroma-specific class).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

import pytest

from ai_engine.retrieval import ChromaRetriever


class _FakeVector:
    """Mimics the numpy array `SentenceTransformer.encode` returns — only `.tolist()` is used."""

    def __init__(self, values: list[float]) -> None:
        self._values = values

    def tolist(self) -> list[float]:
        return self._values


class _FakeModel:
    """Stands in for `SentenceTransformer` — only `.encode(text).tolist()` is used."""

    def encode(self, _text: str) -> _FakeVector:
        return _FakeVector([0.0])


class _FakeCollection:
    """Stands in for a `chromadb.Collection`.

    Holds canned rows keyed by disaster_type so `.query` can honor the `where` filter the
    same way a real collection would, which is what `test_disaster_type_is_a_hard_filter`
    checks.
    """

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.last_n_results: int | None = None

    def query(
        self, *, query_embeddings: list[list[float]], n_results: int, where: dict[str, str]
    ) -> dict[str, list[list[Any]]]:
        self.last_n_results = n_results
        matched = [
            r for r in self._rows if r["metadata"]["disaster_type"] == where["disaster_type"]
        ]
        matched = matched[:n_results]
        return {
            "ids": [[r["id"] for r in matched]],
            "documents": [[r["document"] for r in matched]],
            "distances": [[r["distance"] for r in matched]],
            "metadatas": [[r["metadata"] for r in matched]],
        }


def _retriever(rows: list[dict[str, Any]]) -> tuple[ChromaRetriever, _FakeCollection]:
    collection = _FakeCollection(rows)
    return ChromaRetriever(collection, _FakeModel()), collection


def test_disaster_type_is_a_hard_filter() -> None:
    """다른 재난유형의 청크는 애초에 후보에 오르지 않아야 한다 (FixtureRetriever와 동일 계약)."""
    retriever, _ = _retriever(
        [
            {
                "id": "a",
                "document": "태풍 지침",
                "distance": 0.1,
                "metadata": {"disaster_type": "태풍", "stage": "특보중 행동요령"},
            },
            {
                "id": "b",
                "document": "호우 지침",
                "distance": 0.1,
                "metadata": {"disaster_type": "flood", "stage": "특보중 행동요령"},
            },
        ]
    )
    passages = retriever.search("질의", disaster_type="태풍", tags=[], top_k=5)
    assert [p.id for p in passages] == ["a"]


def test_candidate_pool_uses_multiplier() -> None:
    """부스트 재정렬을 위해 top_k보다 넉넉히 후보를 가져와야 한다."""
    retriever, collection = _retriever([])
    retriever.search("질의", disaster_type="태풍", tags=[], top_k=4)
    assert collection.last_n_results == 4 * ChromaRetriever.CANDIDATE_MULTIPLIER


def test_score_is_similarity_plus_tag_boost() -> None:
    """score = (1 - distance) + 태그 겹침만큼의 부스트."""
    retriever, _ = _retriever(
        [
            {
                "id": "a",
                "document": "지침",
                "distance": 0.3,
                "metadata": {"disaster_type": "태풍", "stage": "특보중 행동요령"},
            }
        ]
    )
    # 지금 청크에는 취약성 태그가 없어 disaster_type 자체를 태그로 넘겨 부스트 메커니즘만 검증한다.
    passages = retriever.search("질의", disaster_type="태풍", tags=["태풍"], top_k=1)
    assert passages[0].score == pytest.approx(0.7 + ChromaRetriever.TAG_BOOST)


def test_tie_break_is_deterministic_by_id() -> None:
    """동점 시 id 오름차순 — 근거 일치율 채점이 재현 가능해야 한다."""
    retriever, _ = _retriever(
        [
            {
                "id": "z",
                "document": "지침",
                "distance": 0.2,
                "metadata": {"disaster_type": "태풍", "stage": "예보시 행동요령"},
            },
            {
                "id": "a",
                "document": "지침",
                "distance": 0.2,
                "metadata": {"disaster_type": "태풍", "stage": "예보시 행동요령"},
            },
        ]
    )
    passages = retriever.search("질의", disaster_type="태풍", tags=[], top_k=2)
    assert [p.id for p in passages] == ["a", "z"]


def test_no_candidates_returns_empty_list() -> None:
    retriever, _ = _retriever([])
    assert retriever.search("질의", disaster_type="태풍", tags=[], top_k=5) == []


_RAG_EXTRA_INSTALLED = importlib.util.find_spec("sentence_transformers") is not None
_OPT_IN_ENV_VAR = "AI_ENGINE_TEST_REAL_EMBEDDINGS"


@pytest.mark.skipif(
    not _RAG_EXTRA_INSTALLED or not os.environ.get(_OPT_IN_ENV_VAR),
    reason=(
        "real BGE-M3 + on-disk Chroma round trip; requires the `rag` extra and "
        f"{_OPT_IN_ENV_VAR}=1 (downloads the model, so opt-in only — never in CI)"
    ),
)
def test_from_persist_dir_round_trip(tmp_path: Path) -> None:
    from ai_engine.chunking import chunk_csv

    fixture = Path(__file__).parent.parent / "src" / "ai_engine" / "fixtures" / "typhoon_sample.csv"
    chunks = chunk_csv(fixture)
    assert chunks  # sanity: the fixture actually produced chunks to index

    retriever = ChromaRetriever.from_persist_dir(tmp_path, collection_name="test_action_manual")
    # No indexing helper is called here on purpose — this test only proves the seam
    # constructs and queries a real Chroma collection without raising; build_index.py
    # owns actually populating it.
    assert retriever.search("태풍 대비", disaster_type="태풍", tags=[], top_k=3) == []
