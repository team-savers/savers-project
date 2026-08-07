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
import re
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

# Fixtures live inside the package (src/) on purpose: 코드와 같은 버전으로 움직여야 하고,
# wheel/이미지에 함께 실려야 컨테이너 안에서도 재생할 수 있다. 지금 얼려둔 것은 스키마
# 재현용 replay 픽스처이고, 실제 오프라인 폴백용 대피소 캐시는 별도 과제다.
FIXTURES = Path(__file__).resolve().parents[1] / "src" / "backend_core" / "fixtures"

# fixture_path()에서 event_type을 좁히는 패턴. 파일명에 그대로 들어가므로 ASCII만 허용한다.
_EVENT_TYPE = re.compile(r"[A-Za-z0-9_-]+")


class CollectError(RuntimeError):
    """Request failed, or the upstream returned a non-normal result code."""


def today_kst() -> date:
    """Collection date in KST — the fixture filename is dated by when it was observed."""
    return datetime.now(KST).date()


def fixture_path(source: str, event_type: str) -> Path:
    """Where this collection would be frozen — computable without calling the upstream."""
    # isalnum()은 유니코드 기준이라 한글도 통과시킨다. 파일명에 들어가는 값은 ASCII만.
    if not _EVENT_TYPE.fullmatch(event_type):
        raise CollectError(
            f"event_type이 파일명에 그대로 들어갑니다. 영숫자와 -_만 허용: {event_type!r}"
        )
    return FIXTURES / f"{source}_{event_type}_{today_kst():%Y%m%d}.json"


def refuse_if_frozen(path: Path) -> None:
    """Fail before spending a request: the daily quota is the reason fixtures exist."""
    if path.exists():
        raise CollectError(
            f"이미 존재: {path.name}. 픽스처는 수정하지 않는다. 새 이름으로 수집할 것."
        )


def save_fixture(source: str, event_type: str, payload: dict[str, Any]) -> None:
    """Freeze one response as `{source}_{event_type}_{YYYYMMDD}.json`.

    `newline="\\n"`은 미관이 아니다. 없으면 윈도우가 CRLF로 쓰고, 아래 digest가 그 CRLF를
    해시하고, git은 커밋 시 blob을 LF로 정규화한다 — 출력된 해시가 커밋된 파일과 영영
    맞지 않는다. 실제로 그 상태로 한 번 올라갔다.
    """
    path = fixture_path(source, event_type)
    refuse_if_frozen(path)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"동결 완료: {path.name}  sha256[:12]={digest}")
    print("fixtures/README.md 수집 이력 표에 위 해시와 함께 기록할 것.")


# ── 인증 ────────────────────────────────────────────────────────────────────────────────

ENV_DEFAULT = Path(__file__).resolve().parents[3] / "infra" / ".env"


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


# ── 기상청 단기예보 ─────────────────────────────────────────────────────────────────────

KMA_CHOICE = "kma-forecast"
KMA_SOURCE = "kma_vilage_fcst"
KMA_ENV_KEY = "KMA_APIHUB_KEY"
KMA_BASE = "https://apihub.kma.go.kr/api/typ02/openApi/VilageFcstInfoService_2.0"

# 발표 시각(KST). 자료는 각 시각 +10분쯤 올라오므로 조금 물러선 뒤 고른다.
KMA_BASE_TIMES = (2, 5, 8, 11, 14, 17, 20, 23)
KMA_PUBLISH_LAG = timedelta(minutes=15)

# 한 시각당 12개 안팎의 카테고리가 나오므로, 10건만 받으면 PCP/POP가 아예 안 들어온
# 픽스처가 나올 수 있다. 기상청 한도는 일 20000회로 safetydata와 별개다.
KMA_DEFAULT_ROWS = 300


def latest_kma_base(now: datetime) -> tuple[str, str]:
    """Most recent 발표 시각 whose data should already be published."""
    candidate = now - KMA_PUBLISH_LAG
    for hour in reversed(KMA_BASE_TIMES):
        if candidate.hour >= hour:
            return candidate.strftime("%Y%m%d"), f"{hour:02d}00"
    previous_day = candidate - timedelta(days=1)
    return previous_day.strftime("%Y%m%d"), f"{KMA_BASE_TIMES[-1]:02d}00"


