"""실데이터로 부합도 모델을 학습하고 모델 1개와 summary.json을 저장한다."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from ai_engine.shelter_safety.training import train_and_evaluate

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA = REPO_ROOT / "apps/ai-engine/data/raw/building_registry_3districts_20260805.csv"
DEFAULT_OUTPUT = REPO_ROOT / "apps/ai-engine/artifacts/shelter_safety"


def _stable_summary(summary: dict[str, Any]) -> str:
    return json.dumps(summary, ensure_ascii=False, sort_keys=True, allow_nan=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-reproducibility", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    model, summary = train_and_evaluate(args.data)

    reproducibility = {"checked": False, "passed": None}
    if args.verify_reproducibility:
        repeated_model, repeated_summary = train_and_evaluate(args.data)
        same_summary = _stable_summary(summary) == _stable_summary(repeated_summary)
        same_model = model.booster_.model_to_string() == repeated_model.booster_.model_to_string()
        reproducibility = {
            "checked": True,
            "passed": same_summary and same_model,
            "summary_identical": same_summary,
            "model_identical": same_model,
        }
        if not reproducibility["passed"]:
            raise RuntimeError(f"동일 seed 재현성 검증 실패: {reproducibility!r}")

    summary["data"]["path"] = args.data.resolve().relative_to(REPO_ROOT).as_posix()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    model_path = args.output_dir / "shelter_suitability_lgbm.txt"
    summary_path = args.output_dir / "summary.json"
    model.booster_.save_model(model_path)
    summary["artifact"] = {
        "model_path": model_path.relative_to(REPO_ROOT).as_posix(),
        "model_sha256": sha256(model_path.read_bytes()).hexdigest(),
        "summary_path": summary_path.relative_to(REPO_ROOT).as_posix(),
    }
    summary["reproducibility"] = reproducibility
    summary["generated_at"] = datetime.now(UTC).isoformat()
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(summary_path)
    print(model_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
