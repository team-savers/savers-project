"""보호자 1차 정보성 통지 — 고정 문구.

ADR-0015 결정 2: 1차 재난 알림은 `ward` 행동 지시와 `guardian` 정보성 통지로 갈린다.
보호자 통지는 지역·특보 종류·피보호자 이름을 끼운 **시스템 통지문**이며, 피보호자 문안과
달리 생성 계약(ADR-0006)을 타지 않는다 — 그래서 `AlertMessage`·`message_mode`를 재사용하지
않는다. `message_mode`를 달고 다니면 생성물이 아닌 문장이 생성 지표 쪽 어휘를 물고 들어간다.

⚠️ 문안·필드는 이슈 #218(PM 확정) 원문 그대로다. 임의로 바꾸지 않는다(링크 경로만 아래
함수에서 최신 Frontend·OpenAPI 계약 형식에 맞춘다):

- 한국어 고정. `Guardian` 스키마에 로케일 필드가 없고, 방향은 ADR-0021(보호자 Q&A 한국어 전용)과 같다.
- 30분/30초 같은 숫자를 넣지 않는다 — 시연 플래그가 30분을 30초로 줄이므로 본문에 박으면 어긋난다.
- 후속 통지를 약속하지 않는다 — 성공 경로에서는 2차 발송이 아예 없다(ADR-0015, 재난 1건당 1회).
- 안전 판단·금칙어(「안전합니다」·「괜찮습니다」)를 넣지 않는다 — 보호자가 자기에게 내려온
  대피 지시로 오독하지 않도록 둘째 문장이 상황 공유임을 못 박는다.
- 「대피 안내」가 아니라 「안내 메시지」다 — 단계 1(상황 주시)에서도 참인 표현만 쓴다.

`alert_label`은 `pipeline.alert_label(event)` 결과를 그대로 받는다 — 새 라벨 표를 만들지 않는다.
"""

from __future__ import annotations

from backend_core.dispatch import PushPayload

# 상황 공유임을 못 박는 고정 둘째 문장. 첫 문장에만 슬롯이 들어간다.
_GUARDIAN_NOTICE_TAIL = "이 알림은 상황 공유이며 보호자님에 대한 대피 지시가 아닙니다."


def guardian_notice_title(ward_name: str, alert_label: str) -> str:
    return f"[세이버스] {ward_name}님께 안내 발송 - {alert_label}"


def guardian_notice_body(dong_name: str, ward_name: str, alert_label: str) -> str:
    return (
        f"{dong_name}에 {alert_label}가 발효되어 {ward_name}님께 안내 메시지를 보냈습니다. "
        f"{_GUARDIAN_NOTICE_TAIL}"
    )


def guardian_notice_link(public_base_url: str, guardian_token: str) -> str:
    """보호자 딥링크. 최신 Frontend·OpenAPI 계약의 경로 형식 `{public_base_url}/g/{guardian_token}` 이다.

    이전 초안의 쿼리 형식 `/g?t=` 를 대체한다 — 프론트 `/g/:token` 라우트와 OpenAPI 계약이
    보호자 토큰을 경로 파라미터로 확정했고, 폐루프 2차 발송(`closed_loop`)도 이미 같은 `/g/` 를
    쓴다. 제목·본문(문안)은 이슈 #218 확정 그대로이며, 여기서 바꾸는 것은 링크 경로뿐이다.

    `rstrip("/")` 는 ward 딥링크(`deep_link`)와 같은 정규화다 — trailing slash 가 붙은
    `public_base_url` 에서 `//g/` (protocol-relative URL 로 오독될 수 있는 형태)가 나오는 것을
    막는다. 경로가 붙은 base URL(`http://x/app`)이면 그 경로 뒤에 `/g/{guardian_token}` 이 붙는다.
    """
    return f"{public_base_url.rstrip('/')}/g/{guardian_token}"


def guardian_notice_payload(
    device_token: str,
    *,
    ward_name: str,
    dong_name: str,
    alert_label: str,
    public_base_url: str,
    guardian_token: str,
) -> PushPayload:
    """One guardian first-notice push. Same `PushPayload` shape as the ward path, but the
    body is a fixed system notice, never a generated `AlertMessage`."""
    return PushPayload(
        device_token=device_token,
        title=guardian_notice_title(ward_name, alert_label),
        body=guardian_notice_body(dong_name, ward_name, alert_label),
        link=guardian_notice_link(public_base_url, guardian_token),
    )
