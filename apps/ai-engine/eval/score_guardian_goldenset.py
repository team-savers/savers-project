"""보호자 응답 골든셋 40건 + 적대 회귀 12건 채점 스크립트.

`metrics.guardian_violations` / `metrics.guardian_accuracy` (M2)에 직접 물린다 — 이 파일은
새 검증 로직을 추가하지 않는다. 골든셋은 `apps/ai-engine/src/ai_engine/guardian_log_qa.py`
(실제 구현)를 호출해서 만들지 않았다 — 구현자가 자기 채점을 만들면 편향이라는 07절 원칙을
지키기 위해, ADR-0012 규칙과 계약(`openapi.yaml` UserActionEventType) 16종만 보고 독립적으로
작성했다.

실행:
    cd apps/ai-engine/eval
    python score_guardian_goldenset.py              # 정답 40건 채점
    python score_guardian_goldenset.py --adversarial # 적대 12건도 함께 채점
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import metrics

GOLDEN_DIR = Path(__file__).parent / "golden_dataset"
MAIN_SET = GOLDEN_DIR / "guardian_v0.jsonl"
ADVERSARIAL_SET = GOLDEN_DIR / "guardian_adversarial_v0.jsonl"


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_main(cases: list[dict]) -> tuple[float | None, list[tuple[str, list[str]]]]:
    all_violations = []
    failures = []
    for case in cases:
        violations = metrics.guardian_violations(
            answer=case["answer"], evidence=case["evidence"], events=case["events"]
        )
        all_violations.append(violations)
        if violations:
            failures.append((case["id"], violations))
    return metrics.guardian_accuracy(all_violations), failures


def score_adversarial(cases: list[dict]) -> list[tuple[str, list[str], bool]]:
    """Returns (id, violations, blocked) per case. `blocked` must be True for every case —
    an adversarial case that is NOT blocked is a regression."""
    results = []
    for case in cases:
        violations = metrics.guardian_violations(
            answer=case["answer"], evidence=case["evidence"], events=case["events"]
        )
        results.append((case["id"], violations, bool(violations)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adversarial", action="store_true", help="적대 회귀 12건도 채점")
    args = parser.parse_args()

    main_cases = _load(MAIN_SET)
    m2, failures = score_main(main_cases)
    print(f"총 {len(main_cases)}건 · 규약 위반 {len(failures)}건")
    print(f"M2 (guardian_accuracy) = {m2}")
    for case_id, violations in failures:
        print(f"  FAIL {case_id}: {violations}")

    exit_code = 0 if not failures else 1

    if args.adversarial:
        adv_cases = _load(ADVERSARIAL_SET)
        results = score_adversarial(adv_cases)
        blocked = sum(1 for _, _, ok in results if ok)
        print(f"\n적대 회귀 {len(adv_cases)}건 · {blocked}건 차단")
        for case_id, violations, ok in results:
            status = "차단" if ok else "**통과(회귀)**"
            print(f"  {case_id:35s} {status:12s} {violations}")
        if blocked != len(adv_cases):
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
