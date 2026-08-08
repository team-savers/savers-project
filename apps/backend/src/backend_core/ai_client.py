"""HTTP client for apps/ai-engine.

⚠️ This module is the *entire* coupling between the two apps. A Python import of
`ai_engine` anywhere in this app would silently destroy the "independently deployable AI
module" property the repo structure exists to prove — so request and response shapes are
rebuilt here from the shared spec (packages/contracts/openapi.yaml, `generation` 태그)
rather than shared as code.

Failure handling follows ADR-0006:
- **`message: null`** — a normal 200 refusal. Returned as `None`; the caller substitutes
  the pre-approved fallback. The engine never produces `official_fallback` itself.
- **timeout / 503 / connection error** — raised as `AiEngineUnavailableError`, which the
  contract says to treat identically to the refusal case.

The timeout is mandatory, not defensive: the 도달 속도 target is 30s, so an unbounded wait
is a metric failure by itself.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from backend_core.models import (
    AlertMessage,
    ChatResponse,
    DisasterContext,
    GenerationContext,
    Locale,
    RecipientContext,
    Source,
)


class AiEngineUnavailableError(RuntimeError):
    """The AI engine timed out, refused the connection or returned a non-2xx."""


class AiEngineClient(Protocol):
    def generate(self, event_id: str, context: GenerationContext) -> AlertMessage | None: ...

    def answer(
        self,
        question: str,
        recipient: RecipientContext,
        disaster: DisasterContext,
        locale: Locale,
    ) -> ChatResponse: ...


class HttpAiEngineClient:
    """Real client. One short-lived call per request, no retries.

    Retrying inside the 30s alert budget would spend the remaining time on a service that
    is already failing; the fallback path is faster and always available.
    """

    def __init__(self, base_url: str, timeout_s: float = 8.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_s

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = httpx.post(f"{self._base_url}{path}", json=payload, timeout=self._timeout)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AiEngineUnavailableError(f"{path}: {exc}") from exc
        return data

    def generate(self, event_id: str, context: GenerationContext) -> AlertMessage | None:
        """Ask for a message. `None` means the engine refused for lack of evidence."""
        data = self._post(
            "/v1/generate",
            {
                "eventId": event_id,
                "context": context.model_dump(mode="json", by_alias=True),
            },
        )
        try:
            message = data.get("message")
            if message is None:
                return None
            return AlertMessage(
                title=message["title"],
                body=message["body"],
                message_mode=message["messageMode"],
                sources=[Source.model_validate(s) for s in message.get("sources", [])],
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AiEngineUnavailableError(f"/v1/generate: malformed response: {exc}") from exc

    def answer(
        self,
        question: str,
        recipient: RecipientContext,
        disaster: DisasterContext,
        locale: Locale,
    ) -> ChatResponse:
        data = self._post(
            "/v1/answer",
            {
                "question": question,
                "recipient": recipient.model_dump(mode="json", by_alias=True),
                "disaster": disaster.model_dump(mode="json", by_alias=True),
                "locale": locale,
            },
        )
        try:
            return ChatResponse(
                answer=data["answer"],
                sources=[Source.model_validate(s) for s in data.get("sources", [])],
                refusal_reason=data.get("refusalReason"),
            )
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise AiEngineUnavailableError(f"/v1/answer: malformed response: {exc}") from exc
