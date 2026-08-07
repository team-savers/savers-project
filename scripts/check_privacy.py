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
        DB 가 없다(backend_core/registry.py 의 ResidentRegistry). 근거는
        ADR-0007 "해결되지 않은 문제" 표의 **인메모리 상태** 항목(⚠️ 미해결,
        실저장소 교체는 Backend S1-2)이다. 실저장소를 붙이는 PR 이 이 SKIP 을
        검사로 바꿔야 한다.
        ⚠️ 후속_과제.md 4번과 혼동하지 말 것 — 그쪽은 /ops↔/join 을 잇는
        임시 Firestore 릴레이의 접근 통제이고, 여기서 말하는 백엔드 등록
        저장소와는 다른 저장소다(PR #76 리뷰).

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
import time
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


def _blank_comments_and_strings(text: str) -> str:
    """주석과 문자열 리터럴을 같은 길이의 공백으로 바꾼다. 줄 번호는 보존된다.

    줄 앞머리가 주석 기호인지만 보는 방식으로는 세 가지를 놓친다 —
    인라인 주석(`foo(); // getCurrentPosition`), `*` 없이 이어지는 블록주석
    연속행, 문자열 리터럴 안의 언급. 그 셋이 다 "호출"로 잡히면 실제 위반이
    아닌데 FAIL 이 나서 리뷰를 막는다(PR #76 리뷰).

    완전한 TS 파서가 목표가 아니다. 목표는 "식별자가 코드 위치에 있는가"를
    가르는 것이고, 그러려면 주석·문자열만 비우면 충분하다. 알려진 한계:
    `//` 를 포함한 정규식 리터럴(예: `/a\\/\\/b/`)은 주석 시작으로 오인될 수
    있다 — 이 저장소에 그런 패턴은 없고, 오인 방향이 "덜 검사"가 아니라
    "그 줄을 비움"이라 미탐이 되므로, 실제로 쓰이면 정규식을 고치는 쪽이 맞다.
    """
    out = list(text)
    i, n = 0, len(text)
    state: str | None = None  # None | 'line' | 'block' | '"' | "'" | '`'
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if state is None:
            if ch == "/" and nxt == "/":
                state, out[i], out[i + 1] = "line", " ", " "
                i += 2
                continue
            if ch == "/" and nxt == "*":
                state, out[i], out[i + 1] = "block", " ", " "
                i += 2
                continue
            if ch in ('"', "'", "`"):
                state, out[i] = ch, " "
                i += 1
                continue
            i += 1
            continue
        if state == "line":
            if ch == "\n":
                state = None
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block":
            if ch == "*" and nxt == "/":
                state, out[i], out[i + 1] = None, " ", " "
                i += 2
                continue
            if ch != "\n":
                out[i] = " "
            i += 1
            continue
        # 문자열 리터럴 안. 이스케이프는 다음 문자까지 함께 삼킨다 —
        # `"\""` 의 가운데 따옴표를 종료로 오인하지 않기 위해서다.
        if ch == "\\":
            out[i] = " "
            if i + 1 < n and text[i + 1] != "\n":
                out[i + 1] = " "
            i += 2
            continue
        if ch == state:
            state, out[i] = None, " "
            i += 1
            continue
        if ch != "\n":
            out[i] = " "
        i += 1
    return "".join(out)


def check_p1_geolocation(report: Report) -> None:
    """P1: 위치 조회는 동의 분기 파일 안에만, 상시 추적 API 는 0건."""
    offenders: list[str] = []
    watch_hits: list[str] = []
    for path in FRONTEND_SRC.rglob("*.ts*"):
        rel = path.relative_to(FRONTEND_SRC).as_posix()
        # 주석·문자열을 비운 사본에서 찾는다 — 언급과 호출을 가르기 위해서다.
        code = _blank_comments_and_strings(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), start=1):
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
            "S1-model",
            "FAIL",
            f"분리 동의 필드 누락: {sorted(required - fields)} (있는 것: {sorted(fields)})",
        )

    ops_tsx = (FRONTEND_SRC / "pages" / "Ops.tsx").read_text(encoding="utf-8")
    if "분리동의" in ops_tsx and "declineNote" in ops_tsx:
        report.add(
            "S1-ui", "PASS", "/ops 등록 화면에 항목별 분리동의 UI 상수 존재 (필수/선택 구분 포함)"
        )
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
            return (
                resp.status,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.read().decode(),
            )
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read().decode()
    except (urllib.error.URLError, TimeoutError) as err:
        # 연결 거부·DNS 실패·타임아웃. 트레이스백으로 죽는 대신 상태 0으로 돌려
        # 호출부가 FAIL 로 보고하게 한다 — --base-url 을 잘못 준 경우가 흔하다.
        return 0, {}, str(err)


