"""Replay fixture loader.

Tests, development and the demo all read frozen fixtures through this loader.
The goal is same-input-same-output, so the loader never modifies a file.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from backend_core.config import get_settings


def load_fixture(name: str) -> dict[str, Any]:
    """Read a fixture file into a dict; fail immediately if it does not exist.

    No silent fallback: returning an empty dict for a missing fixture would let the
    downstream pipeline keep running on bad data, so we fail loudly instead.
    """
    path: Path = get_settings().fixtures_dir / name
    if not path.exists():
        raise FileNotFoundError(
            f"픽스처 없음: {path}. scripts/collect_fixture.py 로 먼저 수집·동결할 것."
        )
    with path.open(encoding="utf-8") as f:
        data: dict[str, Any] = json.load(f)
    return data


def fixture_sha256(name: str) -> str:
    """Fixture integrity hash. Recorded alongside evaluation results so any number
    can be traced back to the exact input that produced it."""
    path: Path = get_settings().fixtures_dir / name
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