def fetch_kma(
    *, key: str, nx: int, ny: int, rows: int, timeout_s: float
) -> tuple[dict[str, Any], str, str]:
    """Fetch one 단기예보 page and return it **exactly as received**.

    3시간 합산과 범주 문자열 해석은 의도적으로 하지 않는다. 그 계산은 소비자 쪽 로직이라,
    픽스처에 넣으면 관측이 아니라 해석을 얼리게 된다.
    """
    base_date, base_time = latest_kma_base(datetime.now(KST))
    params = {
        "authKey": key,  # API허브는 authKey — 공공데이터포털의 serviceKey와 다르다
        "pageNo": "1",
        "numOfRows": str(rows),
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": str(nx),
        "ny": str(ny),
    }

    try:
        response = httpx.get(f"{KMA_BASE}/getVilageFcst", params=params, timeout=timeout_s)
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise CollectError(f"요청 실패 (HTTP {exc.response.status_code}) — 기상청") from None
    except httpx.HTTPError as exc:
        raise CollectError(f"요청 실패 ({type(exc).__name__}) — 기상청") from None

    try:
        payload: dict[str, Any] = response.json()
    except ValueError:
        raise CollectError(
            "JSON 파싱 실패 — 기상청. 인증키 미등록이거나 한도 초과일 때 XML 오류 문서가 "
            "돌아옵니다. 본문은 키가 섞일 수 있어 출력하지 않습니다."
        ) from None

    header = payload.get("response", {}).get("header", {})
    code = str(header.get("resultCode", "")).strip()
    if code and code != "00":
        raise CollectError(f"기상청 resultCode={code} ({header.get('resultMsg')})")

    # 미승인·한도 초과면 apihub가 봉투 없이 {"result": {"status": 403}}만 돌려준다. JSON
    # 파싱은 되고 header가 없어 위 검사를 그냥 통과하므로, 자료가 실제로 왔는지로 한 번 더
    # 막는다. 이걸 저장하면 이름 중복 거부 때문에 같은 이름으로 재수집도 못 한다.
    response_obj = payload.get("response") or {}
    items = ((response_obj.get("body") or {}).get("items") or {}).get("item")
    if not isinstance(items, list) or not items:
        status = (payload.get("result") or {}).get("status")
        raise CollectError(
            f"기상청 응답에 예보 항목이 없습니다 (result.status={status}). "
            "인증키 미승인, 한도 초과, 또는 격자·발표시각이 잘못된 경우입니다."
        )

    return payload, base_date, base_time


# ── CLI ─────────────────────────────────────────────────────────────────────────────────


def describe(payload: dict[str, Any]) -> str:
    """One-line summary for stdout. Reads the payload but never alters the saved bytes."""
    body = payload.get("body")
    if isinstance(body, list):  # safetydata
        total = payload.get("totalCount") or (payload.get("header") or {}).get("totalCount")
        return f"body {len(body)}건 수신 (상류 totalCount={total})"

    items = payload.get("response", {}).get("body", {}).get("items", {}).get("item")
    if isinstance(items, list):  # 기상청
        categories = sorted({str(i.get("category")) for i in items if isinstance(i, dict)})
        return f"item {len(items)}건 수신 (카테고리: {', '.join(categories)})"

    return "수신 완료 — 알 수 없는 응답 형태(원본 그대로 저장)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="재난 API 응답을 픽스처로 동결")
    parser.add_argument(
        "target", choices=[*sorted(SAFETYDATA_TARGETS), KMA_CHOICE], help="수집 대상"
    )
    parser.add_argument("event_type", help="픽스처 이름에 들어갈 상황 라벨 (예: baseline)")
    parser.add_argument("--rows", type=int, default=None, help="numOfRows (대상별 기본값 사용)")
    parser.add_argument("--nx", type=int, default=60, help="기상청 예보 격자 X (기본: 종로구)")
    parser.add_argument("--ny", type=int, default=127, help="기상청 예보 격자 Y (기본: 종로구)")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--env", type=Path, default=ENV_DEFAULT, help="인증키를 읽을 .env 경로")
    args = parser.parse_args(argv)

    is_kma = args.target == KMA_CHOICE
    source = KMA_SOURCE if is_kma else SAFETYDATA_TARGETS[args.target].source
    env_key = KMA_ENV_KEY if is_kma else SAFETYDATA_TARGETS[args.target].env_key
    rows = args.rows or (KMA_DEFAULT_ROWS if is_kma else SAFETYDATA_DEFAULT_ROWS)

    try:
        refuse_if_frozen(fixture_path(source, args.event_type))
        key = load_key_from_env_file(args.env, env_key)
        if is_kma:
            payload, base_date, base_time = fetch_kma(
                key=key, nx=args.nx, ny=args.ny, rows=rows, timeout_s=args.timeout
            )
            print(f"기상청 발표 {base_date} {base_time}, 격자 nx={args.nx} ny={args.ny}")
        else:
            payload = fetch_safetydata(
                key=key,
                endpoint=SAFETYDATA_TARGETS[args.target].endpoint,
                rows=rows,
                timeout_s=args.timeout,
            )
        print(describe(payload))
        save_fixture(source, args.event_type, payload)
    except CollectError as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
