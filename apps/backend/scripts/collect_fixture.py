"""Collect a disaster API response once and freeze it as a fixture.

Usage: python scripts/collect_fixture.py <api_source> <event_type>
  e.g. python scripts/collect_fixture.py kma flood_warning

Calls the real API once, saves fixtures/{source}_{type}_{YYYYMMDD}.json and prints its
sha256. The saved file must never be edited afterwards (see fixtures/README.md).

Note: this script is the *only* development path that touches a real API. Run it with the
keys set in infra/.env, and only after the server IP has been registered.
"""

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from backend_core.config import today_kst

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# The actual call is filled in once keys and endpoints are settled. For now this pins the
# saving, hashing and naming rules so the whole team collects fixtures the same way.


def save_fixture(source: str, event_type: str, payload: dict[str, Any]) -> None:
    name = f"{source}_{event_type}_{today_kst():%Y%m%d}.json"
    path = FIXTURES / name
    if path.exists():
        raise SystemExit(f"이미 존재: {name}. 픽스처는 수정하지 않는다. 새 이름으로 수집할 것.")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    print(f"동결 완료: {name}  sha256[:12]={digest}")
    print("fixtures/README.md 수집 이력 표에 위 해시와 함께 기록할 것.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    print("TODO: API 키 수령 및 엔드포인트 확정 후 호출 로직 구현")
