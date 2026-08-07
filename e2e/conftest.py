"""Shared fixtures for the cross-app E2E harness.

The harness talks to running services over HTTP only — never import `api`,
`backend_core` or `ai_engine` here (app-boundary rule, see e2e/README.md).
"""

import os

import httpx
import pytest
from seed_data import WORST_CASE_USER_ID

BASE_URL_ENV = "SAVERS_E2E_BASE_URL"


@pytest.fixture(scope="session")
def base_url() -> str:
    """Backend entry point under test.

    Skips the whole harness when unset so that "wired up but no stack yet" stays
    green in CI — the workflow flips to real verification the moment
    infra/docker-compose.yml can bring the stack up.
    """
    url = os.environ.get(BASE_URL_ENV)
    if not url:
        pytest.skip(f"{BASE_URL_ENV} 미설정 — 스택이 기동된 환경에서만 실행됩니다")
    return url.rstrip("/")


@pytest.fixture(scope="session")
def client(base_url: str):
    """Session-scoped HTTP client.

    Timeout is deliberate: the 알림 도달 속도 KPI budget is 30s end-to-end, so a
    hung request must fail the test rather than stall the job.
    """
    with httpx.Client(base_url=base_url, timeout=30.0) as c:
        yield c


@pytest.fixture
def worst_case_delivery(client: httpx.Client) -> dict:
    """데모 특보를 발송하고 p001의 배송 결과를 돌려준다.

    함수 스코프인 것은 의도다 — 발송마다 새 세션/보호자 토큰이 나오므로, 앞선
    테스트가 acknowledge한 상태가 다음 테스트로 새지 않는다.
    """
    dispatch = client.post("/internal/alerts/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    run = dispatch.json()
    assert run["matched"] >= 1, "seeded 행정동에 등록된 주민이 매칭되지 않음"

    delivery = next((d for d in run["deliveries"] if d["userId"] == WORST_CASE_USER_ID), None)
    assert delivery is not None, (
        f"{WORST_CASE_USER_ID} 배송 결과가 없음 — 매칭 실패 "
        "(registry.py 시드가 바뀌었다면 이 파일의 상수를 함께 고칠 것)"
    )
    return delivery
