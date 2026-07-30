"""재난 API 응답을 1회 수집해 픽스처로 동결한다.

Freezing rules — why this is a script and not a manual curl:

- **The saved file is the unparsed upstream response.** Any 3시간 합산이나 범주 문자열
  해석은 소비자 쪽 로직이고, 그것을 여기서 적용하면 "관측한 것"이어야 할 파일에 파생값이
  섞인다. 픽스처가 가공되면 그 뒤의 어떤 측정도 상류를 근거로 삼지 못한다.
- **A fixture is never overwritten.** 같은 이름으로 다시 수집하는 것은 거부한다. 이미
  누군가 그 파일을 근거로 판단한 뒤에 내용이 조용히 바뀌는 것이 픽스처의 최악 실패다.
- **요청 URL과 서비스키는 저장 파일·표준출력·예외 어디에도 넣지 않는다.** 이 저장소는
  공개이고, 픽스처는 키가 숨어 들어가기 가장 쉬운 자리다.

Usage: python apps/backend/scripts/collect_fixture.py <target> <event_type>
  e.g. python apps/backend/scripts/collect_fixture.py shelter baseline

수집한 파일은 fixtures/README.md의 이력 표에 sha256과 함께 기록할 것.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

# Fixed +09:00 instead of ZoneInfo("Asia/Seoul"): KST has observed no DST since 1988, and on
# Windows `zoneinfo` has no system tz database so it needs the `tzdata` package, which this
# app does not declare as a dependency. backend_core.config has no shared today_kst() on
# main, so the helper lives here rather than being imported.
KST = timezone(timedelta(hours=9))

# Fixtures live inside the package (src/) on purpose: 오프라인 예비모드가 런타임에 이들로
# 폴백하므로, wheel/이미지 밖에 있는 픽스처는 정확히 필요한 순간에 없다.
FIXTURES = Path(__file__).resolve().parents[1] / "src" / "backend_core" / "fixtures"


def today_kst() -> date:
    """Collection date in KST — the fixture filename is dated by when it was observed."""
    return datetime.now(KST).date()


def save_fixture(source: str, event_type: str, payload: dict[str, Any]) -> None:
    """Freeze one response as `{source}_{event_type}_{YYYYMMDD}.json`.

    Refuses to overwrite an existing file, and prints the sha256 prefix so the collection
    can be recorded against a specific observation.
    """
    name = f"{source}_{event_type}_{today_kst():%Y%m%d}.json"
    path = FIXTURES / name
    if path.exists():
        raise SystemExit(f"이미 존재: {name}. 픽스처는 수정하지 않는다. 새 이름으로 수집할 것.")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"동결 완료: {name}  sha256[:12]={digest}")
    print("fixtures/README.md 수집 이력 표에 위 해시와 함께 기록할 것.")


# ── 인증 ────────────────────────────────────────────────────────────────────────────────

ENV_DEFAULT = Path(__file__).resolve().parents[3] / "infra" / ".env"


class CollectError(RuntimeError):
    """Request failed, or the upstream returned a non-normal result code."""


def load_key_from_env_file(env_path: Path, key_name: str) -> str:
    """Read one key from infra/.env only.

    No os.environ fallback on purpose: a key that leaked into a shell profile or a CI
    environment would otherwise be used without anyone knowing where it came from.
    """
    if not env_path.is_file():
        raise CollectError(f"{env_path} 없음. infra/.env.example을 복사해 {key_name}를 채우세요.")

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        if name.strip() != key_name:
            continue
        # Strip an inline `# 주석` — .env.example carries one on every safetydata line.
        cleaned = value.split("#", 1)[0].strip().strip("'\"")
        if not cleaned:
            raise CollectError(f"{env_path}의 {key_name}가 비어 있습니다.")
        return cleaned

    raise CollectError(f"{env_path}에 {key_name} 항목이 없습니다.")


# ── safetydata ──────────────────────────────────────────────────────────────────────────

SAFETYDATA_BASE = "https://www.safetydata.go.kr/V2/api"

# 일 1000건 한도는 **호출 수** 기준이라 numOfRows를 키워도 소모량은 같다. 예산을 지키는
# 것은 pageNo=1 고정(실행당 정확히 1회 호출)이고, 아래 행수는 픽스처를 "응답 형태를 보기에
# 충분한 최소량"으로 잡아 둔 값이다.
SAFETYDATA_DEFAULT_ROWS = 10


@dataclass(frozen=True)
class SafetydataTarget:
    """One collectable dataset. `source` becomes the fixture filename prefix."""

    source: str
    endpoint: str
    env_key: str


SAFETYDATA_TARGETS: dict[str, SafetydataTarget] = {
    "emergency-sms": SafetydataTarget(
        "safetydata_emergency_sms", "DSSP-IF-00247", "SAFETYDATA_EMERGENCY_SMS_KEY"
    ),
    "shelter": SafetydataTarget("safetydata_shelter", "DSSP-IF-10941", "SAFETYDATA_SHELTER_KEY"),
    "flood-trace": SafetydataTarget(
        "safetydata_flood_trace", "DSSP-IF-00117", "SAFETYDATA_FLOOD_TRACE_KEY"
    ),
    "hazard-zone": SafetydataTarget(
        "safetydata_hazard_zone", "DSSP-IF-00058", "SAFETYDATA_HAZARD_ZONE_KEY"
    ),
    "flood-trace-line": SafetydataTarget(
        "safetydata_flood_trace_line", "DSSP-IF-20678", "SAFETYDATA_FLOOD_TRACE_LINE_KEY"
    ),
}


def fetch_safetydata(*, key: str, endpoint: str, rows: int, timeout_s: float) -> dict[str, Any]:
    """Fetch page 1 and return the response **exactly as received**.

    The envelope is kept, not just `body`: header.resultCode and totalCount are part of the
    observation, and a fixture that has already dropped them cannot be used to check what
    the upstream actually claimed. Errors carry the status code but never the URL, the key
    or the response text.
    """
    params = {
        "serviceKey": key,  # capital K — the platform rejects `servicekey`
        "returnType": "json",
        "pageNo": "1",
        "numOfRows": str(rows),
    }

    try:
        response = httpx.get(f"{SAFETYDATA_BASE}/{endpoint}", params=params, timeout=timeout_s)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise CollectError(f"요청 실패 (HTTP {exc.response.status_code}) — {endpoint}") from None
    except httpx.HTTPError as exc:
        raise CollectError(f"요청 실패 ({type(exc).__name__}) — {endpoint}") from None

    try:
        payload: dict[str, Any] = response.json()
    except ValueError:
        raise CollectError(
            f"JSON 파싱 실패 — {endpoint}. 인증키 미승인이거나 일 1000건 한도를 넘었을 때 "
            "플랫폼이 오류 문서를 돌려주는 경우입니다. 본문은 키가 섞일 수 있어 "
            "출력하지 않습니다."
        ) from None

    header = payload.get("header") or {}
    code = str(header.get("resultCode", "")).strip()
    # 일부 데이터셋은 성공 시 header를 생략한다 — "있는데 틀린" 코드만 실패로 본다.
    if code and code not in ("00", "0"):
        raise CollectError(
            f"resultCode={code} ({header.get('resultMsg') or header.get('errorMsg')})"
        )

    return payload


# ── CLI ─────────────────────────────────────────────────────────────────────────────────


def describe(payload: dict[str, Any]) -> str:
    """One-line summary for stdout. Never touches the saved bytes."""
    body = payload.get("body")
    count = len(body) if isinstance(body, list) else "?"
    total = (payload.get("totalCount")) or (payload.get("header") or {}).get("totalCount")
    return f"body {count}건 수신 (상류 totalCount={total})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="재난 API 응답을 픽스처로 동결")
    parser.add_argument("target", choices=sorted(SAFETYDATA_TARGETS), help="수집 대상")
    parser.add_argument("event_type", help="픽스처 이름에 들어갈 상황 라벨 (예: baseline)")
    parser.add_argument("--rows", type=int, default=SAFETYDATA_DEFAULT_ROWS, help="numOfRows")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--env", type=Path, default=ENV_DEFAULT, help="인증키를 읽을 .env 경로")
    args = parser.parse_args(argv)

    target = SAFETYDATA_TARGETS[args.target]
    try:
        key = load_key_from_env_file(args.env, target.env_key)
        payload = fetch_safetydata(
            key=key, endpoint=target.endpoint, rows=args.rows, timeout_s=args.timeout
        )
    except CollectError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1

    print(describe(payload))
    save_fixture(target.source, args.event_type, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
