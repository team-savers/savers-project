"""Metric functions for the submitted KPIs.

Every function here is pure: same inputs give the same score, no I/O, no clock, no
network. That is what makes a submitted number reproducible by someone who only has this
repo — a reviewer can read the function, feed it the golden set, and get our number back.

⚠️ **These functions are deliberately independent of `ai_engine`.**
`guardrail.verify` computes something similar (bigram support), and importing it here
would be shorter. It would also mean the score follows the implementation: tune
`SUPPORT_THRESHOLD` to make the guardrail pass more, and 근거 일치율 rises without the
messages getting any better. A metric that moves when the thing it grades moves is not a
metric. The duplication is the point; keep it.

`percentile` duplicates `backend_core.pipeline.percentile` for a different reason — the
app-boundary rule forbids importing backend from here at all (AGENTS.md). Both use
nearest-rank so the two numbers stay comparable.

**`None` means "not measurable", never zero.** An empty source list, a body with no
sentences, a divide-by-zero denominator — all return `None`. Reporting 0.0 for those
would drag an average down with cases that were never scored, which is the difference
between a low score and a wrong score. The frontend metric layer (`readability.ts`) made
the same call; keeping them consistent means the two reports can be read side by side.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

# Character bigrams over Hangul + digits only. Whitespace, punctuation and particles carry
# no claim, and dropping them keeps "지하차도는 통행하지 마세요" comparable to the source
# sentence "지하차도는 통행하지 않습니다" without a morphological analyzer in the loop.
_HANGUL_ONLY = re.compile(r"[^가-힣0-9]")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")

# Korean polite imperative endings. The clarity KPI counts "단일 행동지침 포함률", and a
# directive that survives to the end of the message is the cheap, reliable marker for it.
_DIRECTIVE = re.compile(r"(하세요|하십시오|주세요|가세요|마세요)")

# A sentence sharing at least this share of its bigrams with the sources counts as
# supported. 0.5 matches the engine's current setting so the two agree on the fixture
# corpus, but it is a *parameter here* — every scoring function takes it explicitly so a
# report can state the threshold it was produced under.
DEFAULT_SUPPORT_THRESHOLD = 0.5


def sentences(text: str) -> list[str]:
    """Split into scoreable sentences, dropping empty fragments."""
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()]


def bigrams(text: str) -> set[str]:
    compact = _HANGUL_ONLY.sub("", text or "")
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def strip_frame(body: str, frame_phrases: Sequence[str]) -> str:
    """Remove the reviewed message frame so only *generated* text gets scored.

    The delivered message is frame + model output: an opener naming the 행정동 and 특보, and
    a closing directive naming the shelter the backend chose. Neither is 국민행동요령 text,
    so scoring them against the corpus would report every message as roughly half
    unfaithful — a number about our own template, not about the model.

    Frame phrases come from the golden case, not from importing the engine's constants.
    That is deliberate: widening the frame then shows up as a diff in the eval set, where a
    reviewer sees it, instead of silently raising every score.
    """
    out = body or ""
    # Longest first: an opener that contains a shorter phrase must be removed as a whole,
    # otherwise the leftover fragments get scored as if the model wrote them.
    for phrase in sorted((p for p in frame_phrases if p.strip()), key=len, reverse=True):
        out = out.replace(phrase, " ")
    return out


def support_ratio(sentence: str, source_quotes: Sequence[str]) -> float | None:
    """Share of a sentence's bigrams that appear somewhere in the source text.

    `None` when the sentence carries no Hangul (a bare number, punctuation): there is
    nothing to be right or wrong about, and scoring it 0 would punish the message for
    containing "119".
    """
    grams = bigrams(sentence)
    if not grams:
        return None
    allowed: set[str] = set()
    for quote in source_quotes:
        allowed |= bigrams(quote)
    return len(grams & allowed) / len(grams)


def unsupported_sentences(
    body: str,
    source_quotes: Sequence[str],
    *,
    frame_phrases: Sequence[str] = (),
    threshold: float = DEFAULT_SUPPORT_THRESHOLD,
) -> list[str]:
    """Sentences saying something the sources do not — the hallucination evidence list.

    Returned rather than counted so a report can quote the offending sentence. A bare rate
    with no examples is not reviewable.
    """
    scored = strip_frame(body, frame_phrases)
    out = []
    for sentence in sentences(scored):
        ratio = support_ratio(sentence, source_quotes)
        if ratio is not None and ratio < threshold:
            out.append(sentence)
    return out


def source_fidelity(
    body: str,
    source_quotes: Sequence[str],
    *,
    frame_phrases: Sequence[str] = (),
    threshold: float = DEFAULT_SUPPORT_THRESHOLD,
) -> float | None:
    """근거 일치율 for one message: supported sentences / scoreable sentences.

    Sentence-level rather than a single whole-body overlap number, because one invented
    sentence in an otherwise-quoted message is exactly the failure this KPI exists to
    catch, and a body-level average would dilute it away.

    `frame_phrases` is removed first — see `strip_frame`. Passing none scores the frame as
    model output, which is a valid stricter reading but not the number the KPI states.

    `None` when the message has nothing scoreable left, or when no sources were retrieved:
    with nothing to check against, "0% faithful" would be a false accusation.
    """
    if not [q for q in source_quotes if q.strip()]:
        return None
    scored = strip_frame(body, frame_phrases)
    scoreable = [s for s in sentences(scored) if support_ratio(s, source_quotes) is not None]
    if not scoreable:
        return None
    supported = sum(
        1
        for s in scoreable
        # support_ratio is not None for every member of `scoreable` by construction.
        if (r := support_ratio(s, source_quotes)) is not None and r >= threshold
    )
    return supported / len(scoreable)


def hallucination_rate(
    body: str,
    source_quotes: Sequence[str],
    *,
    frame_phrases: Sequence[str] = (),
    threshold: float = DEFAULT_SUPPORT_THRESHOLD,
) -> float | None:
    """Complement of `source_fidelity`. Kept as its own name because the guardrail
    on/off comparison reads as a hallucination *reduction*, and inverting the number at
    the call site is where sign errors get made."""
    fidelity = source_fidelity(
        body, source_quotes, frame_phrases=frame_phrases, threshold=threshold
    )
    return None if fidelity is None else 1.0 - fidelity


def suppression_rate(baseline: float | None, guarded: float | None) -> float | None:
    """환각 억제율: how much of the guardrail-off hallucination the guardrail removed.

    `(baseline - guarded) / baseline`, so 0.5 means "half the hallucinated content is
    gone" — the form the ≥50% target is stated in.

    `None` when either side is unmeasurable, and also when the control group did not
    hallucinate at all: dividing by a zero baseline would report a suppression rate for a
    run that had nothing to suppress. That is a case for a bigger eval set, not a number.
    """
    if baseline is None or guarded is None or baseline <= 0:
        return None
    return (baseline - guarded) / baseline


def directive_present(body: str) -> bool:
    """Whether the message ends up telling the person to do something.

    Feeds "단일 행동지침 포함률 100%". This checks *presence*; the "single" half
    (exactly one action, not three) needs the 행정용어/행동 사전 that lives in the
    frontend's `readability.ts` — see the README for why it is not re-implemented here.
    """
    return bool(_DIRECTIVE.search(body or ""))


def fact_echo_ratio(body: str, facts: Sequence[str]) -> float | None:
    """Share of backend-decided facts repeated verbatim in the message.

    ADR-0006 requires the shelter name and distance to survive generation unchanged: a
    model that rounds "320m" to "약 300m" has changed an evacuation instruction. Substring
    match is intentional — anything looser would accept a paraphrase, which is the failure.

    `None` when the case supplies no facts (no shelter, for instance).
    """
    wanted = [f for f in facts if f.strip()]
    if not wanted:
        return None
    return sum(1 for f in wanted if f in (body or "")) / len(wanted)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile. `None` for an empty sample.

    No interpolation: with the ~100 samples the 알림 도달 속도 KPI calls for, nearest-rank
    is the reproducible choice and matches what the backend reports per run.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q * len(ordered))))
    return ordered[rank - 1]


@dataclass(frozen=True)
class LatencySummary:
    """알림 도달 속도 rollup. Mean and p95 together because the mean hides the tail, and
    the tail is what a person actually waits through."""

    n: int
    mean_ms: float | None
    p95_ms: float | None
    max_ms: float | None


def latency_summary(samples_ms: Sequence[float]) -> LatencySummary:
    if not samples_ms:
        return LatencySummary(n=0, mean_ms=None, p95_ms=None, max_ms=None)
    return LatencySummary(
        n=len(samples_ms),
        mean_ms=sum(samples_ms) / len(samples_ms),
        p95_ms=percentile(samples_ms, 0.95),
        max_ms=max(samples_ms),
    )


def mean(values: Sequence[float | None]) -> float | None:
    """Average over the measurable values only.

    Unmeasurable cases are skipped rather than counted as 0 — see the module docstring.
    A caller that needs to know how many were skipped compares `len(values)` with the
    count it passed in.
    """
    measured = [v for v in values if v is not None]
    if not measured:
        return None
    return sum(measured) / len(measured)


# ─────────────────────────────────────────────────────────────────────────────
# Guardian answer metrics (M2, M4)
#
# These score the *finals* metrics, which are graded against the session event log rather
# than the corpus: M2 (로그에 없는 사실이 섞인 응답 0건) and M4 (폐루프 2차 발송 성공률).
# The rules they implement are ADR-0012 §2 (대조), §3 (금지 표현) and §4 (차단 사유 코드).
#
# ⚠️ Same independence rule as the top of this module, for the same reason: the verifier
# in `ai_engine` computes a similar comparison, and importing it would make the score
# follow the implementation — a verifier bug would grade itself as correct. Two
# implementations of one written rule (ADR-0012) is the check; keep them apart.
#
# Every time comparison here runs on the parsed UTC instant, never on the raw string:
# "…T03:42:09Z" sorts *before* "…T12:42:07+09:00" lexicographically while being the later
# instant, so string ordering flips events whenever the two notations meet. ADR-0012 §2
# says the same thing for 대조 — 인스턴트로 비교한다, 표기가 아니라.
#
# Truncation differs by what is being asked, and the two are not interchangeable:
#   - 대조 (evidence vs. log) truncates to the minute, per ADR-0012 §2, because a sentence
#     read by a person says "12시 13분" and never a second.
#   - 폐루프 ordering (M4) keeps full precision: it asks whether the send *followed* its
#     own timer, and the two are seconds apart by design (ADR-0012 §6 records the gap as
#     the proof the loop re-entered). Truncating would let a send that preceded its timer
#     by a few seconds land in the same minute bucket and score as a success.
#
# Display timezone is a generation concern, not a scoring one: what is graded here is the
# machine timestamp the answer cited, not how the sentence spelled it out.
# ─────────────────────────────────────────────────────────────────────────────

# ADR-0012 §3. Not exhaustive by design — the ADR says so, and a bypass phrase
# ("걱정 안 하셔도 됩니다") is meant to be caught by a golden case, not by growing this
# list until it reads like a filter.
SAFETY_ASSERTIONS = (
    "안전합니다",
    "괜찮습니다",
    "무사합니다",
    "이상 없습니다",
)

_WHITESPACE = re.compile(r"\s+")

# The default phrases never change, so collapse them once at import instead of on every
# scored answer. Custom `forbidden` lists still pay per call, which is the rare path.
_COLLAPSED_SAFETY = tuple((p, _WHITESPACE.sub("", p)) for p in SAFETY_ASSERTIONS)


# Sort position for an event whose `at` could not be parsed. It has no place on the
# timeline, so it goes last rather than ahead of real events; see `followup_summary`.
_UNDATED = datetime.min.replace(tzinfo=UTC)


def _share(part: int, whole: int) -> float | None:
    """`part / whole`, or `None` when nothing was scored.

    The module-wide "0 denominator is 측정 불가, never 0.0" rule lives here so M2 and M4
    cannot drift apart on it.
    """
    return None if whole == 0 else part / whole


def _instant(value: object) -> datetime | None:
    """RFC3339 timestamp -> aware UTC instant. `None` when absent, naive or unparsable.

    Naive input is rejected rather than assumed UTC: a stamp with no offset could equally
    be KST, and guessing turns a 9-hour error into a silent one.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _instant_minute(value: object) -> str | None:
    """RFC3339 timestamp -> UTC minute key (ADR-0012 §2). `None` when it will not parse."""
    instant = _instant(value)
    return None if instant is None else instant.strftime("%Y-%m-%dT%H:%M")


