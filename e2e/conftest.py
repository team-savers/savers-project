"""Shared fixtures for the cross-app E2E harness.

The harness talks to running services over HTTP only — never import `api`,
`backend_core` or `ai_engine` here (app-boundary rule, see e2e/README.md).
"""

import os

import httpx
import pytest
from seed_data import WORST_CASE_USER_ID

BASE_URL_ENV = "SAVERS_E2E_BASE_URL"
# ⚠️ 백엔드를 설정하는 것과 **같은 이름**입니다. 이름을 따로 두면(예: SAVERS_E2E_SESSION_TTL_S)
#    워크플로에서 한쪽만 고쳐졌을 때 조용히 어긋납니다 — 백엔드만 0이면 만료 테스트가 영구
#    skip 되고, 마커만 켜지면 정상 TTL 스택에서 410을 기다리다 실패합니다. 같은 이름이라
#    로컬에서 짧은 TTL 백엔드를 띄울 때도(docs/공통_가이드/워킹_스켈레톤_점검.md §14-2)
#    별도 설정 없이 켜집니다.
SESSION_TTL_ENV = "SAVERS_SESSION_TTL_S"


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


@pytest.fixture(scope="session")
def zero_ttl_backend() -> None:
    """만료 테스트가 돌 수 있는 스택인지 확인한다 — 아니면 실패가 아니라 skip.

    세션 TTL은 프로세스 전역 싱글턴(`api/deps.py`의 `lru_cache`)이라 **테스트별로 다르게
    줄 수 없다.** 그래서 만료를 만드는 유일한 HTTP-전용 수단은 "TTL을 0으로 준 backend를
    따로 돌리는 것"이고, E2E 워크플로가 패스를 둘로 나눠 그걸 한다:

        1차: 정상 TTL(21600) 스택에서  pytest -m "not expiry"
        2차: backend만 TTL=0으로 재생성 후  pytest -m expiry

    TTL=0을 쓰는 이유는 `sleep`이 필요 없다는 것이다. `expires_at`이 발송 루프 진입 시각
    기준으로 계산되므로(`backend_core/pipeline.py`) **짧은 양수 TTL은 발송 소요시간에
    먹힌다** — ai-engine이 느리면 토큰이 발급된 순간 이미 만료돼, 같은 스택의 다른
    테스트가 "세션 만료 버그"처럼 보이는 410으로 무너진다. TTL=0은 그 결합을 없앤다.

    ⚠️ 이 가드가 없으면 정상 스택에 그냥 `pytest`를 돌린 사람이 이유를 알 수 없는 실패를
    본다(200을 받고 410을 기다림). skip 사유를 섞지 않으려고 base_url에 의존하지 않는다 —
    스택 자체가 없을 때는 `client`가 요청하는 `base_url`의 skip이 먼저 걸린다.
    """
    raw = os.environ.get(SESSION_TTL_ENV)
    if raw is None:
        pytest.skip(
            f"{SESSION_TTL_ENV} 미설정 — 만료 검증은 TTL=0으로 재생성한 backend에서만 "
            "돕니다(E2E 워크플로의 만료 전용 패스)"
        )
    try:
        ttl = int(raw)
    except ValueError:
        pytest.skip(f"{SESSION_TTL_ENV}={raw!r} 를 정수로 읽을 수 없습니다")
    if ttl != 0:
        pytest.skip(
            f"{SESSION_TTL_ENV}={ttl} — 만료 검증은 0에서만 결정론적입니다. "
            "양수 TTL이면 대기 시간이 발송 소요시간과 경쟁합니다"
        )


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
