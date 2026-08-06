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
from collections.abc import Sequence
from dataclasses import dataclass

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
