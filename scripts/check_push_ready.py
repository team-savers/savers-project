"""배포본이 실기기 웹푸시 검증을 할 수 있는 상태인지 판정한다 (S1-E7 선행 점검).

**이 스크립트가 있는 이유.** 웹푸시가 안 오는 이유는 코드가 아니라 대개
"배포 빌드에 키가 안 들어갔다"입니다. Vite는 `VITE_*` 값을 **빌드 시점에
번들에 박기** 때문에, 호스팅 대시보드에 값을 넣어도 **다시 빌드하지 않으면
반영되지 않습니다.** 그 상태를 눈으로 구분할 방법이 없어서
"권한을 줬는데 알림이 안 와요"로만 드러납니다 — 실기기를 붙잡고 디버깅할
일이 아니라 배포본을 한 번 조회하면 끝나는 문제입니다.

판정 대상(전부 원격 HTTP 조회 — 저장소 코드를 보지 않습니다):

  1. 도달성   — 배포 URL이 200이고 로그인 리다이렉트가 아닌지.
                프리뷰 배포에 접근 보호가 걸려 있으면 **실기기 브라우저에서
                열 수 없어** 캡처 자체가 불가능합니다.
  2. HTTPS    — 웹푸시는 localhost를 제외하면 HTTPS가 필수입니다.
  3. 앱 config — Firebase 웹앱 설정이 번들에 박혀 있는지. 앱 쪽
                `isFirebaseConfigured()`가 6종을 **전부** 요구하므로, 여기서도
                일부만 보고 통과시키지 않습니다(아래 CONFIG_MARKERS 주석 참고).
  4. VAPID    — 웹푸시 공개키가 번들에 박혀 있는지. 이것만 빠져도 토큰
                발급이 `misconfigured`로 끝나 알림이 한 통도 가지 않습니다.
  5. 서비스워커 — `sw.js`가 서비스되고, 스코프 헤더와 캐시 헤더가 맞는지.
                  FCM 백그라운드 수신이 이 파일에 있습니다.
  6. 매니페스트 — iOS는 홈 화면 추가(A2HS) 상태에서만 웹푸시가 동작하므로
                  매니페스트가 없으면 iOS 경로가 처음부터 막힙니다.

⚠️ **비밀값을 출력하지 않습니다.** 존재 여부만 판정합니다. 이 스크립트의
출력은 그대로 공유해도 안전합니다.

⚠️ 이 스크립트가 전부 통과해도 "알림이 실제로 왔다"는 뜻은 아닙니다.
발송 측(백엔드 Admin SDK 자격증명)과 수신 측(기기 권한 허용)은 여기서 알 수
없습니다. **필요조건만 봅니다** — 통과하면 실기기 검증을 시작할 수 있고,
실패하면 실기기를 켜기 전에 고칠 것이 있다는 뜻입니다.

실행:
    python3 scripts/check_push_ready.py https://<배포주소>

종료 코드: FAIL 이 하나라도 있으면 1, 아니면 0 (WARN 은 실패가 아님).
"""

from __future__ import annotations

import argparse
import http.client
import re
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

# Firebase 웹앱 config 흔적. 값은 절대 출력하지 않고 형태만 본다.
#   authDomain 은 항상 `<project>.firebaseapp.com` 이고, 브라우저 API 키는
#   `AIza` 로 시작하는 39자다.
AUTH_DOMAIN_RE = re.compile(r"[A-Za-z0-9-]+\.firebaseapp\.com")
API_KEY_RE = re.compile(r"AIza[A-Za-z0-9_-]{30,40}")
#   appId 는 `1:<messagingSenderId>:web:<hex>` 형태다 — 이 하나로 senderId 까지
#   함께 확인된다. storageBucket 은 프로젝트 생성 시기에 따라 두 도메인 중 하나다.
APP_ID_RE = re.compile(r"1:\d{6,}:web:[0-9a-f]{6,}")
STORAGE_RE = re.compile(r"[a-z0-9][a-z0-9-]*\.(?:appspot\.com|firebasestorage\.app)")
# 웹푸시 VAPID 공개키: uncompressed P-256 점(65바이트)을 base64url 로 담아 **항상 87자**,
# 'B' 로 시작한다. 길이를 범위로 두면 번들 안의 긴 base64url 블롭에서 `-` 뒤 경계가
# 우연히 맞아 오탐한다(실측: 무작위 4000자 블롭 200개 중 10건). 87자로 못박는다.
# ⚠️ `\b` 를 쓰면 안 된다. base64url 의 `-` 는 비단어 문자라, 키가 `-` 로 끝나면
#    뒤따르는 따옴표와의 사이에 단어 경계가 서지 않아 **진짜 키를 놓친다**(약 1/64).
#    앞뒤로 base64url 문자가 아닌 것만 요구하는 lookaround 가 양방향 모두 정확하다.
VAPID_RE = re.compile(r"(?<![A-Za-z0-9_-])B[A-Za-z0-9_-]{86}(?![A-Za-z0-9_-])")
BUNDLE_RE = re.compile(r"/assets/[A-Za-z0-9._-]+\.js")

