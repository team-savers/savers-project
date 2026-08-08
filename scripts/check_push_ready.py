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
  3. 앱 config — Firebase 웹앱 설정 6종이 번들에 박혀 있는지.
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
import re
import sys
import urllib.error
import urllib.request

# Firebase 웹앱 config 흔적. 값은 절대 출력하지 않고 형태만 본다.
#   authDomain 은 항상 `<project>.firebaseapp.com` 이고, 브라우저 API 키는
#   `AIza` 로 시작하는 39자다. 둘 중 하나라도 없으면 config 가 비어 있다.
AUTH_DOMAIN_RE = re.compile(r"[A-Za-z0-9-]+\.firebaseapp\.com")
API_KEY_RE = re.compile(r"AIza[A-Za-z0-9_-]{30,40}")
# 웹푸시 VAPID 공개키: uncompressed P-256 점을 base64url 로 담아 87~88자,
# 항상 'B' 로 시작한다. 번들의 다른 긴 문자열과 겹치지 않는 형태다.
VAPID_RE = re.compile(r"\bB[A-Za-z0-9_-]{85,87}\b")
BUNDLE_RE = re.compile(r"/assets/[A-Za-z0-9._-]+\.js")

TIMEOUT_S = 25


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
    except (urllib.error.URLError, TimeoutError) as err:
        return 0, {}, f"{err}", url


def check_reachable(report: Report, base: str) -> str | None:
    """도달성 + HTTPS. 번들을 읽을 수 있으면 그 본문을 돌려준다."""
    if base.startswith("http://") and not base.startswith(("http://localhost", "http://127.")):
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
        return None
    # 접근 보호(SSO)가 걸리면 로그인 페이지로 끌려간다 — 실기기에서 열 수 없다.
    if "vercel.com/login" in final or "/sso-api" in final:
        report.add(
            "reachable",
            "FAIL",
            "배포본이 접근 보호(로그인) 뒤에 있습니다 — 실기기 브라우저에서 열 수 없어 "
            "캡처가 불가능합니다. 프로덕션 배포를 쓰거나 해당 배포의 보호를 해제하세요",
        )
        return None
    if status != 200:
        report.add("reachable", "FAIL", f"배포 주소가 {status} 를 반환했습니다")
        return None

    match = BUNDLE_RE.search(body)
    if match is None:
        report.add(
            "reachable",
            "FAIL",
            "index.html 에서 번들(/assets/*.js) 참조를 찾지 못했습니다 — 빌드 산출물이 "
            "아니거나 다른 앱이 서비스되고 있습니다",
        )
        return None

    bundle_url = f"{base}{match.group(0)}"
    b_status, _, bundle, _ = fetch(bundle_url)
    if b_status != 200 or not bundle:
        report.add("reachable", "FAIL", f"번들을 읽을 수 없습니다({b_status}): {match.group(0)}")
        return None

    report.add(
        "reachable",
        "PASS",
        f"배포본 도달·번들 조회 성공 ({match.group(0)}, {len(bundle) // 1024}KB)",
    )
    return bundle


def check_firebase_config(report: Report, bundle: str) -> None:
    """앱 config 6종 + VAPID. 값은 출력하지 않고 존재만 본다."""
    has_domain = AUTH_DOMAIN_RE.search(bundle) is not None
    has_key = API_KEY_RE.search(bundle) is not None
    if has_domain and has_key:
        report.add("firebase-config", "PASS", "Firebase 웹앱 config 가 번들에 포함됨 (값 미출력)")
    else:
        missing = [
            name
            for name, present in (("authDomain", has_domain), ("apiKey", has_key))
            if not present
        ]
        report.add(
            "firebase-config",
            "FAIL",
            f"Firebase config 가 번들에 없습니다 (누락 흔적: {', '.join(missing)}). "
            "VITE_FIREBASE_* 6종을 호스팅 환경변수에 넣고 **다시 빌드**해야 합니다 — "
            "값만 저장하고 재배포하지 않으면 번들은 그대로입니다",
        )

    if VAPID_RE.search(bundle) is not None:
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
            f"/sw.js 를 받을 수 없습니다({status}) — 백그라운드 수신 경로가 없습니다",
        )
        return

    notes: list[str] = []
    if headers.get("service-worker-allowed") != "/":
        notes.append("Service-Worker-Allowed 헤더가 '/' 가 아님(스코프 제한)")
    cache = headers.get("cache-control", "")
    if "max-age=0" not in cache and "no-cache" not in cache and "must-revalidate" not in cache:
        notes.append(f"캐시 헤더가 재검증을 강제하지 않음({cache!r}) — 낡은 워커가 남을 수 있음")

    if notes:
        report.add("service-worker", "WARN", f"/sw.js 는 서비스되지만: {'; '.join(notes)}")
    else:
        report.add("service-worker", "PASS", "/sw.js 서비스 + 스코프·캐시 헤더 정상")

    # 백그라운드 수신도 config 를 필요로 한다 — 워커 번들에 함께 박혀야 한다.
    if AUTH_DOMAIN_RE.search(body) is None and API_KEY_RE.search(body) is None:
        report.add(
            "service-worker-config",
            "FAIL",
            "/sw.js 에 Firebase config 가 없습니다 — 앱이 화면에 떠 있을 때만 알림이 보이고 "
            "**닫혀 있을 때(백그라운드) 수신이 안 됩니다.** 캡처하려는 잠금화면 알림이 "
            "정확히 이 경로입니다",
        )
    else:
        report.add("service-worker-config", "PASS", "/sw.js 에 config 포함 — 백그라운드 수신 가능")


def check_manifest(report: Report, base: str) -> None:
    status, _, _, _ = fetch(f"{base}/manifest.webmanifest")
    if status == 200:
        report.add("manifest", "PASS", "매니페스트 서비스됨 — iOS 홈 화면 추가(A2HS) 전제 충족")
    else:
        report.add(
            "manifest",
            "WARN",
            f"매니페스트를 받을 수 없습니다({status}) — 안드로이드 검증에는 영향이 없지만 "
            "iOS 는 A2HS 상태에서만 웹푸시가 동작하므로 iOS 경로가 막힙니다",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "url", help="배포된 프론트엔드 주소 (예: https://savers-project.vercel.app)"
    )
    args = parser.parse_args()
    base = args.url.rstrip("/")

    print(f"── 대상: {base} ──")
    report = Report()
    bundle = check_reachable(report, base)
    if bundle is not None:
        check_firebase_config(report, bundle)
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
