"""HttpAiEngineClient — ai-engine의 HTTP 응답을 백엔드 계약으로 옮기는 지점.

Convention: tests/ mirrors src/ (src/backend_core/ai_client.py ->
tests/backend_core/test_ai_client.py).

ADR-0006의 두 갈래를 여기서 고정한다. 정직한 거절(`message: null`)은 200이므로
`None`으로 내려오고, 도달 실패(timeout·연결 오류·5xx·응답 파손)는 모양과 무관하게
전부 `AiEngineUnavailableError`가 된다. 파이프라인은 두 경우를 같은 자리에서 승인
문안으로 바꾸므로(test_pipeline.py의 refusal·outage 테스트), 그 앞단인 이 변환이
어긋나면 위 두 테스트가 초록인 채로 실제 장애만 빠져나간다.

`httpx.post`를 모듈 속성째 바꿔 끼운다. respx·pytest-httpx는 dev 의존성에 없고,
제출 직전에 의존성을 늘리지 않기 위해 pytest 내장 monkeypatch만 쓴다.
"""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from backend_core.ai_client import AiEngineUnavailableError, HttpAiEngineClient
from backend_core.models import DisasterEvent, GenerationContext, ShelterList
from backend_core.pipeline import build_context
from backend_core.registry import ResidentRegistry

BASE_URL = "http://ai-engine.test"
EVENT_ID = "KMA-TEST-0001"

_REQUEST = httpx.Request("POST", f"{BASE_URL}/v1/generate")

GENERATED_BODY = "물이 차오르기 전에 관악구민종합체육관으로 이동하세요."
GENERATED_PAYLOAD = {
    "message": {
        "title": "[세이버스] 서원동 호우경보",
        "body": GENERATED_BODY,
        "messageMode": "grounded",
        "sources": [{"title": "[더미] 국민행동요령", "quote": "물이 차오르기 전에 이동합니다."}],
    }
}


def _responds(response: httpx.Response) -> Callable[..., httpx.Response]:
    def _post(url: str, **kwargs: Any) -> httpx.Response:
        return response

    return _post


def _fails(exc: Exception) -> Callable[..., httpx.Response]:
    def _post(url: str, **kwargs: Any) -> httpx.Response:
        raise exc

    return _post


def _records(
    response: httpx.Response, calls: list[tuple[str, dict[str, Any]]]
) -> Callable[..., httpx.Response]:
    def _post(url: str, **kwargs: Any) -> httpx.Response:
        calls.append((url, kwargs))
        return response

    return _post


@pytest.fixture
def context(event: DisasterEvent, registry: ResidentRegistry) -> GenerationContext:
    """production 경로로 만든 컨텍스트.

    대피소 후보가 없어 shelter는 null로 직렬화된다. 중첩 Shelter의
    camelCase(distanceM, hasStairs) 직렬화는 이 fixture로는 태우지 않으며,
    그 커버는 shelter가 있는 컨텍스트로 후속에서 붙인다.
    """
    resident = registry.get("p001")
    assert resident is not None
    return build_context(
        event,
        resident.profile,
        ShelterList(hazard_match="inside", availability="ok", basis="dongCode"),
    )


def test_generated_message_is_mapped_onto_the_contract(
    monkeypatch: pytest.MonkeyPatch, context: GenerationContext
) -> None:
    """정상 응답의 camelCase(messageMode)가 계약 필드로 옮겨진다.

    응답 매핑과 함께 요청 쪽 계약도 고정한다. 경로, timeout, by_alias camelCase가
    실제로 나가는지를 단언한다. 스텁이 인자를 버리면 timeout 누락이나 별칭 누락이
    초록으로 지나가므로 여기서 호출을 기록해 확인한다.
    """
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        httpx,
        "post",
        _records(httpx.Response(200, json=GENERATED_PAYLOAD, request=_REQUEST), calls),
    )

    message = HttpAiEngineClient(BASE_URL).generate(EVENT_ID, context)

    assert message is not None
    assert message.message_mode == "grounded"
    assert message.body == GENERATED_BODY
    assert len(message.sources) == 1

    assert len(calls) == 1
    url, kwargs = calls[0]
    assert url == f"{BASE_URL}/v1/generate"
    assert kwargs["timeout"] == 8.0
    assert kwargs["json"]["eventId"] == EVENT_ID
    assert "serviceMode" in kwargs["json"]["context"]


