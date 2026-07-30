"""재난 API 응답을 1회 수집해 픽스처로 동결한다.

Freezing rules — why this is a script and not a manual curl:

- **The saved file is the unparsed upstream response.** Any 3시간 합산이나 범주 문자열
  해석은 소비자 쪽 로직이고, 그것을 여기서 적용하면 "관측한 것"이어야 할 파일에 파생값이
  섞인다. 픽스처가 가공되면 그 뒤의 어떤 측정도 상류를 근거로 삼지 못한다.
- **A fixture is never overwritten.** 같은 이름으로 다시 수집하는 것은 거부한다. 이미
  누군가 그 파일을 근거로 판단한 뒤에 내용이 조용히 바뀌는 것이 픽스처의 최악 실패다.
- **요청 URL과 서비스키는 저장 파일·표준출력·예외 어디에도 넣지 않는다.** 이 저장소는
  공개이고, 픽스처는 키가 숨어 들어가기 가장 쉬운 자리다.

수집한 파일은 fixtures/README.md의 이력 표에 sha256과 함께 기록할 것.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