# 웹푸시가 HTTPS 없이 허용되는 예외. 접두어 비교(`startswith("http://127.")`)로 두면
# `http://127.evil.com` 같은 외부 호스트가 로컬로 통과한다 — 호스트명을 정확히 대조한다.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# ⚠️ Firebase JS SDK 가 번들에 **항상** 넣는 DEFAULT_VAPID_KEY 상수다.
#    걸러내지 않으면 firebase/messaging 을 import 하는 모든 빌드가 무조건 PASS 한다 —
#    키를 한 번도 주입하지 않은 배포본까지 초록으로 나와, 이 스크립트가 막으려던
#    "필요조건이 빠졌는데 초록" 을 스스로 만든다 (PR #81 리뷰).
SDK_DEFAULT_VAPID = (
    "BDOU99-h67HcA6JeFXHbSNMu7e2yNNu3RzoMj8TM4W88jITfq7ZmPvIM1Iv-4_l2LxQcYwhqby2xGpWwzjfAnG4"
)

# 판정에 쓰는 config 흔적. 앱의 isFirebaseConfigured() 는 6종을 전부 요구하는데,
# projectId 는 authDomain 의 앞부분이고 messagingSenderId 는 appId 의 가운데
# 세그먼트라, 아래 4개로 6종 전부를 사실상 덮는다. 일부만 들어간 빌드는 화면에
# 오류가 없고 콘솔 경고만 남으므로, 여기서 잡지 못하면 실기기에서 드러난다.
CONFIG_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("authDomain", AUTH_DOMAIN_RE),
    ("apiKey", API_KEY_RE),
    ("appId", APP_ID_RE),
    ("storageBucket", STORAGE_RE),
)

TIMEOUT_S = 25


def missing_config_markers(source: str) -> list[str]:
    """없는 config 흔적의 **이름**만 돌려준다. 값은 어떤 경우에도 돌려주지 않는다."""
    return [name for name, pattern in CONFIG_MARKERS if pattern.search(source) is None]


def has_vapid_key(source: str) -> bool:
    """SDK 내장 기본키를 제외한 VAPID 공개키가 들어 있는지."""
    return any(key != SDK_DEFAULT_VAPID for key in VAPID_RE.findall(source))


class Report:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, str]] = []

    def add(self, check: str, status: str, detail: str) -> None:
        self.items.append((check, status, detail))
        mark = {"PASS": "✅", "FAIL": "❌", "WARN": "⚠️ "}[status]
        print(f"{mark} {status:4} {check} — {detail}")

    @property
    def failed(self) -> bool:
        return any(s == "FAIL" for _, s, _ in self.items)


