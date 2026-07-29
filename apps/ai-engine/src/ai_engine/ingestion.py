"""Ingestion seam: where the 국민행동요령 corpus enters the pipeline.

Parsing stage of the one-way pipeline (parsing -> chunking -> embedding -> retrieval ->
generation, see `chunking.py`). This module normalizes rows fetched from the live API into
the exact `dict[str, str]` shape `chunking.parse_rows()` produces from a CSV, so
`chunking.chunk_rows()` is reused unchanged regardless of source. Mirrors
`backend_core.ingest`'s "ingestion seam" framing, for a different upstream (a corpus API
instead of a live disaster feed).

Source: safetydata.go.kr, DSSP-IF-20588 (재난안전데이터 공유 플랫폼). Schema below was
confirmed by direct probing on 2026-07-29 — there is no published field-level doc at hand.

⚠️ `safety_cate` is not truly optional: omitting it silently scopes results to 태풍
(safety_cate2=01001) rather than returning every disaster type. Known codes: 01001=태풍,
01002=홍수, 01003=호우, 01004=강풍. `scripts/fetch_corpus.py` defaults to 호우+홍수 for the
MVP's flood target — this module stays disaster-agnostic and takes the code(s) as input.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

API_URL = "https://www.safetydata.go.kr/V2/api/DSSP-IF-20588"

# Hard stop on pagination regardless of what `totalCount` claims — a wrong/stale count (or
# a server that keeps re-serving the same page) must fail loudly, not spin forever burning
# quota against a rate-limited public API.
MAX_PAGES = 1000

# Same 9 keys as the CSV columns `chunking.parse_rows()` reads — this is the shape
# `chunk_rows()` is written against, independent of whether the source is a CSV or the API.
ROW_FIELDS = (
    "actRmks",
    "contentsUrl",
    "safety_cate1",
    "safety_cate2",
    "safety_cate3",
    "safety_cate4",
    "safety_cate_nm1",
    "safety_cate_nm2",
    "safety_cate_nm3",
)


class ActionManualApiError(RuntimeError):
    """Non-zero `resultCode` from the API (bad key, unregistered IP, quota, ...)."""


def _normalize(item: dict[str, Any]) -> dict[str, str]:
    # The API returns JSON null for empty optional fields (e.g. contentsUrl); parse_rows()
    # from CSV always yields "" for the same case, so callers get one shape either way.
    return {field: str(item.get(field) or "") for field in ROW_FIELDS}


def _redact_service_key(url: httpx.URL) -> str:
    """URL with `serviceKey` masked.

    `httpx`'s default `raise_for_status()` exception embeds the full request URL —
    including the raw key — in its message. This is the only place that string gets built
    for an error path, so redacting it here is the single fix point.
    """
    params = dict(url.params)
    if "serviceKey" in params:
        params["serviceKey"] = "REDACTED"
    return str(url.copy_with(params=params))


def fetch_action_manual_rows(
    api_key: str,
    *,
    safety_cate: str | list[str] | None = None,
    page_size: int = 100,
    client: httpx.Client | None = None,
    sleep_between_pages_s: float = 0.2,
    max_pages: int = MAX_PAGES,
) -> list[dict[str, str]]:
    """Fetch and normalize every row for the given `safety_cate` code(s).

    `safety_cate=None` calls the API without the filter — only do this deliberately: the
    platform silently scopes an unfiltered call to 태풍 (see module docstring).
    """
    codes: list[str | None]
    if isinstance(safety_cate, str):
        codes = [safety_cate]
    elif safety_cate:
        codes = list(safety_cate)
    else:
        codes = [None]

    owns_client = client is None
    http_client = client or httpx.Client(timeout=20.0)
    try:
        rows: list[dict[str, str]] = []
        for code in codes:
            rows.extend(
                _fetch_one_category(
                    http_client, api_key, code, page_size, sleep_between_pages_s, max_pages
                )
            )
        return rows
    finally:
        if owns_client:
            http_client.close()


def _fetch_one_category(
    client: httpx.Client,
    api_key: str,
    safety_cate: str | None,
    page_size: int,
    sleep_between_pages_s: float,
    max_pages: int,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    total_count: int | None = None

    for page_no in range(1, max_pages + 1):
        params: dict[str, str | int] = {
            "serviceKey": api_key,
            "numOfRows": page_size,
            "pageNo": page_no,
            "returnType": "json",
        }
        if safety_cate is not None:
            params["safety_cate"] = safety_cate

        response = client.get(API_URL, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # `from None`, not `from exc`: chaining would keep the original (key-bearing)
            # exception attached, and any traceback printer downstream would still leak it.
            raise ActionManualApiError(
                f"HTTP {exc.response.status_code} calling {_redact_service_key(exc.request.url)}"
            ) from None
        payload = response.json()

        header = payload.get("header", {})
        if header.get("resultCode") != "00":
            raise ActionManualApiError(
                f"{header.get('resultCode')}: {header.get('resultMsg')} ({header.get('errorMsg')})"
            )

        body = payload.get("body") or []
        if not body:
            # Server has nothing more, regardless of what totalCount claims — stop rather
            # than looping on empty pages forever.
            break
        rows.extend(_normalize(item) for item in body)

        total_count = payload["totalCount"]
        if len(rows) >= total_count:
            break

        if sleep_between_pages_s:
            time.sleep(sleep_between_pages_s)
    else:
        raise ActionManualApiError(
            f"exceeded max_pages={max_pages} while paginating (safety_cate={safety_cate!r}); "
            "totalCount may be wrong or the API may be repeating pages"
        )

    return rows
