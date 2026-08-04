"""대피소 침수 안전등급 PU-learning 파이프라인.

P(긍정) = 수해대피소(TL_FLOOD_P) 중 CD_GUBUN="안전"만. U(무라벨) = 건축물대장 전체(P
제외). Spy 기법으로 U 중 신뢰 가능한 negative를 걸러낸다 — 설계 배경은
`spy.py` 모듈 docstring 참고.

`ai_engine`의 다른 서브모듈(retrieval/generation 등, parsing -> chunking ->
embedding -> retrieval -> generation 단방향 파이프라인)과 별개의 오프라인 배치
파이프라인이라 그 규칙의 적용 대상이 아니다. `ai_engine/__init__.py`는 이 패키지를
임포트하지 않으므로, `pandas`/`scikit-learn`/`lightgbm`(`ml` extra)이 없어도
나머지 ai_engine은 그대로 동작한다.
"""
