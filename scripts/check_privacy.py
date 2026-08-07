"""미저장·암호화 점검 — 개인정보_체크리스트.md를 실행 가능한 검사로 옮긴 것 (S1-E6).

docs/공통_가이드/개인정보_체크리스트.md 의 P1~P4·S1~S4 를 기준 삼아,
자동화 가능한 항목은 검사하고 불가능한 항목은 이유와 함께 SKIP 으로
보고한다 — 못 잰 것을 통과로 세지 않는다(eval 하네스의 null≠0 규약과
같은 원칙).

두 층으로 검사한다:

  정적 (스택 불필요, 항상 실행)
    P1  위치 조회가 동의 UI 뒤에만 있는가 — getCurrentPosition 호출이
        허용 목록(동의 분기를 소유한 두 파일) 밖에 없고, 상시 추적 API
        (watchPosition)는 저장소 어디에도 없는지.
    S1  민감정보 동의가 일반 동의와 분리돼 있는가 — ConsentFlags 가
        personal/sensitive/location 세 필드로 분리돼 있고, /ops 의
        분리동의 상수가 존재하는지.

  라이브 (--base-url 로 기동된 스택 필요; HTTP 만 사용 — 앱 패키지를
  import 하지 않는다, e2e 와 같은 경계 규칙)
    P2  원본 좌표 미저장 — 유일하게 이 스크립트만 아는 센티널 좌표로
        대피소 검색을 호출한 뒤: 응답에 좌표 반향 없음, Cache-Control:
        no-store, 세션·보호자 재조회에 좌표 없음, 서버 로그(--log)에
        좌표 없음을 확인한다.
        ⚠️ 로그 검사는 카나리아를 함께 요구한다: 같은 로그에서 검색
        요청의 접근 기록이 **보여야** 좌표 부재가 의미를 갖는다 —
        엉뚱한 로그 파일을 긁고 "없음 = 통과"가 되는 무음 실패를 막는다.
    P3  철회 즉시 파기 — P2 가 "저장 자체가 없음"을 보이면 설계상 자동
        충족(파기할 대상이 없음). P2 결과에서 유도한다.
    P4  사실 확인자료(메타 로그) — 좌표 없는 접근 기록이 로그에 남는지.
        전용 감사 로그는 미구현이므로, 접근 로그 존재를 확인하되 WARN
        으로 보고한다(법정 보관 기간 요건은 별도 설계 필요).

  SKIP (자동화 불가 — 이유를 출력에 남긴다)
    S2/S4/N1/N2  문구·문서 검토 항목 (체크리스트가 "사람이 체크"로 지정)
    S3  저장 시 암호화 — 등록 저장소가 아직 인메모리 스텁이라 스캔할
        DB 가 없다(2026-08-05 팀 결정: 실저장 경로는 예선 범위 밖,
        후속_과제.md 4번). 저장소가 생기는 PR 이 이 SKIP 을 검사로
        바꿔야 한다.

실행:
    python3 scripts/check_privacy.py                          # 정적만
    python3 scripts/check_privacy.py --base-url http://localhost:8000 \
        --log /path/to/backend.log [--out report.json]        # 정적+라이브

표준 라이브러리만 쓴다 — venv 없이 python3 만 있으면 어디서든 돈다.
종료 코드: FAIL 이 하나라도 있으면 1, 아니면 0 (SKIP/WARN 은 실패가 아님).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = REPO_ROOT / "apps" / "frontend" / "src"

# 위치 조회(getCurrentPosition) 호출이 허용되는 파일. 두 파일 다 동의 분기를
# 직접 소유한다 — LocationConsent 는 명시 동의 버튼 뒤, ShelterGuide 는
# permissions.query 가 'granted'(과거에 이미 동의)일 때의 재조회 분기.
# 새 호출 지점을 추가하려면 이 목록과 함께 그 파일의 동의 경로를 리뷰받아야
# 한다 — 목록 밖 호출은 P1 위반이다.
GEO_ALLOWED_FILES = {
    "components/LocationConsent.tsx",
    "components/ShelterGuide.tsx",
}

# 센티널 좌표. 실좌표처럼 보이지만 이 스크립트만 아는 소수부 자릿수를 써서,
# 로그·응답 어디에 남아도 부분 문자열 검색으로 잡힌다. 서울 시내 좌표 범위를
# 벗어나지 않아 서버가 "이상값"으로 다르게 처리할 여지도 없다.
SENTINEL_LAT = "37.4867309551"
SENTINEL_LNG = "126.9312880274"
# 로그에서 찾을 조각 — 반올림·포맷 변경에도 걸리도록 소수부 앞 8자리를 쓴다.
SENTINEL_FRAGMENTS = ("48673095", "93128802")


class Report:
    """항목별 결과 수집. FAIL 만 종료 코드를 바꾼다."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, check: str, status: str, detail: str) -> None:
        self.items.append({"check": check, "status": status, "detail": detail})
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️ ", "WARN": "⚠️ "}[status]
        print(f"{mark} {status:4} {check} — {detail}")

    @property
    def failed(self) -> bool:
        return any(i["status"] == "FAIL" for i in self.items)


