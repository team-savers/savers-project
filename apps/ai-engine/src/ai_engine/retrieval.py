"""Retrieval stage: 국민행동요령 corpus -> grounded passages.

Pipeline direction is one-way (parsing -> chunking -> embedding -> retrieval ->
generation); nothing here may import the generation module.

What this is: the *shape* of conditional retrieval — a metadata filter (disaster type +
vulnerability tags) combined with a similarity score — running on a dummy fixture so the
vertical slice can be exercised offline. What this is not: the real retriever. Chroma +
Korean embeddings replace `FixtureRetriever` in S1-1/S1-2 (AI/RAG owns that); the
`Retriever` protocol is the seam that makes the swap a one-line change at the call site.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from ai_engine.models import DisasterType, Passage, RecipientContext

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "action_manual.jsonl"

# Vulnerability attribute -> corpus tag. Only attributes whose *presence* should pull in
# different source text are mapped; the rest affect phrasing, not retrieval.
_PROFILE_TAG_RULES: tuple[tuple[str, str], ...] = (
    ("banjiha", "banjiha"),
    ("lowland", "lowland"),
    ("assisted", "mobility_assisted"),
    ("slow", "mobility_assisted"),
)

# Query terms synthesized per attribute for the dispatch path, where there is no user
# question to search with. Real embeddings will make this cruder-but-cheap step obsolete.
_QUERY_TERMS: dict[str, str] = {
    "banjiha": "반지하 침수 대피",
    "lowland": "저지대 침수 대피",
    "assisted": "거동 불편 대피 도움",
    "slow": "천천히 이동 대피",
    "stairs": "계단 경사로 이동",
    "lives_alone": "혼자 있는 사람 연락",
    "care": "함께 있는 가족 대피",
}

# ⚠️ These are written in the *corpus's* vocabulary, not the alert's. "호우경보 행동요령"
# reads naturally but shares almost no wording with guidance text that talks about 물·이동·
# 대피, so a lexical retriever scores it near zero and every ordinary profile falls back to
# the generic message. Embedding retrieval removes this coupling; until then, changing a
# line here without re-checking recall against the corpus silently breaks the happy path.
_DISASTER_TERMS: dict[str, str] = {
    "flood": "호우 침수 위험 물이 차오르기 전에 안전한 곳으로 이동 대피",
}


class Retriever(Protocol):
    """Seam between the dummy fixture and the real Chroma index."""

    def search(
        self,
        query: str,
        *,
        disaster_type: DisasterType,
        tags: list[str],
        top_k: int,
    ) -> list[Passage]: ...


def profile_tags(profile: RecipientContext) -> list[str]:
    """Metadata filter axis derived from the profile.

    Returned tags *boost* rather than restrict: a passage matching none of them can still
    be retrieved. Hard-filtering on vulnerability would make an under-tagged corpus return
    nothing, and "no evidence" in a disaster means the user gets the generic fallback.
    """
    tags: list[str] = []
    for attribute in (profile.housing, profile.mobility):
        for value, tag in _PROFILE_TAG_RULES:
            if attribute == value:
                tags.append(tag)
    if not profile.stairs_ok:
        tags.append("stairs")
    if profile.lives_alone:
        tags.append("lives_alone")
    return tags


def build_query(disaster_type: DisasterType, profile: RecipientContext) -> str:
    """Synthesize the dispatch-path query (no user question exists at alert time)."""
    parts = [_DISASTER_TERMS.get(disaster_type, disaster_type)]
    for key in (profile.housing, profile.mobility):
        if key in _QUERY_TERMS:
            parts.append(_QUERY_TERMS[key])
    if not profile.stairs_ok:
        parts.append(_QUERY_TERMS["stairs"])
    if profile.lives_alone:
        parts.append(_QUERY_TERMS["lives_alone"])
    if profile.care:
        parts.append(_QUERY_TERMS["care"])
    return " ".join(parts)


def _bigrams(text: str) -> set[str]:
    """Character bigrams — a whitespace tokenizer is useless for Korean agglutination.

    Deliberately crude: this is a stand-in for embedding similarity, kept dependency-free
    so CI never drags in the RAG stack (heavy deps live in the `rag` extra).
    """
    compact = "".join(text.split())
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


class FixtureRetriever:
    """Lexical retriever over the committed dummy corpus.

    Scoring = bigram overlap with the query + a fixed boost per matching profile tag.
    The absolute numbers are meaningless across implementations; only the ordering is,
    which is why the contract documents `score` as implementation-dependent.

    ⚠️ Known limitation, and the reason embeddings are on the critical path: lexical
    matching misses paraphrase. "애를 데려가도 돼요?" retrieves nothing from a corpus that
    says 영유아·가족, so the chatbot refuses instead of answering. Refusing is the safe
    failure — but it is a recall failure, not correct behavior, and swapping in the Chroma
    retriever is what fixes it (AI/RAG, S1-1~S1-2).
    """

    TAG_BOOST = 0.15

    # A passage must earn *some* lexical overlap before profile tags can lift it. Without
    # this floor, an unrelated question ("주식 전망 알려줘") still matches every tagged
    # passage on boost alone, and the engine answers from evidence that has nothing to do
    # with the question — the exact failure the "근거 없으면 생성하지 않는다" rule targets.
    MIN_LEXICAL_OVERLAP = 0.05

    def __init__(self, passages: list[Passage]) -> None:
        self._passages = passages

    @classmethod
    def from_jsonl(cls, path: Path = FIXTURE_PATH) -> FixtureRetriever:
        """Load the corpus fixture.

        Raises FileNotFoundError rather than falling back to an empty corpus: an engine
        that silently retrieves nothing would look like "no evidence" and quietly send
        every user the generic fallback.
        """
        with path.open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        return cls([Passage(score=0.0, **row) for row in rows])

    @property
    def passages(self) -> list[Passage]:
        """Read-only view of the loaded corpus, for tests and eval tooling."""
        return list(self._passages)

    def search(
        self,
        query: str,
        *,
        disaster_type: DisasterType,
        tags: list[str],
        top_k: int,
    ) -> list[Passage]:
        query_grams = _bigrams(query)
        if not query_grams:
            return []

        wanted = set(tags)
        scored: list[Passage] = []
        for passage in self._passages:
            # Metadata filter: disaster type is a hard condition — 호우 지침을 다른 재난에
            # 인용하면 근거는 있는데 상황이 틀린, 가장 나쁜 종류의 오답이 된다.
            if disaster_type not in passage.tags:
                continue
            overlap = len(query_grams & _bigrams(passage.text)) / len(query_grams)
            if overlap < self.MIN_LEXICAL_OVERLAP:
                continue
            boost = self.TAG_BOOST * len(wanted & set(passage.tags))
            scored.append(passage.model_copy(update={"score": round(overlap + boost, 4)}))

        # id is the tie-breaker so repeated runs (and therefore KPI scoring) are stable.
        scored.sort(key=lambda p: (-p.score, p.id))
        return scored[:top_k]


class ChromaRetriever:
    """Chroma + BGE-M3 embedding retriever — the S1-1~S1-2 replacement for
    `FixtureRetriever` (see `apps/ai-engine/scripts/build_index.py` for the indexing side).

    ⚠️ `chromadb`/`sentence_transformers` are only imported inside this class's methods,
    never at module level. This module sits on the core import path
    (service -> generation -> retrieval), and CI's required jobs install core + dev only
    — never the `rag` extra — so a top-level import here would break every test that
    merely imports `ai_engine.retrieval`.

    Indexed chunks currently carry no vulnerability tags (the source CSV has none), so
    `tags` only ever contains `disaster_type` — the boost below has nothing to boost until
    a vulnerability-tagged corpus exists. That is a data gap, not a bug in this class.
    """

    # `tags` boosts rather than hard-filters (same contract as FixtureRetriever), but
    # Chroma's `where` can only hard-filter. So `disaster_type` goes into `where` and we
    # over-fetch candidates to re-rank by tag overlap in Python, same as the lexical path.
    CANDIDATE_MULTIPLIER = 3
    TAG_BOOST = FixtureRetriever.TAG_BOOST

    def __init__(self, collection: Any, model: Any) -> None:
        self._collection = collection
        self._model = model

    @classmethod
    def from_persist_dir(
        cls,
        path: str | Path | None = None,
        *,
        collection_name: str = "action_manual",
        model_name: str = "BAAI/bge-m3",
    ) -> ChromaRetriever:
        import chromadb
        from sentence_transformers import SentenceTransformer

        from ai_engine.config import get_settings

        persist_dir = str(path) if path is not None else get_settings().chroma_persist_dir
        client = chromadb.PersistentClient(path=persist_dir)
        # hnsw:space="cosine": only applies if this call creates the collection (Chroma's
        # default is "l2", which `search()`'s `1 - distance` would misinterpret). The usual
        # path is build_index.py creating it first with the same setting; this covers the
        # case where a query runs against a not-yet-indexed, freshly created collection.
        collection = client.get_or_create_collection(
            collection_name, metadata={"hnsw:space": "cosine"}
        )
        return cls(collection, SentenceTransformer(model_name))

    def search(
        self,
        query: str,
        *,
        disaster_type: DisasterType,
        tags: list[str],
        top_k: int,
    ) -> list[Passage]:
        # normalize_embeddings=True: matches build_index.py — cosine similarity is only
        # well-defined for unit vectors, and the "flood" indexed collection assumes it.
        query_embedding = self._model.encode(query, normalize_embeddings=True).tolist()
        result = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * self.CANDIDATE_MULTIPLIER,
            where={"disaster_type": disaster_type},
        )
        ids = result["ids"][0]
        if not ids:
            return []

        wanted = set(tags)
        scored: list[Passage] = []
        for id_, text, distance, metadata in zip(
            ids, result["documents"][0], result["distances"][0], result["metadatas"][0], strict=True
        ):
            passage_tags = [str(metadata["disaster_type"])]
            similarity = 1.0 - distance
            boost = self.TAG_BOOST * len(wanted & set(passage_tags))
            scored.append(
                Passage(
                    id=id_,
                    title=str(metadata.get("stage", "")),
                    text=text,
                    score=round(similarity + boost, 4),
                    tags=passage_tags,
                    url=metadata.get("url"),
                )
            )

        # Same tie-breaker as FixtureRetriever, for the same reproducibility reason.
        scored.sort(key=lambda p: (-p.score, p.id))
        return scored[:top_k]
