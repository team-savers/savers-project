"""Placeholder harness test — proves the E2E wiring itself works.

Replace/extend in S1-3 with the real 관통 시나리오 (등록→감지→매칭→위치→생성→발송)
and the failure modes (API 장애 · 위치 권한 거부 · 가드레일 이탈).
Keep this file's contract: reach services over HTTP, never import app packages.
"""

import httpx
import pytest


@pytest.mark.flow
def test_backend_is_reachable(client: httpx.Client) -> None:
    """Smallest possible end-to-end assertion: the stack is up and answering.

    Everything downstream (matching, generation, dispatch) depends on this, so a
    failure here should be read as "the stack did not come up", not as a feature bug.
    """
    response = client.get("/health")
    assert response.status_code == 200, response.text
    assert response.json().get("status") == "ok"