def fetch(url: str) -> tuple[int, dict[str, str], str, str]:
    """(status, headers, body, final_url). 실패는 예외 대신 상태 코드로 돌려준다."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"http(s) URL만 허용: {url}")

    # 스킴 검증을 위에서 했으므로 file:// 등이 들어올 수 없다 — 아래 두 줄의 S310 억제 근거.
    req = urllib.request.Request(url, headers={"User-Agent": "savers-push-ready-check"})  # noqa: S310
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - 위에서 스킴 검증
            return (
                resp.status,
                {k.lower(): v for k, v in resp.headers.items()},
                resp.read().decode("utf-8", errors="replace"),
                resp.geturl(),
            )
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, "", url
    # ⚠️ URLError/TimeoutError 만 잡으면 부족하다. 응답을 받기 시작한 뒤 연결이 끊기면
    #    resp.read() 가 ConnectionResetError·IncompleteRead·RemoteDisconnected 로 죽는데,
    #    셋 다 URLError 가 아니라 판정이 트레이스백으로 끝난다 — 남은 검사도, 종료 코드도
    #    사라진다. OSError(=URLError·TimeoutError·소켓 오류의 상위)와 HTTPException 을
    #    함께 잡아 "실패는 예외가 아니라 status 0" 이라는 이 함수의 계약을 지킨다.
    except (OSError, http.client.HTTPException) as err:
        return 0, {}, f"{type(err).__name__}: {err}", url


def is_local(url: str) -> bool:
    """localhost 예외 판정. 접두어 비교는 `http://127.evil.com` 을 통과시킨다 — 호스트를 파싱한다."""
    return (urlsplit(url).hostname or "").lower() in LOCAL_HOSTS


def why(status: int, body: str) -> str:
    """실패 사유 표기.

    두 경우가 그냥 코드만 찍으면 오독된다.
      - status 0 은 HTTP 코드가 아니라 접속 실패다. 원인을 대신 싣는다.
      - 200 인데 본문이 비어 있으면 실패 사유가 "HTTP 200(성공)" 으로 표시된다.
        실패 줄에 성공 코드가 찍히는 셈이라 읽는 사람이 멈춘다.
    """
    if status == 0:
        return f"접속 실패: {body}"
    if status == 200 and not body:
        return "HTTP 200 이지만 본문이 비어 있음"
    return f"HTTP {status}"


def check_reachable(report: Report, base: str) -> tuple[bool, str | None]:
    """도달성 + HTTPS. (호스트에 닿았는가, 번들 본문) 을 돌려준다.

    두 값을 나누는 이유: 번들을 못 읽는 것과 호스트에 못 닿는 것은 다른 사건이다.
    전자는 config 판정만 불가능할 뿐 서비스워커·매니페스트는 그대로 확인할 수 있다.
    """
    if base.startswith("http://") and not is_local(base):
        report.add(
            "https",
            "FAIL",
            "배포 주소가 http 입니다 — 웹푸시는 localhost 외에서 HTTPS 가 필수라 "
            "권한 요청 자체가 브라우저에서 차단됩니다",
        )
    else:
        report.add("https", "PASS", "HTTPS(또는 localhost) — 웹푸시 전제 충족")

    status, _, body, final = fetch(f"{base}/")
    if status == 0:
        report.add("reachable", "FAIL", f"배포 주소에 접속할 수 없습니다: {body}")
        # 호스트 자체에 못 닿았다 — /sw.js·매니페스트도 같은 결과일 뿐이라 더 묻지 않는다.
        return False, None
    # 접근 보호(SSO)가 걸리면 로그인 페이지로 끌려간다 — 실기기에서 열 수 없다.
    if "vercel.com/login" in final or "/sso-api" in final:
        report.add(
            "reachable",
            "FAIL",
            "배포본이 접근 보호(로그인) 뒤에 있습니다 — 실기기 브라우저에서 열 수 없어 "
            "캡처가 불가능합니다. 프로덕션 배포를 쓰거나 해당 배포의 보호를 해제하세요",
        )
        return True, None
    if status != 200:
        report.add("reachable", "FAIL", f"배포 주소가 {status} 를 반환했습니다")
        return True, None

    match = BUNDLE_RE.search(body)
    if match is None:
        report.add(
            "reachable",
            "FAIL",
            "index.html 에서 번들(/assets/*.js) 참조를 찾지 못했습니다 — 빌드 산출물이 "
            "아니거나 다른 앱이 서비스되고 있습니다",
        )
        return True, None

    bundle_url = f"{base}{match.group(0)}"
    b_status, _, bundle, _ = fetch(bundle_url)
    if b_status != 200 or not bundle:
        report.add(
            "reachable",
            "FAIL",
            f"번들을 읽을 수 없습니다({why(b_status, bundle)}): {match.group(0)}",
        )
        return True, None

    report.add(
        "reachable",
        "PASS",
        f"배포본 도달·번들 조회 성공 ({match.group(0)}, {len(bundle) // 1024}KB)",
    )
    return True, bundle


def check_firebase_config(report: Report, bundle: str) -> None:
    """앱 config 6종 + VAPID. 값은 출력하지 않고 존재만 본다."""
    missing = missing_config_markers(bundle)
    if not missing:
        report.add("firebase-config", "PASS", "Firebase 웹앱 config 가 번들에 포함됨 (값 미출력)")
    else:
        report.add(
            "firebase-config",
            "FAIL",
            f"번들의 Firebase config 가 불완전합니다 (누락 흔적: {', '.join(missing)}). "
            "VITE_FIREBASE_* 6종을 호스팅 환경변수에 넣고 **다시 빌드**해야 합니다 — "
            "값만 저장하고 재배포하지 않으면 번들은 그대로입니다",
        )

    if has_vapid_key(bundle):
        report.add("vapid", "PASS", "웹푸시 공개키(VAPID)가 번들에 포함됨 (값 미출력)")
    else:
        report.add(
            "vapid",
            "FAIL",
            "VAPID 공개키가 번들에 없습니다 — 토큰 발급이 misconfigured 로 끝나 알림이 "
            "한 통도 가지 않습니다. Firebase 콘솔 → Cloud Messaging → 웹 푸시 인증서에서 "
            "키 쌍을 만들고 VITE_FIREBASE_VAPID_KEY 로 넣으세요",
        )


def check_service_worker(report: Report, base: str) -> None:
    status, headers, body, _ = fetch(f"{base}/sw.js")
    if status != 200 or not body:
        report.add(
            "service-worker",
            "FAIL",
            f"/sw.js 를 받을 수 없습니다({why(status, body)}) — 백그라운드 수신 경로가 없습니다",
        )
        return

    notes: list[str] = []
    if headers.get("service-worker-allowed") != "/":
        notes.append("Service-Worker-Allowed 헤더가 '/' 가 아님(스코프 제한)")
    # no-store 는 "캐시에 넣지도 말라" 로 재검증보다 강한 지시다 — 빠뜨리면 가장 안전한
    # 설정에 대고 "낡은 워커가 남을 수 있음" 이라고 잘못 경고한다.
    cache = headers.get("cache-control", "")
    if not any(d in cache for d in ("no-store", "no-cache", "max-age=0", "must-revalidate")):
        notes.append(f"캐시 헤더가 재검증을 강제하지 않음({cache!r}) — 낡은 워커가 남을 수 있음")

    if notes:
        report.add("service-worker", "WARN", f"/sw.js 는 서비스되지만: {'; '.join(notes)}")
    else:
        report.add("service-worker", "PASS", "/sw.js 서비스 + 스코프·캐시 헤더 정상")

    # 백그라운드 수신도 config 를 필요로 한다 — 워커 번들에 함께 박혀야 한다.
    # ⚠️ 판정 기준을 check_firebase_config 와 **같게** 둔다(하나라도 없으면 FAIL).
    #    "전부 없을 때만 FAIL" 로 두면, 이 스크립트가 존재하는 이유인 half-config
    #    (authDomain 은 들어갔는데 apiKey 가 빠진 상태)를 서비스워커 쪽에서만
    #    통과시킨다 — 같은 사고를 반쪽만 잡는 셈이다 (PR #81 리뷰, 안은남).
    #    두 곳이 같은 CONFIG_MARKERS 를 쓰므로 기준이 갈라질 수 없다.
    sw_missing = missing_config_markers(body)
    if not sw_missing:
        report.add("service-worker-config", "PASS", "/sw.js 에 config 포함 — 백그라운드 수신 가능")
    else:
        missing = ", ".join(sw_missing)
        report.add(
            "service-worker-config",
            "FAIL",
            f"/sw.js 의 Firebase config 가 불완전합니다 (누락: {missing}) — 앱이 화면에 떠 "
            "있을 때만 알림이 보이고 **닫혀 있을 때(백그라운드) 수신이 안 됩니다.** "
            "캡처하려는 잠금화면 알림이 정확히 이 경로입니다",
        )


def check_manifest(report: Report, base: str) -> None:
    status, _, body, _ = fetch(f"{base}/manifest.webmanifest")
    if status == 200:
        report.add("manifest", "PASS", "매니페스트 서비스됨 — iOS 홈 화면 추가(A2HS) 전제 충족")
    else:
        report.add(
            "manifest",
            "WARN",
            f"매니페스트를 받을 수 없습니다({why(status, body)}) — 안드로이드 검증에는 영향이 없지만 "
            "iOS 는 A2HS 상태에서만 웹푸시가 동작하므로 iOS 경로가 막힙니다",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url", help="배포된 프론트엔드 주소 (예: https://savers-project.vercel.app)"
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")
    # 스킴이 없으면 아래 https 판정이 "http:// 로 시작하지 않으니 HTTPS" 로 오판한 뒤
    # fetch 가 ValueError 로 죽는다. 판정을 시작하기 전에 사용법 오류로 끊는다.
    if not base.startswith(("http://", "https://")):
        parser.error(f"URL 은 http:// 또는 https:// 로 시작해야 합니다: {base}")

    print(f"── 대상: {base} ──")
    report = Report()
    # 항목들은 서로 독립이다. 번들을 못 읽었다고 서비스워커·매니페스트까지 침묵하면
    # "왜 실패했는지" 가 오히려 좁아진다 — 판정 가능한 것은 끝까지 판정한다.
    host_up, bundle = check_reachable(report, base)
    if bundle is not None:
        check_firebase_config(report, bundle)
    else:
        report.add(
            "firebase-config·vapid",
            "WARN",
            "번들을 읽지 못해 판정하지 못했습니다 — 위 reachable 실패를 먼저 해결하세요",
        )
    if host_up:
        check_service_worker(report, base)
        check_manifest(report, base)

    print()
    if report.failed:
        print("결과: 실기기 검증을 시작할 수 없습니다 — 위 ❌ 를 먼저 해결하세요.")
        print("      환경변수를 넣은 뒤에는 **반드시 재배포**해야 번들에 반영됩니다.")
        return 1
    print("결과: 실기기 검증 전제 충족 — 캡처 절차를 진행할 수 있습니다.")
    print("      (발송 측 자격증명과 기기 권한 허용은 이 스크립트가 알 수 없습니다.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
