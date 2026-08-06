"""Shared fixtures for the cross-app E2E harness.

The harness talks to running services over HTTP only — never import `api`,
`backend_core` or `ai_engine` here (app-boundary rule, see e2e/README.md).
"""

import os

import httpx
import pytest

BASE_URL_ENV = "SAVERS_E2E_BASE_URL"

# 시드 데이터에 대한 유일한 참조점. backend_core/registry.py의 seed_registry·DEMO_DONG_CODE와
# 짝이지만, HTTP 전용 규약 때문에 import할 수 없어 값을 여기 한 번만 적어 둔다. 시드가 바뀌면
# 고칠 곳은 이 두 상수뿐 — 테스트 파일마다 복사해 두면 한쪽만 고쳐진 채 "매칭 실패"로만
# 보이는 실패가 남고, 원인이 시드 변경이라는 걸 알기 어렵다.
#
# p001 = 김순자. stairs_ok=False + 보호자 등록 — 가장 취약한 프로필이면서 보호자 연결까지
# 가진 유일한 시드 주민이라 정상 경로와 최악 경로 양쪽의 대상이다.
WORST_CASE_USER_ID = "p001"
# 데모 특보가 덮는 시드 행정동(서원동). 대피소 픽스처가 존재하는 유일한 행정동이다.
SEED_DONG_CODE = "1162064500"


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