def evidence_mismatches(
    evidence: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
) -> list[str]:
    """ADR-0012 §2: check each cited evidence item against the log.

    Returns one block-reason code per failing item, in the order the items were cited.
    An empty list means every citation held. The codes are the ADR's, not free text, so a
    report can count *why* answers were blocked rather than only how many.
    """
    # Sets, not lists: every use below is a membership test or an emptiness test, and
    # ADR-0012 2절 says one matching occurrence is enough, so duplicate minutes carry
    # nothing. Nobody counts occurrences here — 횟수 주장 is `unsupported_claim` by 2절.
    by_type: dict[str, set[str | None]] = {}
    for event in events:
        event_type = event.get("type")
        if isinstance(event_type, str):
            by_type.setdefault(event_type, set()).add(_instant_minute(event.get("at")))

    codes: list[str] = []
    for item in evidence:
        item_type = item.get("type")
        present = item.get("present")
        if not isinstance(item_type, str) or not isinstance(present, bool):
            # ADR-0012 4절, third shape: the triplet's other two slots. Until `type` and
            # `present` are readable there is no row in the 2절 table to apply — which
            # event to match against and which direction is being claimed are both
            # undecided. Note `isinstance(1, bool)` is False, so a stringified or numeric
            # flag lands here rather than falling through to the absence branch.
            codes.append("malformed_evidence")
            continue

        logged: set[str | None] = by_type.get(item_type, set())
        if present:
            cited = _instant_minute(item.get("at"))
            if cited is None:
                # `present: true` without a parsable time cannot be compared at all.
                # Treating it as a pass would let an unverifiable citation through.
                codes.append("malformed_evidence")
            elif not logged:
                codes.append("present_claim_mismatch")
            elif cited not in logged:
                codes.append("time_mismatch")
        elif item.get("at") is not None:
            # ADR-0012: `present: false` carries no time. A time here means the producer
            # is confused about which direction it is asserting.
            codes.append("malformed_evidence")
        elif logged:
            codes.append("absent_claim_mismatch")
    return codes


