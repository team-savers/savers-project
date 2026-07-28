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

from backend_core.models import Guardian, Profile


class RegistrationNotFoundError(LookupError):
    """No resident holds this registration token."""


@dataclass
class Resident:
    """A registered person plus the devices that can reach them.

    `registration_token` is long-lived and one-per-person; it is what a proxy registrar
    holds. It is deliberately *not* the session token — session tokens are minted at
    dispatch time, so requiring one to register a device would mean needing a push before
    you could receive a push (the circular dependency ADR-0005 flagged).
    """

    profile: Profile
    registration_token: str
    devices: list[str] = field(default_factory=list)


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

    def register_device(self, registration_token: str, fcm_token: str) -> Resident:
        resident = self.by_registration_token(registration_token)
        if fcm_token not in resident.devices:
            resident.devices.append(fcm_token)
        return resident

    def unregister_device(self, registration_token: str, fcm_token: str) -> Resident:
        """Detach a device. Idempotent — an already-absent token is still a success.

        Lost/replaced handsets, shared 복지관 terminals and withdrawn consent all end here;
        making the caller distinguish "removed" from "was not there" adds no information
        and invites retry loops.
        """
        resident = self.by_registration_token(registration_token)
        if fcm_token in resident.devices:
            resident.devices.remove(fcm_token)
        return resident

    def __len__(self) -> int:
        return len(self._by_user)


# ── Demo seed ────────────────────────────────────────────────────────────────────
# 킬러 데모 페르소나 2종(S2-E1): 반지하 고령자 + 외국인 근로자. Fictional people with
# fictional tokens — readable on purpose so nobody mistakes them for real credentials.

DEMO_DONG_CODE = "1162064500"
DEMO_DONG_NAME = "서원동"


def seed_registry() -> ResidentRegistry:
    """Two residents in the same 행정동, differing in every axis that changes the output."""
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
                devices=["fcm_demo_device_p001"],
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
                devices=["fcm_demo_device_p002"],
            ),
        ]
    )
