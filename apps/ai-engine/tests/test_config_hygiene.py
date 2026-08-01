"""Guards against config-value duplication drifting back in.

Not a mirror of one `src/` module — this protects an invariant that spans several files:
the Chroma collection name has been hardcoded as a plain string literal, independently, in
more than one place three separate times (`build_index.py --collection`'s own default and
`ChromaRetriever.from_persist_dir()`'s own default both drifted from
`Settings.action_manual_collection` — see that field's docstring in `ai_engine/config.py`).
Each time, nothing failed until someone ran the indexer without an explicit flag and it
silently wrote to a collection the live service never reads from.

This test makes a fourth occurrence fail at test time instead of at index time.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).parent.parent

# Exact-quote match only: "flood_action_manual.csv" (a CSV export filename) and
# "action_manual.jsonl" (FixtureRetriever's own fixture file) are different values for
# different artifacts, not the Chroma collection name, and must not trip this. Requiring
# the same quote character immediately on both sides of the literal is what tells
# "action_manual" apart from "action_manual.jsonl" or ".../action_manual.csv".
_HARDCODED_COLLECTION_NAME = re.compile(r"""(["'])(flood_action_manual|action_manual)\1""")

# config.py is the one place this string is allowed to be written literally; every other
# reference must go through `Settings.action_manual_collection` instead of retyping it.
_ALLOWED_FILE = APP_ROOT / "src" / "ai_engine" / "config.py"

# Shipped code only. tests/ intentionally uses its own throwaway collection names (e.g.
# "test_action_manual") for isolation — those aren't the production value this guards.
_SCANNED_DIRS = (APP_ROOT / "src", APP_ROOT / "scripts")


def test_action_manual_collection_name_is_not_hardcoded_outside_config() -> None:
    """`config.py`가 유일한 출처 — 다른 곳에 같은 문자열이 리터럴로 다시 나타나면 실패한다."""
    violations: list[str] = []
    for base in _SCANNED_DIRS:
        for path in base.rglob("*.py"):
            if path == _ALLOWED_FILE:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _HARDCODED_COLLECTION_NAME.search(line):
                    violations.append(f"{path.relative_to(APP_ROOT)}:{lineno}: {line.strip()}")

    assert not violations, (
        "Chroma 컬렉션 이름이 config.py 밖에 하드코딩됨 — "
        "Settings.action_manual_collection을 참조하도록 고치세요:\n" + "\n".join(violations)
    )