def forbidden_phrase_hits(answer: str, phrases: Sequence[str] = SAFETY_ASSERTIONS) -> list[str]:
    """ADR-0012 §3: phrases that must not appear, whatever the evidence says.

    Matching is on the answer with whitespace collapsed, so a line break inside the phrase
    does not hide it.
    """
    collapsed = _WHITESPACE.sub("", answer)
    pairs = (
        _COLLAPSED_SAFETY
        if phrases is SAFETY_ASSERTIONS
        else tuple((p, _WHITESPACE.sub("", p)) for p in phrases)
    )
    return [phrase for phrase, needle in pairs if needle in collapsed]


def guardian_violations(
    *,
    answer: str | None,
    evidence: Sequence[Mapping[str, object]],
    events: Sequence[Mapping[str, object]],
    forbidden: Sequence[str] = SAFETY_ASSERTIONS,
) -> list[str]:
    """Every ADR-0012 block reason for one guardian answer. Empty list = deliverable.

    Three independent checks, because ADR-0012 blocks for three different reasons:
    the citations are checked against the log (2절), the answer is checked for sentences
    that no citation covers (2절 row 4), and the wording is checked for forbidden phrases
    (3절). An answer passes only when all three hold.

    A refusal (`answer is None`) has nothing to check and yields no violations — it is the
    designed path, not a failure. Whether refusing *too often* is a problem is a different
    number (거절률), deliberately not folded in here: mixing them would let an engine that
    refuses everything score a perfect M2.
    """
    if answer is None:
        return []

    # ADR-0012 1절: 답변을 문장으로 쪼개고 각 문장을 삼중항으로 정규화한다. Sentences with
    # no Hangul or digits claim nothing (see `support_ratio`) and are not counted.
    claims = [sentence for sentence in sentences(answer) if bigrams(sentence)]

    # ADR-0012 3절: 금지 표현은 대조 결과와 *무관하게* 차단한다. It is computed before the
    # evidence branch for exactly that reason — an answer that cites nothing is still an
    # answer that said 「괜찮습니다」, and returning only the citation code would drop the
    # more serious reason from the 8/31 사유별 집계.
    forbidden_codes = ["forbidden_phrase" for _ in forbidden_phrase_hits(answer, forbidden)]

    if not evidence:
        # The contract's invariant is `sources` empty -> `answer` null. An answer that
        # arrives with no citations has already broken it: every sentence it makes is a
        # claim with no corresponding `sources` item, which is ADR-0012 2절 row 4. One code
        # per claim, and at least one even for an answer that parses into no sentence at
        # all — the invariant is broken by the answer existing.
        #
        # Not `no_evidence`: that is a `GuardianAskResponse.refusalReason` enum value
        # (openapi.yaml), what the API hands the guardian's screen, and ADR-0012 5절
        # assigns it to the refusal path. Block reasons are the closed set of six in 4절;
        # mixing the other field's enum into this list would split the 8/31 사유별 집계
        # across two vocabularies.
        return ["unsupported_claim"] * max(len(claims), 1) + forbidden_codes

    # ADR-0012 2절 row 4: 대응하는 `sources` 항목이 없는 주장은 통과할 수 없다.
    #
    # `evidence_mismatches` only grades the citations that *are* there; it cannot see a
    # sentence that cited nothing. So an answer may quote the log correctly and then add
    # 「현재 대피소로 이동 중입니다」 — grounded first half, invented second half — and
    # score clean, which is precisely the failure M2 exists to count.
    #
    # The check is by count, and it is a *necessary* condition rather than a mapping: one
    # sentence needs at least one triplet (1절), so more sentences than cited items proves
    # by pigeonhole that some sentence has none. It deliberately does not try to decide
    # *which* sentence maps to *which* item — that needs the claim extraction the verifier
    # does, and reimplementing it here would make this file the verifier's mirror instead
    # of its independent check. A sentence that cites the *wrong* item is caught by
    # `evidence_mismatches`; a sentence that cites nothing is caught here.
    uncited = max(len(claims) - len(evidence), 0)

    return evidence_mismatches(evidence, events) + ["unsupported_claim"] * uncited + forbidden_codes


