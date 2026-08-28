"""보호자 응답 골든셋 40건 + 적대 회귀 12건 채점 스크립트.

`metrics.guardian_violations` / `metrics.guardian_accuracy` (M2)에 직접 물린다 — 이 파일은
새 검증 로직을 추가하지 않는다. 골든셋 최초 작성(40건)은 `apps/ai-engine/src/ai_engine/
guardian_log_qa.py`(실제 구현)를 호출해서 만들지 않았다 — 구현자가 자기 채점을 만들면
편향이라는 07절 원칙을 지키기 위해, ADR-0012 규칙과 계약(`openapi.yaml`
UserActionEventType) 12종만 보고 독립적으로 작성했다.

**단, questionId를 가진 30건은 이후 다시 쓰였고 그 30건에는 위 원칙이 더 이상
적용되지 않는다** — runtime(`guardian_log_qa.py`)이 실제로 낸 answer/sources를
먼저 채택한 뒤 계약 문서에 사후 대조하는 순서였다. 정확한 이력은 아래
"작성 이력을 정확히 남긴다" 절 참고. 독립 작성 원칙이 그대로 유지되는 것은
questionId가 없는 나머지 10건(자유질문)과 적대 회귀 12건뿐이다.

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
못한다(PR #162 리뷰 Blocking). `_matches_golden()`이 후자를 담당한다.

**2026-08-27 해소.** 이 비교를 처음 넣었을 때는 30건 전부 불일치했다 — 원인은
두 가지가 겹쳐 있었다. (1) `guardian_log_qa.py`가 관련 이벤트 중 *가장 최근 것
하나*(+ evacuation_progress는 도착 여부, help_request는 CITATION_SCOPE 내 이벤트
전체)만 인용하는 반면, 골든셋은 케이스가 겪은 이벤트를 CITATION_SCOPE 밖의 것까지
포함해 전부 순서대로 서술하도록 작성돼 있었다. (2) `_matches_golden()`이 `at`을
문자열 그대로 비교해, 같은 시각도 오프셋 표기 차이(`+09:00` vs `Z`)만으로
mismatch로 잡혔다. 구현 오너(김소원) 확인 결과 — runtime의 질문별 인용 범위
(evacuation_progress=최근 1건+도착 부재 / help_request=CITATION_SCOPE 내 이벤트
전체 / arrival_status=최근 1건)가 의도한 계약이며, 골든셋 쪽을 이에 맞춰 재작성
했다(30건, `guardian_log_qa.py`가 실제로 낸 answer/sources를 그대로 채택). 동시에
`_matches_golden()`에 `_normalize_at()`을 추가해 인스턴트 기준으로 비교하도록
고쳤다. 재검증 결과: 골든 기대값 일치 30/30, 적대 회귀 12/12 차단, exit 0.

**2026-08-28 추가 — questionId 30건이 실제로 내는 응답은 30가지가 아니다(신호정님 리뷰).**
`arrival_status`/`help_request`는 CITATION_SCOPE가 "최근 1건"만 인용하도록 정해져 있어,
선행 이벤트가 다른 여러 케이스가 같은 answer/evidence로 수렴한다 — 이는 계약이 의도한
동작이라 이 PR에서 고칠 대상이 아니다. `--runtime`은 이제 이 수를 "골든 기대값 일치
N/30"과 별도로 "실제 서로 다른 응답 조합 M가지"로 함께 보고한다(아래 `score_runtime`).
40건 구성 자체(카테고리별 10건)는 07절 스펙을 유지하기 위해 그대로 둔다.

**작성 이력을 정확히 남긴다(소원님 2026-08-27 15:06 요청)** — 위 30건은 계약을
먼저 읽고 처음부터 독립적으로 다시 쓴 것이 **아니다.** `guardian_log_qa.py`
실행 결과를 먼저 채택한 뒤, 그 값을 계약 문서(구현 코드가 아님)인
[ADR-0012](../../../docs/adr/0012-verifier-rules-and-closed-loop.md) 2절과
[openapi.yaml](../../../packages/contracts/openapi.yaml) `GuardianQuestionId`
(2512행~)에 사후 대조했다. 세 질문 모두 계약 원문과 일치했다 —
evacuation_progress의 "최근 1건+도착부재"는 openapi.yaml 2543행·ADR-0012 2절
116행에 그대로 명시돼 있고, help_request·arrival_status의 인용 가능 이벤트도
openapi.yaml 2521~2523행 표와 정확히 같다(오히려 수정 전 골든셋이 표 밖 이벤트
`direct_evacuation_selected`/`route_guidance_started`를 근거로 쓰고 있어 계약을
어기고 있었다).

**단, help_request가 "관련 이벤트 전체를 서술해야 한다"는 완전성 자체는 계약에
명시돼 있지 않다** — ADR-0012·openapi.yaml 어디에도 "빠짐없이"·"전부 서술"류의
문구가 없다. 명시된 것은 (a) 근거 타입이 `help_request_selected`·
`emergency_call_119_selected` 둘로 제한된다는 것과 (b) 사실이 여럿이면 문장을
쪼갠다는 서식 규칙뿐이다. `_answer_help()`가 present 이벤트만 문장으로 만들고
absent 쪽을 항상 덧붙이진 않는 지금 동작은 계약에 **어긋나지도 요구되지도**
않는 구현 선택이다 — evacuation_progress의 "행동 0건이면 전 종류 부재 하나로
닫는다" 같은 명시적 특례가 help_request에는 없다.

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


def _normalize_at(value: str | None) -> str | None:
    """골든셋(+09:00 등 임의 오프셋)과 runtime(UTC `Z`)이 같은 시각을 다른 문자열로 적을 수
    있다 — instant 기준으로 정규화해야 표기 차이가 아닌 실제 불일치만 걸린다(PR #162,
    소원님 2026-08-27 14:09 코멘트)."""
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).isoformat()


def _matches_golden(case: dict, response: GuardianLogAnswer) -> bool:
    """runtime 응답이 골든 케이스가 적어 둔 기대값(answer/evidence)과 같은지 비교한다.

    규약 위반 여부(`metrics.guardian_violations`)는 "runtime이 규약을 지키는 *어떤*
    답을 냈다"만 증명한다 — 그 답이 이 골든 케이스가 의도한 답인지는 별개다. evidence는
    (type, present, at) 집합으로 비교해 순서 차이는 무시하고 사실 집합만 견준다. `at`은
    인스턴트 기준으로 정규화한 뒤 비교한다 — 그렇지 않으면 같은 시각도 오프셋 표기
    차이(`+09:00` vs `Z`)만으로 mismatch로 잡힌다.
    """
    golden_evidence = {
        (item["type"], item["present"], _normalize_at(item.get("at"))) for item in case["evidence"]
    }
    runtime_evidence = {
        (source.type, source.present, _normalize_at(source.at)) for source in response.sources
    }
    return response.answer == case["answer"] and golden_evidence == runtime_evidence


def score_runtime(
    cases: list[dict],
) -> tuple[float | None, list[tuple[str, list[str]]], list[str], list[str], int]:
    """`questionId`가 있는 케이스만 실제 `guardian_log_qa.py`(runtime)를 호출해 채점한다.

    경로: events + questionId -> `answer_guardian_question()`(runtime) -> answer/sources
    -> `metrics.guardian_violations`. `score_main`과 달리 케이스에 미리 적힌 answer/evidence는
    규약 위반 채점에는 쓰지 않는다 — runtime이 실제로 만든 값만 채점한다. 다만 그 값을
    골든 케이스의 기대값과도 별도로 비교한다(`_matches_golden`) — 규약 위반이 0건이어도
    골든 케이스가 의도한 답이 아닐 수 있기 때문이다.

    `distinct_responses`는 채점된 케이스들이 실제로 낸 서로 다른 (answer, evidence) 조합
    개수다 — CITATION_SCOPE가 "최근 1건"만 인용하는 질문은 선행 이벤트가 다른 케이스도
    같은 응답으로 수렴하므로, 채점 건수와 이 수는 다를 수 있다(신호정님 2026-08-27 리뷰).

    Returns (M2, 위반 목록, questionId 없어 건너뛴 id 목록, 골든 기대값과 어긋난 id 목록,
    실제 서로 다른 응답 조합 개수).
    """
    all_violations = []
    failures = []
    skipped = []
    golden_mismatches = []
    response_signatures = set()
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
        response_signatures.add(
            (
                response.answer,
                frozenset(
                    (source.type, source.present, _normalize_at(source.at))
                    for source in response.sources
                ),
            )
        )
    m2 = metrics.guardian_accuracy(all_violations) if all_violations else None
    return m2, failures, skipped, golden_mismatches, len(response_signatures)


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
        m2_rt, failures_rt, skipped, golden_mismatches, distinct_responses = score_runtime(
            main_cases
        )
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
        print(
            f"[runtime] 실제 서로 다른 응답 조합 {distinct_responses}가지 "
            f"(CITATION_SCOPE 최근 1건 정책으로 여러 케이스가 같은 응답에 수렴함 — "
            "PR #162 리뷰, 신호정)"
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
