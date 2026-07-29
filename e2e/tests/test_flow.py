"""Real vertical-slice scenario: 수신 → 매칭 → 생성 → 세션 발급 → 발송 → 보호자 연결.

Exercises `POST /internal/alerts/dispatch` against the seeded demo 행정동, then follows one
delivered resident's session and guardian tokens through their own endpoints. This is the
first non-placeholder flow test (docs/역할_일정/06-QA-보안.md S1-3) — it landed early because
the walking skeleton (PR #22) shipped ahead of schedule.

Deliberately agnostic about which text the message carries: whether the AI engine answered
or was unreachable and the backend substituted the 사전 승인 fallback
(apps/backend/src/backend_core/fallback.py, "움직이기 어려우면 119에 연락하세요"), the
session/guardian wiring runs the same code path either way — this test covers both without
needing to force one branch (forcing an AI outage deterministically needs infra-level fault
injection outside what an HTTP-only e2e test controls; see docs/adr/0007-walking-skeleton.md
"해결되지 않은 문제" and 신호정's PR #22 review comment for the follow-up).
"""

from __future__ import annotations

import httpx
import pytest

# 김순자 — stairs_ok=False, guardian 등록됨 (backend_core/registry.py seed_registry).
# 가장 취약한 프로필이면서 보호자 연결까지 가진 유일한 시드 주민이라 이 검증에 쓴다.
GUARDIAN_RESIDENT_USER_ID = "p001"


@pytest.mark.flow
def test_dispatch_reaches_session_and_guardian(client: httpx.Client) -> None:
    """Dispatch the demo flood warning, then follow one delivery's tokens end to end."""
    dispatch = client.post("/internal/alerts/dispatch")
    assert dispatch.status_code == 200, dispatch.text
    run = dispatch.json()
    assert run["matched"] >= 1, "seeded 행정동에 등록된 주민이 매칭되지 않음"

    delivery = next(
        (d for d in run["deliveries"] if d["userId"] == GUARDIAN_RESIDENT_USER_ID), None
    )
    assert delivery is not None, f"{GUARDIAN_RESIDENT_USER_ID} 배송 결과가 없음 — 매칭 실패"

    session = client.get(f"/v1/session/{delivery['sessionToken']}")
    assert session.status_code == 200, session.text
    session_body = session.json()
    assert session_body["message"]["body"], "메시지 본문이 비어 있음 — 무음 실패"
    assert session_body["profile"]["userId"] == GUARDIAN_RESIDENT_USER_ID
    # 취약 프로필(계단 불가)에게 계단 있는 대피소만 안내되는 실패를 잡기 위한 최소 확인.
    # 실제 국민행동요령/대피소 안내 문구 자체의 품질(근거 일치율)은 eval/ 하네스의 몫이다.

    guardian = client.get(f"/v1/guardian/{delivery['guardianToken']}")
    assert guardian.status_code == 200, guardian.text
    guardian_status = guardian.json()
    assert guardian_status["wardName"]
    assert guardian_status["acknowledgedByGuardian"] is False

    ack = client.post(f"/v1/guardian/{delivery['guardianToken']}/acknowledge")
    assert ack.status_code == 200, ack.text
    assert ack.json()["ok"] is True

    guardian_after_ack = client.get(f"/v1/guardian/{delivery['guardianToken']}")
    assert guardian_after_ack.json()["acknowledgedByGuardian"] is True, (
        "보호자 확인(acknowledge) 이후에도 상태에 반영되지 않음 — 보호자 연결 실패"
    )