def guardian_accuracy(case_violations: Sequence[Sequence[str]]) -> float | None:
    """M2: share of graded answers with zero violations. `None` when nothing was graded.

    Refusals count as graded and clean (see `guardian_violations`), because a refusal that
    was correct is exactly the behaviour the metric is defending.
    """
    clean = sum(1 for violations in case_violations if not violations)
    return _share(clean, len(case_violations))


@dataclass(frozen=True)
class FollowupSummary:
    """M4 with the sessions it could not score kept next to the number.

    `rate` is over `due` alone. `unscoreable` counts sessions that *did* re-enter the loop
    but carry a `followup_due` or `guardian_notified` whose `at` cannot be ordered, so
    "did the send follow its own timer" has no answer for them.

    They are deliberately neither successes nor failures. Dropping them silently inflates
    M4 — a run with one clean success and one unreadable session would report 100%. But
    counting them as failures is just as wrong: it makes a timestamp bug indistinguishable
    from a guardian who was never notified, on a metric whose whole point is telling those
    two apart. Report `rate` and `unscoreable` together, or report neither.
    """

    due: int
    sent: int
    unscoreable: int
    rate: float | None


def _ordered_by_instant(
    events: Sequence[Mapping[str, object]],
) -> list[tuple[datetime | None, Mapping[str, object]]]:
    """Events oldest-first by parsed instant, unorderable ones last.

    Ordering is on the instant, never the raw stamp — a KST-stamped `followup_due` and a
    Z-stamped `guardian_notified` seconds later sort backwards as strings, which would
    read a punctual second dispatch as having preceded its own timer.
    """
    dated = [(_instant(event.get("at")), event) for event in events]
    dated.sort(key=lambda pair: (pair[0] is None, pair[0] or _UNDATED))
    return dated


