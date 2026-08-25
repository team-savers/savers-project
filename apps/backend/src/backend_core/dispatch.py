"""Push delivery.

Web push (FCM) is the primary channel — 알림톡 is out of preliminary scope (ADR-0005).
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
from typing import Any, Protocol
from urllib.parse import urlsplit


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


def _same_origin_path(link: str) -> str:
    """Reduce a deep link to its path and query, dropping scheme and host.

    The push carries `data.url`, and the service worker validates that it stays on the
    landing origin before navigating (sw.ts notificationclick). Sending an absolute URL
    would either fail that check or pin the notification to one host; the relative form is
    same-origin by construction and survives a domain change between build and deploy.
    """
    parts = urlsplit(link)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def _load_firebase() -> tuple[Any, Any, Any]:
    """Import the Admin SDK lazily so CI and local tests never require it.

    firebase-admin is an optional extra installed only on the deployed VM (pyproject
    `[project.optional-dependencies] fcm`). Importing at module top would pull it into every
    test run and the lint image. Kept as one seam so a test can substitute a fake SDK.
    """
    import firebase_admin
    from firebase_admin import credentials, messaging

    return firebase_admin, credentials, messaging


class FcmDispatcher:
    """Sends `PushPayload` as a data-only FCM message. The real channel behind the Protocol.

    Three properties mirror the Protocol's meaning and must not drift:

    - **data-only, three string keys.** `{title, body, url}` and nothing else — no
      `notification` block (sw.ts would double-notify) and no extra keys. FCM's `data` map
      is string-to-string, and all three values already are.
    - **`send()` returns acceptance, not delivery.** `True` means FCM returned a message id
      (push_accepted, ADR-0013), never that the device received it.
    - **No retry here.** A failed send returns `False`; deciding whether to try again is the
      closed loop's job, not the adapter's (one responsibility per layer).
    """

    def __init__(self, service_account_path: str, *, app_name: str = "savers") -> None:
        self._path = service_account_path
        self._app_name = app_name
        self._messaging: Any | None = None

    def _ensure_messaging(self) -> Any:
        """Initialize the named app once, then reuse it. Config errors surface loudly.

        A bad credential path or a missing SDK raises here rather than being folded into a
        `False` return — those are deploy-time faults, and the pipeline's send-error belt
        counts them distinctly from an honest per-device rejection.
        """
        if self._messaging is None:
            firebase_admin, credentials, messaging = _load_firebase()
            try:
                firebase_admin.get_app(self._app_name)
            except ValueError:
                firebase_admin.initialize_app(
                    credentials.Certificate(self._path), name=self._app_name
                )
            self._messaging = messaging
        return self._messaging

    def send(self, payload: PushPayload) -> bool:
        messaging = self._ensure_messaging()
        message = messaging.Message(
            token=payload.device_token,
            data={
                "title": payload.title,
                # Verbatim, like RecordingDispatcher — no slot layer (ADR-0005/0006).
                "body": payload.body,
                "url": _same_origin_path(payload.link),
            },
        )
        try:
            message_id = messaging.send(message)
        except Exception:
            # An FCM-side rejection (unregistered token, quota, transient) is a False, not a
            # crash. Retry, if any, belongs to the coordination loop.
            return False
        return bool(message_id)


def deep_link(base_url: str, token: str, stage: int) -> str:
    """Landing URL carried by the push.

    `?s=` is a rendering *hint* only. The frontend must take the stage from the session
    response, because a stale notification or a tampered URL would otherwise put the screen
    in a different state than the server's judgement of the situation.
    """
    return f"{base_url.rstrip('/')}/a?t={token}&s={stage}"
