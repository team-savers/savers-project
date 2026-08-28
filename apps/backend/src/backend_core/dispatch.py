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

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

# Default webpush TTL. Matched to the session token lifetime (config.session_ttl_s, 6h): a
# push FCM has not yet delivered outlives its session and lands on a dead link, so FCM should
# drop it at the same horizon rather than wake a phone with the previous day's 특보. This PR
# is unwired, so the value is self-contained here; the wiring PR passes the live setting in.
_DEFAULT_WEBPUSH_TTL_S = 6 * 60 * 60
PushChannel = Literal["recording", "fcm"]


@dataclass(frozen=True)
class PushPayload:
    """What actually goes out. `body` is the generated text, unmodified."""

    device_token: str
    title: str
    body: str
    link: str


class Dispatcher(Protocol):
    channel: PushChannel

    def send(self, payload: PushPayload) -> bool: ...


class RecordingDispatcher:
    """In-memory dispatcher: records instead of sending.

    Default for P1 and for tests. FCM Admin SDK credentials only exist on the deployed VM,
    and CI must never hit a real push endpoint — but the walking skeleton still has to
    prove that a fully formed payload reaches the last step of the pipeline.
    """

    channel: PushChannel = "recording"

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
    - **`False` is device-confirmed unreachable, not any failure.** Only an FCM verdict that
      *this token* cannot receive (unregistered / sender-id mismatch) is an honest 미접수 →
      `False`. Every other fault (network, quota, config) propagates so the pipeline counts it
      in `send_errors`, keeping a transport failure distinct from an honest rejection — folding
      both into `False` would let a run of network errors pass as latency-sample-eligible 미접수
      and quietly defeat the M1 도달-속도 표본. No retry here either; that is the closed loop's job.
    """

    channel: PushChannel = "fcm"

    def __init__(
        self,
        service_account_path: str,
        *,
        app_name: str = "savers",
        ttl_seconds: int = _DEFAULT_WEBPUSH_TTL_S,
    ) -> None:
        self._path = service_account_path
        self._app_name = app_name
        self._ttl_seconds = ttl_seconds
        self._messaging: Any | None = None
        self._app: Any | None = None

    def prepare(self) -> None:
        """Validate the local SDK/credential/app setup without sending a network request."""
        self._ensure_messaging()

    def _ensure_messaging(self) -> Any:
        """Initialize the named app once, cache both the app handle and messaging module.

        A bad credential path or a missing SDK raises here rather than being folded into a
        `False` return — those are deploy-time faults, and the pipeline's send-error belt
        counts them distinctly from an honest per-device rejection.

        The app handle is captured (not just the module) because `messaging.send` must be
        given `app=` explicitly: this is a *named* app, so a bare `send(message)` would look
        up the non-existent default app and fail.
        """
        if self._messaging is None:
            firebase_admin, credentials, messaging = _load_firebase()
            try:
                app = firebase_admin.get_app(self._app_name)
            except ValueError:
                # Build the credential *outside* the init-race try below: a corrupted service
                # account JSON raises ValueError from Certificate(), and if that were inside
                # the try it would be swallowed and disguised as "app already exists" — a
                # config fault masquerading as a benign race. Let it propagate loudly.
                cred = credentials.Certificate(self._path)
                try:
                    app = firebase_admin.initialize_app(cred, name=self._app_name)
                except ValueError:
                    # Lost an init race: another caller registered the app between our
                    # get_app miss and this initialize_app. The app now exists, so adopt it
                    # rather than let the duplicate-name ValueError escape as a config fault.
                    app = firebase_admin.get_app(self._app_name)
            self._app = app
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
            # TTL closes the 410-window: FCM drops the push at the session horizon instead of
            # buffering it into the next day and waking a phone with a lapsed 특보. Urgency
            # high — a disaster alert is exactly the case web-push urgency exists for.
            webpush=messaging.WebpushConfig(
                headers={"TTL": str(self._ttl_seconds), "Urgency": "high"},
            ),
        )
        try:
            # app= is required: this is a named app, so an unbound send() would resolve the
            # (non-existent) default app and fail. _ensure_messaging cached the handle.
            message_id = messaging.send(message, app=self._app)
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError):
            # FCM confirms *this token* cannot receive: unregistered (uninstalled/expired) or
            # a sender-id mismatch. That is an honest 미접수 → False; the closed loop decides on
            # the guardian escalation. Every other FirebaseError/network fault is deliberately
            # NOT caught — it propagates so the pipeline counts it in `send_errors`, distinct
            # from this False (see the class docstring; folding them together defeats M1).
            return False
        return bool(message_id)


class DispatcherConfigurationError(RuntimeError):
    """The explicitly selected push channel cannot be prepared at process startup."""


def create_dispatcher(
    channel: PushChannel,
    service_account_path: Path | None,
    *,
    ttl_seconds: int = _DEFAULT_WEBPUSH_TTL_S,
) -> Dispatcher:
    """Build and prepare the explicit channel; FCM validation is local-only."""
    if channel == "recording":
        return RecordingDispatcher()
    if channel != "fcm":  # Defensive for non-Settings callers; Settings rejects this first.
        raise DispatcherConfigurationError(f"unsupported push channel: {channel}")
    if service_account_path is None:
        raise DispatcherConfigurationError(
            "SAVERS_FCM_SERVICE_ACCOUNT_PATH is required when SAVERS_PUSH_CHANNEL=fcm"
        )

    path = Path(service_account_path)
    if not path.exists():
        raise DispatcherConfigurationError(f"FCM service account file does not exist: {path}")
    if not path.is_file():
        raise DispatcherConfigurationError(f"FCM service account path is not a file: {path}")
    if not os.access(path, os.R_OK):
        raise DispatcherConfigurationError(f"FCM service account file is not readable: {path}")

    dispatcher = FcmDispatcher(str(path), ttl_seconds=ttl_seconds)
    try:
        dispatcher.prepare()
    except Exception as exc:
        raise DispatcherConfigurationError("FCM Admin SDK initialization failed") from exc
    return dispatcher


def deep_link(base_url: str, token: str, stage: int) -> str:
    """Landing URL carried by the push.

    `?s=` is a rendering *hint* only. The frontend must take the stage from the session
    response, because a stale notification or a tampered URL would otherwise put the screen
    in a different state than the server's judgement of the situation.
    """
    return f"{base_url.rstrip('/')}/a?t={token}&s={stage}"