# ---- 정적 검사 ---------------------------------------------------------


def check_p1_geolocation(report: Report) -> None:
    """P1: 위치 조회는 동의 분기 파일 안에만, 상시 추적 API 는 0건."""
    offenders: list[str] = []
    watch_hits: list[str] = []
    for path in FRONTEND_SRC.rglob("*.ts*"):
        rel = path.relative_to(FRONTEND_SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("//", "*", "/*")):
                continue  # 주석 속 언급은 호출이 아니다
            if "watchPosition" in line:
                watch_hits.append(f"{rel}:{lineno}")
            if "getCurrentPosition" in line and rel not in GEO_ALLOWED_FILES:
                offenders.append(f"{rel}:{lineno}")

    if watch_hits:
        report.add(
            "P1-tracking",
            "FAIL",
            f"상시 추적 API(watchPosition) 발견: {', '.join(watch_hits)} — "
            "'상시 위치 추적 없음'은 비타협 제약(AGENTS.md)",
        )
    else:
        report.add("P1-tracking", "PASS", "watchPosition 0건 — 1회 조회(getCurrentPosition)만 존재")

    if offenders:
        report.add(
            "P1-consent-path",
            "FAIL",
            f"동의 분기 밖 위치 조회: {', '.join(offenders)} — "
            f"허용 목록({', '.join(sorted(GEO_ALLOWED_FILES))}) 밖 호출",
        )
    else:
        report.add(
            "P1-consent-path",
            "PASS",
            f"getCurrentPosition 호출이 동의 분기 파일({len(GEO_ALLOWED_FILES)}곳) 안에만 존재",
        )


def check_s1_consent_separation(report: Report) -> None:
    """S1: 민감정보 동의가 일반 동의와 UI/데이터 모델상 분리."""
    types_ts = (FRONTEND_SRC / "api" / "types.ts").read_text(encoding="utf-8")
    match = re.search(r"export interface ConsentFlags \{(.*?)\}", types_ts, re.DOTALL)
    if match is None:
        report.add("S1-model", "FAIL", "ConsentFlags 인터페이스가 types.ts에 없음")
        return
    fields = set(re.findall(r"^\s*(\w+):\s*boolean", match.group(1), re.MULTILINE))
    required = {"personal", "sensitive", "location"}
    if required <= fields:
        report.add(
            "S1-model",
            "PASS",
            "ConsentFlags가 개인정보/민감정보/위치정보를 독립 필드로 분리 (제23조 분리 동의 구조)",
        )
    else:
        report.add(
            "S1-model", "FAIL", f"분리 동의 필드 누락: {sorted(required - fields)} (있는 것: {sorted(fields)})"
        )

    ops_tsx = (FRONTEND_SRC / "pages" / "Ops.tsx").read_text(encoding="utf-8")
    if "분리동의" in ops_tsx and "declineNote" in ops_tsx:
        report.add("S1-ui", "PASS", "/ops 등록 화면에 항목별 분리동의 UI 상수 존재 (필수/선택 구분 포함)")
    else:
        report.add("S1-ui", "FAIL", "/ops에서 분리동의 UI 정의를 찾지 못함")


