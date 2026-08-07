"""Push delivery.

Web push (FCM) is the primary channel — 알림톡 is not adopted, in the preliminary
round or the finals (ADR-0005).
Two consequences are load-bearing here:

- **The body is delivered verbatim.** There is no template, no approved slot set, no
  rendering adapter, and none may be reintroduced. What the eval harness scores is exactly
  what the user receives; inserting a substitution layer would break that equality and with
  it the meaning of 근거 일치율·메시지 명확성.
- **No reliance on notification action buttons.** Platforms cap them at two and behave
  inconsistently, so [집이에요]/[밖이에요] lives on the landing page, not the notification.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PushPayload:
    """What actually goes out. `body` is the generated text, unmodified."""

    device_token: str
    title: str
    body: str
    link: str


class Dispatcher(Protocol):
    def send(self, payload: PushPayload) -> bool: ...


class RecordingDispatcher:
    """In-memory dispatcher: records instead of sending.

    Default for P1 and for tests. FCM Admin SDK credentials only exist on the deployed VM,
    and CI must never hit a real push endpoint — but the walking skeleton still has to
    prove that a fully formed payload reaches the last step of the pipeline.
    """

    def __init__(self) -> None:
        self.sent: list[PushPayload] = []

    def send(self, payload: PushPayload) -> bool:
        self.sent.append(payload)
        return True

    def clear(self) -> None:
        self.sent.clear()


def deep_link(base_url: str, token: str, stage: int) -> str:
    """Landing URL carried by the push.

    `?s=` is a rendering *hint* only. The frontend must take the stage from the session
    response, because a stale notification or a tampered URL would otherwise put the screen
    in a different state than the server's judgement of the situation.
    """
    return f"{base_url.rstrip('/')}/a?t={token}&s={stage}"