@dataclass(frozen=True)
class _LoopOutcome:
    """What one session's log says about the closed loop."""

    due: bool  # `followup_due` is present, so the loop re-entered
    sent: bool  # a placeable `guardian_notified` followed it
    readable: bool  # the log answers "did the send follow its timer" one way or the other


def _score_session(events: Sequence[Mapping[str, object]]) -> _LoopOutcome:
    due_at: datetime | None = None
    due = False
    due_placed = False
    sent = False
    unplaceable_send = False

    for at, event in _ordered_by_instant(events):
        event_type = event.get("type")
        if event_type == "followup_due":
            if due:
                continue  # 재진입 상한은 1회 (7절); a second one cannot move the verdict.
            due = True
            due_at = at
            # The loop re-entered — the event's presence says so, not its clock — but
            # with no readable time there is nothing to order the send against.
            due_placed = at is not None
        elif event_type == "guardian_notified":
            if at is None:
                unplaceable_send = True
            elif due_at is not None and at >= due_at:
                sent = True

    # A send that *could* be placed settles the session, junk timestamps elsewhere in the
    # log notwithstanding. An unplaceable one only decides anything when nothing else
    # answered the question — and then it is a send we can see but cannot score, which is
    # not the same as a guardian who was never notified.
    return _LoopOutcome(
        due=due,
        sent=sent,
        readable=due_placed and (sent or not unplaceable_send),
    )