# ---- 라이브 검사 -------------------------------------------------------


def _http(
    method: str, url: str, body: dict[str, object] | None = None
) -> tuple[int, dict[str, str], str]:
    if not url.startswith(("http://", "https://")):
        # --base-url 검증을 뚫고 와도 file:// 등으로 로컬 파일을 읽는 일이 없게.
        raise ValueError(f"http(s) URL만 허용: {url}")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)  # noqa: S310 - 위에서 스킴 검증
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - 위에서 스킴 검증
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read().decode()


def check_live(report: Report, base_url: str, log_paths: list[Path]) -> None:
    """P2/P3/P4: 센티널 좌표를 흘려보내고 어디에도 남지 않는지 확인."""
    status, _, dispatch_body = _http("POST", f"{base_url}/internal/alerts/dispatch")
    if status != 200:
        report.add("P2-nostore", "FAIL", f"dispatch가 {status} — 스택이 정상 기동됐는지 확인 필요")
        return
    deliveries = json.loads(dispatch_body)["deliveries"]
    if not deliveries:
        report.add("P2-nostore", "FAIL", "배송 결과 0건 — 시드 주민 매칭 실패")
        return
    delivery = deliveries[0]
    token = delivery["sessionToken"]

    # 센티널 좌표로 검색 — [밖이에요] 경로에서 실좌표가 들어오는 그 요청이다.
    status, headers, search_body = _http(
        "POST",
        f"{base_url}/v1/shelters/search",
        {"sessionToken": token, "dongCode": "1162064500", "lat": float(SENTINEL_LAT), "lng": float(SENTINEL_LNG)},
    )
    if status != 200:
        report.add("P2-nostore", "FAIL", f"좌표 포함 검색이 {status} — 검사를 진행할 수 없음")
        return

    if headers.get("cache-control") != "no-store":
        report.add(
            "P2-cache",
            "FAIL",
            f"검색 응답 Cache-Control이 no-store가 아님({headers.get('cache-control')!r}) — "
            "좌표가 본문으로 오가는 응답은 공유 캐시에 남으면 안 됨",
        )
    else:
        report.add("P2-cache", "PASS", "좌표 검색 응답 Cache-Control: no-store")

    echoed = [f for f in SENTINEL_FRAGMENTS if f in search_body]
    if echoed:
        report.add("P2-echo", "FAIL", f"검색 응답이 원본 좌표를 반향함 (조각 {echoed})")
    else:
        report.add("P2-echo", "PASS", "검색 응답에 원본 좌표 반향 없음 (거리·방위만 파생)")

    # 검색 이후 서버가 노출하는 상태 어디에도 좌표가 없어야 한다.
    leaked_state: list[str] = []
    for name, url in (
        ("session", f"{base_url}/v1/session/{token}"),
        ("guardian", f"{base_url}/v1/guardian/{delivery['guardianToken']}"),
    ):
        _, _, state_body = _http("GET", url)
        if any(f in state_body for f in SENTINEL_FRAGMENTS):
            leaked_state.append(name)
    if leaked_state:
        report.add("P2-state", "FAIL", f"검색 후 재조회 상태에 좌표 잔존: {leaked_state}")
    else:
        report.add("P2-state", "PASS", "검색 후 세션·보호자 재조회에 좌표 없음 (세션 범위 밖 미저장)")

    # 로그 스캔 — 카나리아(요청 접근 기록) 없이는 통과로 세지 않는다.
    if not log_paths:
        report.add("P2-logs", "WARN", "--log 미지정 — 서버 로그의 좌표 부재는 이번 실행에서 검사되지 않음")
    else:
        log_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in log_paths)
        canary = "/v1/shelters/search" in log_text
        leaked = [f for f in SENTINEL_FRAGMENTS if f in log_text]
        if not canary:
            report.add(
                "P2-logs",
                "FAIL",
                "로그에 검색 요청의 접근 기록 자체가 없음 — 엉뚱한 로그를 검사 중이거나 "
                "접근 로그가 꺼져 있음. 이 상태의 '좌표 없음'은 증거가 아님",
            )
        elif leaked:
            report.add("P2-logs", "FAIL", f"서버 로그에 원본 좌표 발견 (조각 {leaked}): {[str(p) for p in log_paths]}")
        else:
            report.add("P2-logs", "PASS", f"로그 {len(log_paths)}개에 접근 기록은 있고 좌표는 없음")

    # P3: 저장이 없으면 파기할 대상도 없다 — P2 계열이 전부 통과일 때만 유도.
    p2_all_pass = all(i["status"] == "PASS" for i in report.items if i["check"].startswith("P2-"))
    if p2_all_pass:
        report.add("P3-erasure", "PASS", "설계상 충족 — 저장 자체가 없음이 확인되어 철회 시 파기 대상이 없음 (P2에서 유도)")
    else:
        report.add("P3-erasure", "SKIP", "P2가 전부 통과일 때만 유도 가능 — 위 결과 참조")

    # P4: 좌표 없는 접근 기록(사실 확인자료). 전용 감사 로그는 미구현.
    if log_paths and "/v1/shelters/search" in log_text and not any(f in log_text for f in SENTINEL_FRAGMENTS):
        report.add(
            "P4-audit",
            "WARN",
            "접근 로그가 좌표 없이 조회 사실을 남기고 있음 — 다만 위치정보법 제16조제2항의 "
            "법정 보관 기간을 갖춘 전용 감사 로그는 미구현 (실서비스 전 설계 필요)",
        )
    else:
        report.add("P4-audit", "SKIP", "로그 미지정 또는 접근 기록 없음 — 판단 불가")


