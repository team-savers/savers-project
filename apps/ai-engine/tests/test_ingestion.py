"""국민행동요령 API ingestion.

All HTTP is mocked via `httpx.MockTransport` — no real network call, per AGENTS.md ("External
API calls in tests must be mocked").

Convention: tests/ mirrors src/ (src/ai_engine/ingestion.py -> tests/test_ingestion.py).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ai_engine.ingestion import ActionManualApiError, fetch_action_manual_rows

_FAKE_API_KEY = "not-a-real-key-just-for-this-test"

_OK_HEADER = {"resultMsg": "NORMAL SERVICE", "resultCode": "00", "errorMsg": None}


def _item(safety_cate2: str, act_rmks: str, **overrides: Any) -> dict[str, Any]:
    base = {
        "safety_cate_nm2": safety_cate2,
        "actRmks": act_rmks,
        "safety_cate_nm3": "호우 특보 중 행동요령",
        "safety_cate4": None,
        "safety_cate3": "01003002",
        "safety_cate2": "01003",
        "safety_cate1": "01",
        "contentsUrl": None,
        "safety_cate_nm1": "자연재난",
    }
    base.update(overrides)
    return base


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_normalizes_null_fields_to_empty_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "header": _OK_HEADER,
                "numOfRows": 100,
                "pageNo": 1,
                "totalCount": 1,
                "body": [_item("호우", "- 지침 문장")],
            },
        )

    rows = fetch_action_manual_rows(
        "key", safety_cate="01003", client=_client(handler), sleep_between_pages_s=0
    )
    assert rows == [
        {
            "actRmks": "- 지침 문장",
            "contentsUrl": "",
            "safety_cate1": "01",
            "safety_cate2": "01003",
            "safety_cate3": "01003002",
            "safety_cate4": "",
            "safety_cate_nm1": "자연재난",
            "safety_cate_nm2": "호우",
            "safety_cate_nm3": "호우 특보 중 행동요령",
        }
    ]


def test_paginates_until_total_count_reached() -> None:
    pages_requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_no = int(request.url.params["pageNo"])
        pages_requested.append(page_no)
        # totalCount=3, numOfRows=2 -> page 1 has 2 rows, page 2 has 1 row.
        body = [_item("호우", f"- 지침 {page_no}-{i}") for i in range(2 if page_no == 1 else 1)]
        return httpx.Response(
            200,
            json={
                "header": _OK_HEADER,
                "numOfRows": 2,
                "pageNo": page_no,
                "totalCount": 3,
                "body": body,
            },
        )

    rows = fetch_action_manual_rows(
        "key",
        safety_cate="01003",
        page_size=2,
        client=_client(handler),
        sleep_between_pages_s=0,
    )
    assert pages_requested == [1, 2]
    assert len(rows) == 3


def test_multiple_safety_cate_codes_are_concatenated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        code = request.url.params["safety_cate"]
        label = {"01002": "홍수", "01003": "호우"}[code]
        return httpx.Response(
            200,
            json={
                "header": _OK_HEADER,
                "numOfRows": 100,
                "pageNo": 1,
                "totalCount": 1,
                "body": [_item(label, f"- {label} 지침")],
            },
        )

    rows = fetch_action_manual_rows(
        "key",
        safety_cate=["01003", "01002"],
        client=_client(handler),
        sleep_between_pages_s=0,
    )
    assert {r["safety_cate_nm2"] for r in rows} == {"호우", "홍수"}


def test_omitting_safety_cate_does_not_send_the_param() -> None:
    """생략 시 API가 조용히 태풍으로 스코프를 좁히는 함정을 문서화하는 회귀 테스트 —
    적어도 우리 쪽 요청에 safety_cate를 실수로 끼워넣지 않는지는 검증한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "safety_cate" not in request.url.params
        return httpx.Response(
            200,
            json={
                "header": _OK_HEADER,
                "numOfRows": 100,
                "pageNo": 1,
                "totalCount": 1,
                "body": [_item("태풍", "- 태풍 지침")],
            },
        )

    rows = fetch_action_manual_rows("key", client=_client(handler), sleep_between_pages_s=0)
    assert rows[0]["safety_cate_nm2"] == "태풍"


def test_non_zero_result_code_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "header": {
                    "resultMsg": "UNREGISTERED IP ERROR",
                    "resultCode": "32",
                    "errorMsg": "등록되지 않은 IP",
                },
                "body": None,
            },
        )

    with pytest.raises(ActionManualApiError, match="32"):
        fetch_action_manual_rows(
            "key", safety_cate="01003", client=_client(handler), sleep_between_pages_s=0
        )


def test_stops_when_body_is_empty_even_if_total_count_not_reached() -> None:
    """totalCount가 실제보다 크게 잘못 와도, 빈 body를 받으면 더 돌지 않고 멈춰야 한다."""
    pages_requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page_no = int(request.url.params["pageNo"])
        pages_requested.append(page_no)
        # totalCount는 100이라고 우기지만, 2페이지째부터 실제로는 줄 게 없다.
        body = [_item("호우", "- 지침")] if page_no == 1 else []
        return httpx.Response(
            200,
            json={
                "header": _OK_HEADER,
                "numOfRows": 1,
                "pageNo": page_no,
                "totalCount": 100,
                "body": body,
            },
        )

    rows = fetch_action_manual_rows(
        "key", safety_cate="01003", page_size=1, client=_client(handler), sleep_between_pages_s=0
    )
    assert pages_requested == [1, 2]
    assert len(rows) == 1


def test_raises_when_max_pages_exceeded() -> None:
    """서버가 계속 (빈 아닌) 페이지를 주는데 totalCount에 영영 못 미치면, 무한 루프 대신
    max_pages에서 명시적으로 실패해야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        page_no = int(request.url.params["pageNo"])
        return httpx.Response(
            200,
            json={
                "header": _OK_HEADER,
                "numOfRows": 1,
                "pageNo": page_no,
                "totalCount": 1_000_000,  # 절대 못 채우는 값
                "body": [_item("호우", f"- 지침 {page_no}")],
            },
        )

    with pytest.raises(ActionManualApiError, match="max_pages"):
        fetch_action_manual_rows(
            "key",
            safety_cate="01003",
            page_size=1,
            client=_client(handler),
            sleep_between_pages_s=0,
            max_pages=3,
        )


def test_http_error_message_does_not_leak_the_api_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with pytest.raises(ActionManualApiError) as exc_info:
        fetch_action_manual_rows(
            _FAKE_API_KEY,
            safety_cate="01003",
            client=_client(handler),
            sleep_between_pages_s=0,
        )
    assert _FAKE_API_KEY not in str(exc_info.value)
    assert "REDACTED" in str(exc_info.value)