def test_refusal_arrives_as_none_not_as_an_error(
    monkeypatch: pytest.MonkeyPatch, context: GenerationContext
) -> None:
    """거절은 200이다 — 못 만든 게 아니라 안 만든 것이므로 장애로 승격시키지 않는다."""
    refusal = {"message": None, "refusalReason": "no_evidence"}
    monkeypatch.setattr(
        httpx, "post", _responds(httpx.Response(200, json=refusal, request=_REQUEST))
    )

    assert HttpAiEngineClient(BASE_URL).generate(EVENT_ID, context) is None


@pytest.mark.parametrize(
    "post",
    [
        pytest.param(
            _fails(httpx.TimeoutException("read timeout", request=_REQUEST)), id="timeout"
        ),
        pytest.param(
            _fails(httpx.ConnectError("connection refused", request=_REQUEST)), id="connect-error"
        ),
        pytest.param(
            _responds(httpx.Response(503, json={"detail": "unusable"}, request=_REQUEST)), id="503"
        ),
        pytest.param(
            _responds(httpx.Response(200, content=b"<html>502</html>", request=_REQUEST)),
            id="broken-json",
        ),
    ],
)
def test_every_unreachable_shape_narrows_to_one_error(
    monkeypatch: pytest.MonkeyPatch,
    context: GenerationContext,
    post: Callable[..., httpx.Response],
) -> None:
    """도달 실패는 모양이 달라도 예외 하나로 좁혀진다.

    pipeline._generate가 잡는 예외는 AiEngineUnavailableError 하나뿐이다. 여기서
    새는 종류가 하나라도 있으면 run_alert의 수신자 루프 밖으로 올라가고, 그러면
    그 사람만이 아니라 뒤에 줄 선 수신자 전원의 알림이 조용히 사라진다
    (pipeline.py 모듈 docstring의 "No step can abort the run").
    """
    monkeypatch.setattr(httpx, "post", post)

    with pytest.raises(AiEngineUnavailableError):
        HttpAiEngineClient(BASE_URL).generate(EVENT_ID, context)


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param([], id="list-body"),
        pytest.param(
            {"message": {"body": "b", "messageMode": "grounded", "sources": []}},
            id="missing-title",
        ),
        pytest.param(
            {"message": {"title": "t", "body": "b", "messageMode": "bogus", "sources": []}},
            id="bogus-message-mode",
        ),
        pytest.param(
            {
                "message": {
                    "title": "t",
                    "body": "b",
                    "messageMode": "grounded",
                    "sources": [{"title": "[더미] 국민행동요령"}],
                }
            },
            id="source-missing-quote",
        ),
    ],
)
def test_every_malformed_200_narrows_to_one_error(
    monkeypatch: pytest.MonkeyPatch,
    context: GenerationContext,
    payload: Any,
) -> None:
    """200인데 스키마가 어긋난 응답도 도달 실패와 같은 예외로 좁혀진다.

    _post는 전송·JSON 파싱 실패만 잡는다. 응답 파싱(data.get, message["title"],
    AlertMessage(...), Source.model_validate(...))은 generate() 본문에 있어,
    가드가 없으면 AttributeError·KeyError·ValidationError가 그대로 새어
    run_alert 수신자 루프 밖으로 올라간다. 도달 실패 쪽 계약과 같은 것을
    스키마 불일치 쪽에서도 고정한다.
    """
    monkeypatch.setattr(
        httpx, "post", _responds(httpx.Response(200, json=payload, request=_REQUEST))
    )
    with pytest.raises(AiEngineUnavailableError):
        HttpAiEngineClient(BASE_URL).generate(EVENT_ID, context)