def add_manual_skips(report: Report) -> None:
    report.add(
        "S3-encryption",
        "SKIP",
        "등록 저장소가 인메모리 스텁이라 스캔할 DB 없음 (실저장 경로는 예선 범위 밖 — "
        "2026-08-05 팀 결정, 후속_과제.md 4번). 저장소를 붙이는 PR이 이 SKIP을 검사로 바꿔야 함",
    )
    report.add("S2/S4/N1/N2", "SKIP", "동의 문구·위탁 근거·처리방침은 문서 검토 항목 — 체크리스트가 사람 검토로 지정")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="기동된 backend 주소 (미지정 시 정적 검사만)")
    parser.add_argument("--log", type=Path, nargs="*", default=[], help="스캔할 서버 로그 파일(들)")
    parser.add_argument("--out", type=Path, help="결과 JSON 저장 경로 (S1-E6 증빙용)")
    args = parser.parse_args()

    report = Report()
    print("── 정적 검사 (코드 불변식) ──")
    check_p1_geolocation(report)
    check_s1_consent_separation(report)

    if args.base_url:
        print("── 라이브 검사 (기동된 스택, HTTP만) ──")
        check_live(report, args.base_url.rstrip("/"), args.log)
    else:
        print("── 라이브 검사: --base-url 미지정으로 건너뜀 ──")
        report.add("P2/P3/P4", "SKIP", "--base-url 미지정 — 스택을 기동하고 다시 실행하세요")

    print("── 자동화 불가 항목 ──")
    add_manual_skips(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(
                {"generatedAt": datetime.now(UTC).isoformat(), "items": report.items},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"보고서: {args.out}")

    if report.failed:
        print("\n결과: FAIL — 위 ❌ 항목을 해결하기 전에는 통과가 아닙니다")
        return 1
    print("\n결과: PASS (SKIP/WARN은 '검사 안 됨'이지 '통과'가 아님 — 항목별 사유 참조)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