def followup_summary(
    session_logs: Sequence[Sequence[Mapping[str, object]]],
) -> FollowupSummary:
    """M4 (ADR-0012 7절): 분모는 `followup_due`가 있는 세션, 분자는 `guardian_notified`까지 간 세션.

    A session with no `followup_due` at all never re-entered the loop and is out of both
    counts — that is not a failure, it is a person who answered.
    """
    scored = [_score_session(events) for events in session_logs]
    reentered = [outcome for outcome in scored if outcome.due]
    scoreable = [outcome for outcome in reentered if outcome.readable]
    sent_count = sum(1 for outcome in scoreable if outcome.sent)

    return FollowupSummary(
        due=len(scoreable),
        sent=sent_count,
        unscoreable=len(reentered) - len(scoreable),
        rate=_share(sent_count, len(scoreable)),
    )


def followup_delivery_rate(
    session_logs: Sequence[Sequence[Mapping[str, object]]],
) -> float | None:
    """M4 as a single number, or `None` when this run cannot honestly produce one.

    `None` — never 0.0 — in two cases, and they mean different things:

    - no session ever reached `followup_due`. The 30분 timer never fired, so nothing was
      measured; reporting 0 would read as "the loop failed every time".
    - some session's loop events cannot be ordered (`unscoreable` above). A rate computed
      over the readable remainder is a number about a subset, and quoting it as M4 would
      report the log's defect as a better score.

    Use `followup_summary` when the report needs the breakdown; it is the honest form and
    this function is the convenience wrapper over it.
    """
    summary = followup_summary(session_logs)
    return None if summary.unscoreable else summary.rate
