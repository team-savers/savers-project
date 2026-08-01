"""Fetch the real 국민행동요령 corpus (safetydata.go.kr, DSSP-IF-20588) and snapshot it to CSV.

Requires `SAFETYDATA_ACTION_MANUAL_KEY` (infra/.env). This is the network-calling, non-deterministic
half of corpus prep — kept separate from `build_index.py` (CSV -> Chroma), which stays
deterministic given a fixed CSV.

Usage:
    python scripts/fetch_corpus.py                        # 호우+홍수 (MVP flood target)
    python scripts/fetch_corpus.py --safety-cate 01003     # 호우만
    python scripts/fetch_corpus.py --out src/ai_engine/fixtures/flood_action_manual.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ai_engine.config import get_settings
from ai_engine.ingestion import ROW_FIELDS, fetch_action_manual_rows

# ⚠️ safety_cate 생략 시 API가 조용히 태풍(01001)으로 스코프를 좁힌다(ingestion.py 참고) —
# 기본값을 명시적으로 지정해 그 함정을 피한다. AGENTS.md의 MVP 타겟 "호우·도시침수"는
# 재난유형 코드가 아니라 현상이라, 그 원인이 되는 두 유형(호우, 홍수)을 모두 담는다.
DEFAULT_SAFETY_CATES = ["01003", "01002"]  # 호우, 홍수


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--safety-cate",
        action="append",
        default=None,
        help="반복 지정 가능 (예: --safety-cate 01003 --safety-cate 01002). 기본값: 호우+홍수",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("src/ai_engine/fixtures/flood_action_manual.csv"),
    )
    args = parser.parse_args()

    api_key = get_settings().safetydata_action_manual_key
    if not api_key:
        raise SystemExit("SAFETYDATA_ACTION_MANUAL_KEY not set (infra/.env)")

    rows = fetch_action_manual_rows(api_key, safety_cate=args.safety_cate or DEFAULT_SAFETY_CATES)
    if not rows:
        print("no rows fetched")
        return

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ROW_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