# 라이브 구간에서 보고해야 하는 항목 전체. 조기 반환 시 아직 보고되지 않은
# 항목을 SKIP 으로 채우는 데 쓴다 — "못 잰 것은 통과가 아니다"를 리포트에서도
# 지키려면 항목이 조용히 빠지는 게 아니라 SKIP 으로 보여야 한다(PR #76 리뷰).
LIVE_CHECKS = ("P2-cache", "P2-echo", "P2-state", "P2-logs", "P3-erasure", "P4-audit")

# 센티널 요청의 접근 기록이 로그 파일에 도달할 때까지 기다리는 한도.
# docker compose logs -f 로 흘려 쓰는 경우 파이프 버퍼 때문에 수백 ms 지연이
# 생길 수 있어, 즉시 판정하면 "내 요청이 없다"는 오탐이 난다.
LOG_ARRIVAL_TRIES = 20
LOG_ARRIVAL_INTERVAL_S = 0.5
# 대피소 검색 접근 기록을 세는 기준. uvicorn 기본 접근 로그가 경로를 그대로
# 남긴다(실측 확인: `"POST /v1/shelters/search HTTP/1.1" 200`).
SEARCH_ACCESS_MARK = "/v1/shelters/search"


def _read_logs(log_paths: list[Path]) -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in log_paths)


def _skip_remaining(report: Report, reason: str) -> None:
    reported = {item["check"] for item in report.items}
    for check in LIVE_CHECKS:
        if check not in reported:
            report.add(check, "SKIP", reason)


