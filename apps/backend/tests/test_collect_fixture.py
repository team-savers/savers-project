"""collect_fixture.py의 순수 함수와 픽스처 무결성 검사.

README 수집 이력 표의 sha256을 실제 파일에서 다시 계산해 대조한다. 표를 손으로 갱신하는
구조라 두 번 어긋난 적이 있고, 사람이 재계산하기 전에는 아무도 모르는 종류의 오차였다.
개행 때문에 값이 갈리므로 CR을 제거한 뒤(= 저장소 blob 기준) 해시한다.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "src" / "backend_core" / "fixtures"
README = FIXTURES / "README.md"

_spec = importlib.util.spec_from_file_location(
    "collect_fixture", BACKEND / "scripts" / "collect_fixture.py"
)
assert _spec and _spec.loader
collect_fixture = importlib.util.module_from_spec(_spec)
# @dataclass가 sys.modules에서 자기 모듈을 되찾으므로 exec 전에 등록해야 한다.
sys.modules["collect_fixture"] = collect_fixture
_spec.loader.exec_module(collect_fixture)

ROW = re.compile(r"^\|\s*(?P<name>[\w.-]+\.json)\s*\|[^|]*\|[^|]*\|\s*(?P<sha>[0-9a-f]{12}|—)\s*\|")
REPLAY = re.compile(r"_\d{8}\.json$")


def _blob_sha12(path: Path) -> str:
    """저장소 blob과 같은 기준 — 작업 트리가 CRLF여도 같은 값이 나온다."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:12]


def _recorded() -> dict[str, str]:
    return {
        m.group("name"): m.group("sha")
        for line in README.read_text(encoding="utf-8").splitlines()
        if (m := ROW.match(line))
    }


def test_readme_records_every_replay_fixture() -> None:
    on_disk = {p.name for p in FIXTURES.glob("*.json") if REPLAY.search(p.name)}
    missing = on_disk - set(_recorded())
    assert not missing, f"수집 이력 표에 없는 픽스처: {sorted(missing)}"


@pytest.mark.parametrize("name,sha", sorted(_recorded().items()))
def test_readme_sha256_matches_file(name: str, sha: str) -> None:
    path = FIXTURES / name
    if sha == "—":
        assert not path.exists(), f"제외로 기록됐는데 파일이 있습니다: {name}"
        return
    assert path.exists(), f"표에 있는데 파일이 없습니다: {name}"
    assert _blob_sha12(path) == sha, f"{name}: 표 {sha} / 실제 {_blob_sha12(path)}"


def test_latest_kma_base_before_first_publish_returns_previous_day() -> None:
    now = datetime(2026, 8, 5, 0, 5, tzinfo=collect_fixture.KST)
    assert collect_fixture.latest_kma_base(now) == ("20260804", "2300")


def test_latest_kma_base_waits_for_publish_lag() -> None:
    before = datetime(2026, 8, 5, 2, 10, tzinfo=collect_fixture.KST)
    assert collect_fixture.latest_kma_base(before) == ("20260804", "2300")
    after = datetime(2026, 8, 5, 2, 20, tzinfo=collect_fixture.KST)
    assert collect_fixture.latest_kma_base(after) == ("20260805", "0200")


def test_load_key_strips_inline_comment(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SAFETYDATA_SHELTER_KEY=abc123  # 발급일 2026-07-30\n", encoding="utf-8")
    assert collect_fixture.load_key_from_env_file(env, "SAFETYDATA_SHELTER_KEY") == "abc123"


def test_load_key_rejects_empty_value(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("SAFETYDATA_SHELTER_KEY=  # 아직 미발급\n", encoding="utf-8")
    with pytest.raises(collect_fixture.CollectError):
        collect_fixture.load_key_from_env_file(env, "SAFETYDATA_SHELTER_KEY")


def test_fixture_path_rejects_path_separator() -> None:
    with pytest.raises(collect_fixture.CollectError):
        collect_fixture.fixture_path("safetydata_shelter", "../../evil")
