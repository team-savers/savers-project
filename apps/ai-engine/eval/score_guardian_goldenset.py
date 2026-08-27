"""보호자 응답 골든셋 40건 + 적대 회귀 12건 채점 스크립트.

`metrics.guardian_violations` / `metrics.guardian_accuracy` (M2)에 직접 물린다 — 이 파일은
새 검증 로직을 추가하지 않는다. 골든셋은 `apps/ai-engine/src/ai_engine/guardian_log_qa.py`
(실제 구현)를 호출해서 만들지 않았다 — 구현자가 자기 채점을 만들면 편향이라는 07절 원칙을
지키기 위해, ADR-0012 규칙과 계약(`openapi.yaml` UserActionEventType) 12종만 보고 독립적으로
작성했다.

기본 실행은 케이스에 미리 적어 둔 `answer`/`evidence`를 그대로 채점한다 — "정답 문장이
verifier를 통과하는가"만 증명하고, "실제 `guardian_log_qa.py`가 이 답을 만드는가"는
증명하지 못한다. `--runtime`은 그 간극을 메운다: `questionId` + `events`를 실제
`answer_guardian_question()`에 넣어 runtime이 만든 answer/sources를 채점한다.
`questionId`가 없는 기타 10건(자유질문)은 계약(`packages/contracts/openapi.yaml`)에
자유질문 입력 필드가 아직 없어 runtime 경로에 넣을 수 없다 — `--runtime`에서는
건너뛰고 개수만 보고한다 (후속 과제).

`--runtime`은 두 가지를 따로 검사한다 — 규약 위반 여부와, 골든 케이스가 적어 둔
기대값(answer/evidence)과의 일치 여부. 전자만으로는 "runtime이 규약을 지키는
*어떤* 답을 냈다"만 증명하고, 그 답이 골든 케이스가 의도한 답인지는 증명하지
못한다(PR #162 리뷰 Blocking). `_matches_golden()`이 후자를 담당한다. 이 비교를
실제로 넣어 보면 30건 전부 불일치한다 — `guardian_log_qa.py`가 관련 이벤트 중
*가장 최근 것 하나*(+ evacuation_progress는 도착 여부)만 인용하는 반면, 골든셋은
케이스가 겪은 이벤트를 전부 순서대로 서술하도록 작성됐다. 이 간극은 questionId를
카테고리별로 좁혀도(§리뷰 3) 좁혀지지 않는다 — 한 이벤트만 인용하는 것과 여러
이벤트를 순서대로 인용하는 것은 CITATION_SCOPE가 아니라 `_answer_progress`/
`_answer_help`/`_answer_arrival`의 구현 자체가 가르는 문제이기 때문이다. 즉 지금
`guardian_log_qa.py`와 골든셋 중 어느 쪽이 07절 스펙이 의도한 계약인지는 이 파일이
결정할 수 없다 — 구현 오너(김소원) 또는 Tech Lead 확인이 필요하다 (후속 과제).

M2(guardian_accuracy)의 분모는 거절(`answer: null`) 5건을 뺀 답변 35건이다 —
`metrics.py`의 `guardian_accuracy` docstring이 경고하는 대로, 거절을 M2에 섞으면 전부
거절하는 엔진이 만점을 받는다. 거절 5건은 `expect.refuse`가 실제 응답과 일치하는지만
별도로 확인한다.

실행:
    cd apps/ai-engine/eval
    python score_guardian_goldenset.py              # 정답 40건 채점 (sanity check)
    python score_guardian_goldenset.py --adversarial # 적대 12건도 함께 채점
    python score_guardian_goldenset.py --runtime     # questionId 보유 30건, runtime 경로로 채점
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import metrics

from ai_engine.guardian_log_qa import GuardianLogAnswer, answer_guardian_question

GOLDEN_DIR = Path(__file__).parent / "golden_dataset" / "guardian"
MAIN_SET = GOLDEN_DIR / "guardian_v0.jsonl"
ADVERSARIAL_SET = GOLDEN_DIR / "guardian_adversarial_v0.jsonl"


def _load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def score_main(
    cases: list[dict],
) -> tuple[float | None, list[tuple[str, list[str]]], int, list[str]]:
    """M2는 거절이 아닌 케이스에서만 계산한다.

    `metrics.guardian_accuracy`의 docstring이 경고하는 그대로다 — 거절을 M2에 섞으면
    전부 거절하는 엔진이 만점을 받는다. 거절 케이스(`answer: null`)는 검사할 문장이
    없어 분자·분모 어느 쪽에도 정보를 더하지 않으므로, M2 분모에서 뺀 대신 `expect.refuse`가
    실제 응답과 일치하는지만 따로 확인한다 — 그래야 이 필드가 죽은 데이터로 남지 않는다.

    Returns (M2, 위반 목록, 거절 건수, `expect`와 어긋난 거절 id 목록).
    """
    answerable = [case for case in cases if case["answer"] is not None]
    refusals = [case for case in cases if case["answer"] is None]

    all_violations = []
    failures = []
    for case in answerable:
        violations = metrics.guardian_violations(
            answer=case["answer"], evidence=case["evidence"], events=case["events"]
        )
        all_violations.append(violations)
        expected = case.get("expect", {}).get("violations", [])
        if violations != expected:
            failures.append((case["id"], violations))

    refusal_mismatches = [
        case["id"] for case in refusals if case.get("expect", {}).get("refuse") != "no_evidence"
    ]

    return metrics.guardian_accuracy(all_violations), failures, len(refusals), refusal_mismatches


def _to_runtime_event(event: dict) -> dict:
    """골든셋 이벤트(+09:00 등 임의 오프셋) -> `GuardianSessionEvent` 요구 형식(UTC, `Z` 접미사).

    `next_guidance_requested`는 계약상 `guidanceStep` payload가 필수다 (`guardian_log_qa.py`
    `validate_payload_for_type`). 골든셋은 그 값을 채점에 쓰지 않으므로(단계 자체가
    `guardian_violations`의 채점 대상이 아니다) 스키마를 만족시키는 값 하나만 채운다.
    """
    at_utc = datetime.fromisoformat(event["at"]).astimezone(UTC)
    payload = {"guidanceStep": 1} if event["type"] == "next_guidance_requested" else {}
    return {
        "type": event["type"],
        "at": at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payload": payload,
    }


def _matches_golden(case: dict, response: GuardianLogAnswer) -> bool:
    """runtime 응답이 골든 케이스가 적어 둔 기대값(answer/evidence)과 같은지 비교한다.

    규약 위반 여부(`metrics.guardian_violations`)는 "runtime이 규약을 지키는 *어떤*
    답을 냈다"만 증명한다 — 그 답이 이 골든 케이스가 의도한 답인지는 별개다. evidence는
    (type, present, at) 집합으로 비교해 순서 차이는 무시하고 사실 집합만 견준다.
    """
    golden_evidence = {(item["type"], item["present"], item.get("at")) for item in case["evidence"]}
    runtime_evidence = {(source.type, source.present, source.at) for source in response.sources}
    return response.answer == case["answer"] and golden_evidence == runtime_evidence


def score_runtime(
    cases: list[dict],
) -> tuple[float | None, list[tuple[str, list[str]]], list[str], list[str]]:
    """`questionId`가 있는 케이스만 실제 `guardian_log_qa.py`(runtime)를 호출해 채점한다.

    경로: events + questionId -> `answer_guardian_question()`(runtime) -> answer/sources
    -> `metrics.guardian_violations`. `score_main`과 달리 케이스에 미리 적힌 answer/evidence는
    규약 위반 채점에는 쓰지 않는다 — runtime이 실제로 만든 값만 채점한다. 다만 그 값을
    골든 케이스의 기대값과도 별도로 비교한다(`_matches_golden`) — 규약 위반이 0건이어도
    골든 케이스가 의도한 답이 아닐 수 있기 때문이다.

    Returns (M2, 위반 목록, questionId 없어 건너뛴 id 목록, 골든 기대값과 어긋난 id 목록).
    """
    all_violations = []
    failures = []
    skipped = []
    golden_mismatches = []
    for case in cases:
        question_id = case.get("questionId")
        if question_id is None:
            skipped.append(case["id"])
            continue
        runtime_events = [_to_runtime_event(event) for event in case["events"]]
        response = answer_guardian_question(question_id, runtime_events)
        evidence = [source.model_dump(mode="python") for source in response.sources]
        violations = metrics.guardian_violations(
            answer=response.answer, evidence=evidence, events=runtime_events
        )
        all_violations.append(violations)
        if violations:
            failures.append((case["id"], violations))
        if not _matches_golden(case, response):
            golden_mismatches.append(case["id"])
    m2 = metrics.guardian_accuracy(all_violations) if all_violations else None
    return m2, failures, skipped, golden_mismatches


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
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="questionId 보유 케이스를 실제 guardian_log_qa.py(runtime)로 재채점",
    )
    args = parser.parse_args()

    main_cases = _load(MAIN_SET)
    m2, failures, refusal_count, refusal_mismatches = score_main(main_cases)
    answerable_count = len(main_cases) - refusal_count
    print(
        f"[sanity] 총 {len(main_cases)}건 (답변 {answerable_count}건 · 거절 {refusal_count}건) · "
        f"규약 위반 {len(failures)}건"
    )
    print(f"[sanity] M2 (guardian_accuracy, 분모=답변 {answerable_count}건) = {m2}")
    for case_id, violations in failures:
        print(f"  FAIL {case_id}: {violations}")
    for case_id in refusal_mismatches:
        print(f"  FAIL {case_id}: expect.refuse != 'no_evidence'인데 answer가 null임")

    exit_code = 0 if not failures and not refusal_mismatches else 1

    if args.runtime:
        m2_rt, failures_rt, skipped, golden_mismatches = score_runtime(main_cases)
        scored = len(main_cases) - len(skipped)
        print(
            f"\n[runtime] questionId 보유 {scored}건 · 규약 위반 {len(failures_rt)}건 · "
            f"제외 {len(skipped)}건(자유질문 - questionId 계약 미정, 후속 과제)"
        )
        print(f"[runtime] M2 (guardian_accuracy) = {m2_rt}")
        for case_id, violations in failures_rt:
            print(f"  [runtime] FAIL {case_id}: {violations}")
        print(
            f"[runtime] 골든 기대값(answer/evidence) 일치 {scored - len(golden_mismatches)}건 · "
            f"불일치 {len(golden_mismatches)}건"
        )
        for case_id in golden_mismatches:
            print(f"  [runtime] MISMATCH {case_id}: runtime 응답이 골든 케이스 기대값과 다름")
        if failures_rt or golden_mismatches:
            exit_code = 1

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
