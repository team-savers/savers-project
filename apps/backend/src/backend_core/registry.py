"""Registered residents and their push devices.

Registration is done *for* the person by a guardian, 복지관 or 지자체 — the vulnerable user
never installs or configures anything (zero-install hard constraint). That is why there is
no signup/profile-edit path here: residents arrive already registered, and the only write
operation exposed to the public API is attaching or detaching a device token.

⚠️ P1 storage is an in-memory dict. When this becomes a real store, sensitive fields
(장애·건강 관련 항목, 보호자 연락처) must be encrypted at rest — the minimal-collection
constraint covers storage, not just collection.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend_core.models import DeviceRole, Guardian, Profile


class RegistrationNotFoundError(LookupError):
    """No resident holds this registration token."""


class GuardianNotRegisteredError(ValueError):
    """A guardian device was posted for a ward whose profile has no guardian.

    2차 발송은 guardian 기기에만 나가는데(ADR-0015 결정 2), 애초에 보호자가 없는 대상에게
    guardian 토큰을 붙이면 아무 데도 도달하지 않는 기기가 조용히 쌓인다 — 등록 시점에 막는다
    (ADR-0015 결정 3).
    """


def _empty_devices() -> dict[DeviceRole, list[str]]:
    # 두 역할 버킷을 항상 초기화한다(ADR-0015 결정 1, 안 A). 발송·조회 경로가 키 존재를
    # 검사하지 않고 바로 읽을 수 있게 하기 위해서다.
    return {"ward": [], "guardian": []}


@dataclass
class Resident:
    """A registered person plus the devices that can reach them.

    `registration_token` is long-lived and one-per-person; it is what a proxy registrar
    holds. It is deliberately *not* the session token — session tokens are minted at
    dispatch time, so requiring one to register a device would mean needing a push before
    you could receive a push (the circular dependency ADR-0005 flagged).

    `devices` is keyed by role: 1차 재난 알림은 `ward` 기기에만, 2차 발송은 `guardian`
    기기에만 나간다(ADR-0015 결정 2). 같은 토큰이 두 역할에 모두 등록될 수 있고, 해제는
    양쪽에서 뗀다.
    """

    profile: Profile
    registration_token: str
    devices: dict[DeviceRole, list[str]] = field(default_factory=_empty_devices)


class ResidentRegistry:
    """In-memory resident store, indexed the two ways the flow actually reads it."""

    def __init__(self, residents: list[Resident] | None = None) -> None:
        self._by_user: dict[str, Resident] = {}
        self._by_registration: dict[str, Resident] = {}
        for resident in residents or []:
            self.add(resident)

    def add(self, resident: Resident) -> None:
        self._by_user[resident.profile.user_id] = resident
        self._by_registration[resident.registration_token] = resident

    def get(self, user_id: str) -> Resident | None:
        return self._by_user.get(user_id)

    def by_registration_token(self, token: str) -> Resident:
        try:
            return self._by_registration[token]
        except KeyError as exc:
            raise RegistrationNotFoundError(token) from exc

    def by_dong_codes(self, dong_codes: list[str]) -> list[Resident]:
        """Alert targeting. Registered 행정동 only — never a live location.

        Matching on the registered district is what lets the service select recipients
        without tracking anyone: location is read once, later, in the recipient's browser.
        """
        wanted = set(dong_codes)
        return [r for r in self._by_user.values() if r.profile.dong_code in wanted]

    def register_device(
        self, registration_token: str, fcm_token: str, role: DeviceRole
    ) -> Resident:
        """Attach a device under one role. Idempotent per role — re-posting the same token
        to the same role is a no-op. The same token may hold both roles (a shared handset
        that is both the ward's and the guardian's phone); this appends only to `role`.
        """
        resident = self.by_registration_token(registration_token)
        if role == "guardian" and resident.profile.guardian is None:
            raise GuardianNotRegisteredError(registration_token)
        bucket = resident.devices[role]
        if fcm_token not in bucket:
            bucket.append(fcm_token)
        return resident

    def unregister_device(self, registration_token: str, fcm_token: str) -> Resident:
        """Detach a device from *every* role. Idempotent — an already-absent token is still
        a success.

        The unregister contract carries no role (`DeviceUnregisterRequest`): an FCM token is
        unique per device, so it identifies the target without one, and "gone from any role"
        is the whole point. Lost/replaced handsets, shared 복지관 terminals and withdrawn
        consent all end here; making the caller distinguish "removed" from "was not there"
        adds no information and invites retry loops.
        """
        resident = self.by_registration_token(registration_token)
        for bucket in resident.devices.values():
            if fcm_token in bucket:
                bucket.remove(fcm_token)
        return resident

    def register_guardian_device_by_user(self, user_id: str, fcm_token: str) -> Resident:
        """Attach a guardian device addressed by the ward's `user_id`, not a registration token.

        The guardian device route authenticates with a guardian *session* token, which resolves
        to a `user_id` — the registrar-held registration token never reaches it. Registration
        still lands on the persistent Resident, so it outlives the session token that carried it
        and feeds the next alert's 2차 발송(계약 `/v1/guardian/{token}/device`). Idempotent on
        the guardian bucket; raises `GuardianNotRegisteredError` when the ward has no guardian at
        all, since a guardian device would then reach nobody(ADR-0015 결정 3).
        """
        resident = self.get(user_id)
        if resident is None:
            raise RegistrationNotFoundError(user_id)
        if resident.profile.guardian is None:
            raise GuardianNotRegisteredError(user_id)
        # 직접 인덱싱한다 — `devices_for`는 `.get(role, [])`로 새 리스트를 돌려줄 수 있어
        # 거기에 append하면 등록이 사라진다. `_empty_devices`가 guardian 버킷을 항상 만든다.
        bucket = resident.devices["guardian"]
        if fcm_token not in bucket:
            bucket.append(fcm_token)
        return resident

    def unregister_guardian_device_by_user(self, user_id: str, fcm_token: str) -> Resident:
        """Detach a guardian device by `user_id`. Idempotent — an already-absent token still
        succeeds, same contract as `unregister_device`(기기 교체·공용 단말·동의 철회)."""
        resident = self.get(user_id)
        if resident is None:
            raise RegistrationNotFoundError(user_id)
        bucket = resident.devices["guardian"]
        if fcm_token in bucket:
            bucket.remove(fcm_token)
        return resident

    @staticmethod
    def devices_for(resident: Resident, role: DeviceRole) -> list[str]:
        """The tokens registered under one role — 1차 발송은 `ward`, 2차 발송은 `guardian`.

        버킷이 누락된 Resident에도 `[]`로 안전 강등한다(직접 인덱싱 금지) — 발송 경로가
        KeyError 500 대신 skipped_no_device로 집계할 수 있게 한다.
        """
        return resident.devices.get(role, [])

    def __len__(self) -> int:
        return len(self._by_user)


# ── Demo seed ────────────────────────────────────────────────────────────────────
# 킬러 데모 페르소나 2종(S2-E1): 반지하 고령자 + 외국인 근로자. Fictional people with
# fictional tokens — readable on purpose so nobody mistakes them for real credentials.

DEMO_DONG_CODE = "1162064500"
DEMO_DONG_NAME = "서원동"

# all_excluded 관통 경로 재현용 시드 행정동. 이 동의 대피소는 픽스처상 전부 지하라, 호우
# 안전필터가 후보를 전부 제외해 availability="all_excluded"가 된다 — 후보가 아예 없는
# upstream_unavailable과 다른 경로다. 발송→세션→검색이 이어지려면 이 동에도 주민이 있어야
# 하므로 p003을 둔다(e2e가 이 시드를 이어받는다).
# ⚠️ dongCode는 실재 10자리 행정동 코드를 오프라인에서 확정하지 못해 가공값을 쓴다(관악구
#    11620 접두만 실제, 뒤 4자리 미검증). 실 코드 매칭 테이블(Backend S1-1)이 들어오면 교체한다.
UNDERGROUND_ONLY_DONG_CODE = "1162066500"
UNDERGROUND_ONLY_DONG_NAME = "신림동"
# QA 인계: 데모 특보는 이 동을 안 덮는다. all_excluded 관통은
# affectedDongCodes: ["1162066500"] 이벤트를 /internal/alerts/dispatch에 실어야 p003 세션이 나온다.


def seed_registry() -> ResidentRegistry:
    """Demo personas plus one all_excluded probe resident.

    p001·p002 are the killer-demo two in 서원동; p003 lives in a 행정동 whose only shelters
    are underground, so the flood safety filter empties the list — the all_excluded path the
    other two never exercise.
    """
    return ResidentRegistry(
        [
            Resident(
                profile=Profile(
                    user_id="p001",
                    name="김순자",
                    dong_code=DEMO_DONG_CODE,
                    dong_name=DEMO_DONG_NAME,
                    bjd_code="1162010200",
                    housing="banjiha",
                    mobility="slow",
                    stairs_ok=False,
                    easy_text=True,
                    vision="ok",
                    hearing="ok",
                    language="ko",
                    lives_alone=True,
                    care=None,
                    guardian=Guardian(name="김미영", phone="010-0000-0000", relation="딸"),
                    registered_by="guardian",
                ),
                registration_token="r_demo_resident_p001",  # noqa: S106 - 가공 데모 값
                # p001은 보호자(김미영, 딸)를 가진 유일한 시드라 2차 발송 대상이 있다. ward
                # 기기 1 + guardian 기기 1을 심어 폐루프 시연 경로를 세운다(ADR-0015).
                # ⚠️ 두 토큰 모두 가공값 — 실발송 전환 후에는 접수되지 않으므로 리허설 때
                #    실제 FCM 토큰으로 교체해야 한다(ADR-0015 "심는 토큰은 실제여야 한다").
                devices={"ward": ["fcm_demo_device_p001"], "guardian": ["fcm_demo_guardian_p001"]},
            ),
            Resident(
                profile=Profile(
                    user_id="p002",
                    name="Nguyen Van A",
                    dong_code=DEMO_DONG_CODE,
                    dong_name=DEMO_DONG_NAME,
                    housing="normal",
                    mobility="ok",
                    stairs_ok=True,
                    easy_text=True,
                    vision="ok",
                    hearing="ok",
                    language="vi",
                    lives_alone=False,
                    care=None,
                    guardian=None,
                    registered_by="employer",
                ),
                registration_token="r_demo_resident_p002",  # noqa: S106 - 가공 데모 값
                # guardian이 null이라 결정 8번대로 2단계에 안 들어간다 — guardian 기기 없음.
                devices={"ward": ["fcm_demo_device_p002"], "guardian": []},
            ),
            Resident(
                profile=Profile(
                    user_id="p003",
                    name="이철수",
                    dong_code=UNDERGROUND_ONLY_DONG_CODE,
                    dong_name=UNDERGROUND_ONLY_DONG_NAME,
                    housing="normal",
                    mobility="ok",
                    stairs_ok=True,
                    easy_text=True,
                    vision="ok",
                    hearing="ok",
                    language="ko",
                    lives_alone=False,
                    care=None,
                    guardian=None,
                    registered_by="welfare_center",
                ),
                registration_token="r_demo_resident_p003",  # noqa: S106 - 가공 데모 값
                devices={"ward": ["fcm_demo_device_p003"], "guardian": []},
            ),
        ]
    )
