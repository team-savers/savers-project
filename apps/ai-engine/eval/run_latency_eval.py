"""Measure 알림 도달 속도 end-to-end and write a JSON report.

Run it against a started stack:

    docker compose -f infra/docker-compose.yml up --build      # or two uvicorn processes
    python apps/ai-engine/eval/run_latency_eval.py --runs 100

**HTTP only, by design.** This is the one metric that spans both apps, and importing
`backend_core` from here would break the app-boundary rule that makes ai-engine
independently deployable (AGENTS.md). It would also measure the wrong thing: serialization
and the network hop between backend and ai-engine are part of what a person waits through.

Two numbers come back and they answer different questions:

- `perRecipientMs` — what the backend reports per delivery (`AlertRunSummary.deliveries`).
  This is the KPI's subject: how long *one person* waited from event to dispatch.
- `wallClockMs` — how long the whole request took from here. Always larger; it includes
  every recipient in the run plus our own HTTP overhead. Reported because a per-recipient
  number that looks fine while the run takes a minute is a number hiding a queue.

⚠️ With the offline stubs in place this measures our own code path only — no 기상청 poll,
no FCM round-trip, no HyperCLOVA X call. It is a floor, not the submitted figure. Re-run it
after each seam is replaced; that progression is itself worth showing.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import metrics

DEFAULT_OUT = Path(__file__).parent / "reports"
DEFAULT_BACKEND = "http://localhost:8000"
# Nothing here reaches the public internet, but the disaster feed will: a run that hangs
# forever is a run nobody notices has stopped measuring.
REQUEST_TIMEOUT_S = 30.0


def _dispatch_once(client: httpx.Client) -> tuple[list[float], float, dict[str, Any]]:
    """One dispatch. Returns (per-recipient latencies, wall clock ms, raw summary)."""
    started = perf_counter()
    response = client.post("/internal/alerts/dispatch", timeout=REQUEST_TIMEOUT_S)
    wall_ms = (perf_counter() - started) * 1000
    response.raise_for_status()
    payload = response.json()
    latencies = [float(d["latencyMs"]) for d in payload.get("deliveries", [])]
    return latencies, wall_ms, payload


def evaluate(base_url: str, runs: int) -> dict[str, Any]:
    per_recipient: list[float] = []
    wall_clock: list[float] = []
    modes: dict[str, int] = {}
    failures: list[str] = []

    with httpx.Client(base_url=base_url) as client:
        for index in range(runs):
            try:
                latencies, wall_ms, payload = _dispatch_once(client)
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                # Recorded, not raised: a run that dies at sample 87 of 100 should still
                # report the 86 it measured, and the failure count is itself a finding.
                failures.append(f"run {index}: {type(exc).__name__}: {exc}")
                continue
            per_recipient.extend(latencies)
            wall_clock.append(wall_ms)
            for delivery in payload.get("deliveries", []):
                mode = str(delivery.get("messageMode", "unknown"))
                modes[mode] = modes.get(mode, 0) + 1

    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "baseUrl": base_url,
        "runsRequested": runs,
        "runsSucceeded": len(wall_clock),
        "failures": failures,
        # official_fallback here means ai-engine was unreachable. The run still "passes",
        # so without this breakdown a degraded stack would report a flattering latency.
        "messageModes": modes,
        "perRecipientMs": asdict(metrics.latency_summary(per_recipient)),
        "wallClockMs": asdict(metrics.latency_summary(wall_clock)),
    }


def _format_ms(value: float | None) -> str:
    return "측정 불가" if value is None else f"{value:.1f}ms"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BACKEND, help="backend origin")
    parser.add_argument(
        "--runs", type=int, default=100, help="dispatch calls to make (KPI asks for 100)"
    )
    parser.add_argument("--out", type=Path, default=None, help="report path (.json)")
    args = parser.parse_args()

    report = evaluate(args.base_url, args.runs)

    out = args.out or DEFAULT_OUT / f"latency-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    per = report["perRecipientMs"]
    wall = report["wallClockMs"]
    print(f"{report['runsSucceeded']}/{report['runsRequested']}회 성공 · {report['baseUrl']}")
    print(f"  수신자별 평균  {_format_ms(per['mean_ms'])}   p95 {_format_ms(per['p95_ms'])}")
    print(f"  요청 전체 평균 {_format_ms(wall['mean_ms'])}   p95 {_format_ms(wall['p95_ms'])}")
    print(f"  메시지 등급    {report['messageModes'] or '없음'}")
    if report["failures"]:
        print(f"  실패 {len(report['failures'])}건 — 보고서의 failures 항목 확인")
    if report["messageModes"].get("official_fallback"):
        print("\n⚠️ official_fallback이 섞여 있습니다 — ai-engine이 응답하지 않은 구간입니다.")
        print("   생성 단계를 건너뛴 측정이라 지표로 쓸 수 없습니다.")
    print(f"\n보고서: {out}")
    return 0 if report["runsSucceeded"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
