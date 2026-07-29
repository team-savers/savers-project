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


def fetch_action_manual_rows(
    api_key: str,
    *,
    safety_cate: str | list[str] | None = None,
    page_size: int = 100,
    client: httpx.Client | None = None,
    sleep_between_pages_s: float = 0.2,
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
                _fetch_one_category(http_client, api_key, code, page_size, sleep_between_pages_s)
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
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    page_no = 1
    total_count: int | None = None

    while total_count is None or len(rows) < total_count:
        params: dict[str, str | int] = {
            "serviceKey": api_key,
            "numOfRows": page_size,
            "pageNo": page_no,
            "returnType": "json",
        }
        if safety_cate is not None:
            params["safety_cate"] = safety_cate

        response = client.get(API_URL, params=params)
        response.raise_for_status()
        payload = response.json()

        header = payload.get("header", {})
        if header.get("resultCode") != "00":
            raise ActionManualApiError(
                f"{header.get('resultCode')}: {header.get('resultMsg')} ({header.get('errorMsg')})"
            )

        total_count = payload["totalCount"]
        rows.extend(_normalize(item) for item in payload.get("body") or [])
        page_no += 1

        if sleep_between_pages_s and len(rows) < total_count:
            time.sleep(sleep_between_pages_s)

    return rows
