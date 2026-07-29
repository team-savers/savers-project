"""Retrieval behaviour that the rest of the pipeline depends on.

Retrieval has no endpoint by design (ADR-0006: it is a stage inside the one-way pipeline),
so these tests reach it as a module — which is also how the eval harness will.

Convention: tests/ mirrors src/ (src/ai_engine/retrieval.py -> tests/test_retrieval.py).
"""

from ai_engine.models import RecipientContext
from ai_engine.retrieval import FixtureRetriever, build_query, profile_tags


def test_disaster_type_is_a_hard_filter(
    retriever: FixtureRetriever, foreign_worker: RecipientContext
) -> None:
    """다른 재난의 지침을 인용하면 '근거는 있는데 상황이 틀린' 오답이 된다."""
    passages = retriever.search(
        build_query("flood", foreign_worker), disaster_type="flood", tags=[], top_k=10
    )
    assert passages
    assert all("flood" in p.tags for p in passages)


def test_unrelated_question_retrieves_nothing(
    retriever: FixtureRetriever, banjiha_elder: RecipientContext
) -> None:
    """Out-of-scope 입력은 태그 보너스로 떠오르면 안 된다.

    이게 무너지면 챗봇이 아무 질문에나 '같은 태그를 가진' 문단으로 답하게 되고,
    무응답률이 구조적으로 0이 된다.
    """
    passages = retriever.search(
        "주식 시장 전망 알려줘",
        disaster_type="flood",
        tags=profile_tags(banjiha_elder),
        top_k=4,
    )
    assert passages == []


def test_profile_tags_boost_relevant_passages(
    retriever: FixtureRetriever, banjiha_elder: RecipientContext
) -> None:
    """조건부 검색: 같은 질의라도 취약성에 따라 순위가 달라진다."""
    query = build_query("flood", banjiha_elder)
    with_profile = retriever.search(
        query, disaster_type="flood", tags=profile_tags(banjiha_elder), top_k=3
    )
    without_profile = retriever.search(query, disaster_type="flood", tags=[], top_k=3)
    assert with_profile[0].score > without_profile[0].score


def test_profile_tags_do_not_hard_filter(
    retriever: FixtureRetriever, foreign_worker: RecipientContext
) -> None:
    """태그가 하나도 안 붙는 프로필도 일반 지침은 회수돼야 한다.

    취약성으로 하드 필터를 걸면 태그가 덜 붙은 프로필이 전부 폴백으로 떨어진다.
    """
    assert profile_tags(foreign_worker) == []
    assert retriever.search(
        build_query("flood", foreign_worker), disaster_type="flood", tags=[], top_k=4
    )


def test_screen_only_attributes_do_not_affect_retrieval(
    retriever: FixtureRetriever, banjiha_elder: RecipientContext
) -> None:
    """vision·hearing은 애초에 계약에 없다 — 검색 조건도 그것 없이 성립해야 한다."""
    tags = profile_tags(banjiha_elder)
    assert tags == ["banjiha", "mobility_assisted", "stairs", "lives_alone"]


def test_ordering_is_deterministic(
    retriever: FixtureRetriever, banjiha_elder: RecipientContext
) -> None:
    """동일 입력이 동일 순서를 내야 지표 채점이 재현 가능하다."""
    query = build_query("flood", banjiha_elder)
    tags = profile_tags(banjiha_elder)
    first = retriever.search(query, disaster_type="flood", tags=tags, top_k=5)
    second = retriever.search(query, disaster_type="flood", tags=tags, top_k=5)
    assert [p.id for p in first] == [p.id for p in second]


def test_passage_text_is_verbatim_source(retriever: FixtureRetriever) -> None:
    """`text`는 회수된 원문 그대로 — 근거 일치율 채점의 기준선."""
    passages = retriever.search("지하 공간 대피", disaster_type="flood", tags=[], top_k=1)
    assert passages
    corpus = {p.id: p.text for p in retriever.passages}
    assert passages[0].text == corpus[passages[0].id]
