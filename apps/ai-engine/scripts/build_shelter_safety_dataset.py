"""수해대피소 + 건축물대장으로 대피소 침수 안전등급 PU-learning 데이터셋을 만든다.

Requires the `ml` extra: `pip install -e "./apps/ai-engine[ml]"`.

P(안전 대피소) / 신뢰 negative(spy 기법으로 U에서 확정) / 보류(held-out) 세 CSV와
단계별 카운트 요약(summary.json)을 `--out-dir`에 쓴다. 파이프라인 본체는
`ai_engine.shelter_safety.pipeline.run_pu_pipeline()` — 이 스크립트는 CLI 인자
파싱과 출력 저장만 담당한다 (`scripts/build_index.py`와 동일한 역할 분리).

Usage:
    python scripts/build_shelter_safety_dataset.py \\
        --shelters-csv tests/fixtures/shelter_safety_shelters_mock.csv \\
        --registry-csv tests/fixtures/shelter_safety_registry_mock.csv
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_engine.shelter_safety.pipeline import run_pu_pipeline
from ai_engine.shelter_safety.spy import SpyPipelineConfig


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shelters-csv", type=Path, required=True, help="TL_FLOOD_P CSV 경로")
    parser.add_argument(
        "--registry-csv", type=Path, required=True, help="건축물대장(표제부) CSV 경로"
    )
    parser.add_argument("--out-dir", type=Path, default=Path("outputs/shelter_safety"))
    parser.add_argument("--spy-ratio", type=float, default=SpyPipelineConfig.spy_ratio)
    parser.add_argument(
        "--subsample-multiplier", type=float, default=SpyPipelineConfig.subsample_multiplier
    )
    parser.add_argument(
        "--threshold-percentile", type=float, default=SpyPipelineConfig.threshold_percentile
    )
    parser.add_argument("--seed", type=int, default=SpyPipelineConfig.seed)
    args = parser.parse_args()

    config = SpyPipelineConfig(
        spy_ratio=args.spy_ratio,
        subsample_multiplier=args.subsample_multiplier,
        threshold_percentile=args.threshold_percentile,
        seed=args.seed,
    )
    result = run_pu_pipeline(args.shelters_csv, args.registry_csv, config=config)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    result.positive.to_csv(args.out_dir / "positive.csv", index=False)
    result.reliable_negative.to_csv(args.out_dir / "reliable_negative.csv", index=False)
    result.held_out.to_csv(args.out_dir / "held_out.csv", index=False)
    (args.out_dir / "summary.json").write_text(
        json.dumps(result.diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"P(안전): {len(result.positive)}건")
    print(
        f"신뢰 negative: {len(result.reliable_negative)}건 (임계선 score < {result.threshold:.4f})"
    )
    print(f"판정 보류: {len(result.held_out)}건")
    print(f"-> {args.out_dir}")


if __name__ == "__main__":
    main()