def check_live(report: Report, base_url: str, log_paths: list[Path]) -> None:
    """P2/P3/P4: 센티널 좌표를 흘려보내고 어디에도 남지 않는지 확인."""
    # ⚠️ 센티널 요청을 보내기 **전에** 로그 줄 수를 센다. 요청 후 이 수가 늘지
    # 않으면 검사 대상이 파일에 없다는 뜻이고, 그 상태의 "좌표 없음"은 증거가
    # 아니다 — 스냅샷 로그를 검사하면 정확히 그 일이 벌어진다(PR #76 리뷰).
    search_lines_before = _read_logs(log_paths).count(SEARCH_ACCESS_MARK) if log_paths else 0

    status, _, dispatch_body = _http("POST", f"{base_url}/internal/alerts/dispatch")
    if status != 200:
        report.add("P2-nostore", "FAIL", f"dispatch가 {status} — 스택이 정상 기동됐는지 확인 필요")
        _skip_remaining(report, "dispatch 실패로 센티널 요청을 보내지 못함 — 위 P2-nostore 참조")
        return
    deliveries = json.loads(dispatch_body)["deliveries"]
    if not deliveries:
        report.add("P2-nostore", "FAIL", "배송 결과 0건 — 시드 주민 매칭 실패")
        _skip_remaining(report, "배송 0건으로 검사할 세션이 없음 — 위 P2-nostore 참조")
        return
    delivery = deliveries[0]
    token = delivery["sessionToken"]

    # 센티널 좌표로 검색 — [밖이에요] 경로에서 실좌표가 들어오는 그 요청이다.
    status, headers, search_body = _http(
        "POST",
        f"{base_url}/v1/shelters/search",
        {
            "sessionToken": token,
            "dongCode": "1162064500",
            "lat": float(SENTINEL_LAT),
            "lng": float(SENTINEL_LNG),
        },
    )
    if status != 200:
        report.add("P2-nostore", "FAIL", f"좌표 포함 검색이 {status} — 검사를 진행할 수 없음")
        _skip_remaining(report, "센티널 검색이 실패해 흘려보낸 좌표가 없음 — 위 P2-nostore 참조")
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
        report.add(
            "P2-state", "PASS", "검색 후 세션·보호자 재조회에 좌표 없음 (세션 범위 밖 미저장)"
        )

    # 로그 스캔 — 카나리아 없이는 통과로 세지 않는다.
    #
    # ⚠️ 카나리아는 "이 경로가 로그에 있는가"가 아니라 "**내 센티널 요청**이
    # 로그에 추가됐는가"다. 앞의 것으로는 다른 주체(예: 앞서 돌아간 E2E 테스트)가
    # 남긴 같은 경로 줄로 통과해버리고, 그러면 정작 검사 대상인 내 요청의 줄은
    # 파일에 없는 채로 "좌표 없음 = 통과"가 된다 — 스냅샷 로그를 검사하면 반드시
    # 그 일이 벌어진다(PR #76 리뷰에서 확인된 실제 결함).
    log_canary_ok = False
    if not log_paths:
        report.add(
            "P2-logs", "WARN", "--log 미지정 — 서버 로그의 좌표 부재는 이번 실행에서 검사되지 않음"
        )
    else:
        # 접근 기록이 파일에 도달할 때까지 기다린다 — 흘려 쓰는 경우 지연이 있다.
        log_text = _read_logs(log_paths)
        for _ in range(LOG_ARRIVAL_TRIES):
            if log_text.count(SEARCH_ACCESS_MARK) > search_lines_before:
                break
            time.sleep(LOG_ARRIVAL_INTERVAL_S)
            log_text = _read_logs(log_paths)
        search_lines_after = log_text.count(SEARCH_ACCESS_MARK)
        leaked = [f for f in SENTINEL_FRAGMENTS if f in log_text]
        if search_lines_after <= search_lines_before:
            report.add(
                "P2-logs",
                "FAIL",
                f"내 센티널 요청의 접근 기록이 로그에 나타나지 않음 "
                f"(요청 전 {search_lines_before}줄 → {LOG_ARRIVAL_TRIES}회 재시도 후 "
                f"{search_lines_after}줄). 얼어붙은 스냅샷을 검사하고 있거나"
                "(`docker compose logs` 를 `-f` 없이 떠서 파일이 더 자라지 않는 경우) "
                "접근 로그가 꺼져 있음. 이 상태의 '좌표 없음'은 증거가 아님",
            )
        elif leaked:
            report.add(
                "P2-logs",
                "FAIL",
                f"서버 로그에 원본 좌표 발견 (조각 {leaked}): {[str(p) for p in log_paths]}",
            )
        else:
            log_canary_ok = True
            report.add(
                "P2-logs",
                "PASS",
                f"내 센티널 요청이 로그에 도달했고(검색 기록 {search_lines_before}→"
                f"{search_lines_after}줄) 그 로그에 좌표는 없음",
            )

    # P3: 저장이 없으면 파기할 대상도 없다 — P2 계열이 전부 통과일 때만 유도.
    p2_all_pass = all(i["status"] == "PASS" for i in report.items if i["check"].startswith("P2-"))
    if p2_all_pass:
        report.add(
            "P3-erasure",
            "PASS",
            "설계상 충족 — 저장 자체가 없음이 확인되어 철회 시 파기 대상이 없음 (P2에서 유도)",
        )
    else:
        report.add("P3-erasure", "SKIP", "P2가 전부 통과일 때만 유도 가능 — 위 결과 참조")

    # P4: 좌표 없는 접근 기록(사실 확인자료). 전용 감사 로그는 미구현.
    # P2-logs 가 통과했을 때만 판단한다 — 그때만 "내 조회가 좌표 없이 기록됐다"가
    # 확인된 상태이고, 그게 사실 확인자료가 갖춰야 할 성질이다.
    if log_canary_ok:
        report.add(
            "P4-audit",
            "WARN",
            "접근 로그가 좌표 없이 조회 사실을 남기고 있음 — 다만 위치정보법 제16조제2항의 "
            "법정 보관 기간을 갖춘 전용 감사 로그는 미구현 (실서비스 전 설계 필요)",
        )
    else:
        report.add("P4-audit", "SKIP", "P2-logs가 통과하지 않아 판단 불가 — 위 결과 참조")


def add_manual_skips(report: Report) -> None:
    report.add(
        "S3-encryption",
        "SKIP",
        "등록 저장소(backend_core/registry.py ResidentRegistry)가 인메모리라 스캔할 DB 없음 "
        "— 근거는 ADR-0007 '해결되지 않은 문제' 표의 인메모리 상태 항목(미해결). 실저장소를 "
        "붙이는 PR이 이 SKIP을 검사로 바꿔야 함. 후속_과제.md 4번(Firestore 릴레이 접근 통제)과 "
        "는 다른 저장소다",
    )
    report.add(
        "S2/S4/N1/N2",
        "SKIP",
        "동의 문구·위탁 근거·처리방침은 문서 검토 항목 — 체크리스트가 사람 검토로 지정",
    )


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
