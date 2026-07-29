"""국민행동요령 CSV 청킹 규칙.

Convention: tests/ mirrors src/ (src/ai_engine/chunking.py -> tests/test_chunking.py).
"""

from pathlib import Path

import pytest

from ai_engine.chunking import Chunk, chunk_csv, chunk_rows, parse_rows

FIXTURE_PATH = (
    Path(__file__).parent.parent / "src" / "ai_engine" / "fixtures" / "typhoon_sample.csv"
)

_CSV_HEADER = (
    "actRmks,contentsUrl,safety_cate1,safety_cate2,safety_cate3,safety_cate4,"
    "safety_cate_nm1,safety_cate_nm2,safety_cate_nm3\n"
)


def _write_csv(tmp_path: Path, *rows: str) -> Path:
    path = tmp_path / "sample.csv"
    path.write_text(_CSV_HEADER + "".join(rows), encoding="utf-8")
    return path


def _row(
    act_rmks: str,
    *,
    contents_url: str = "",
    stage: str = "특보중 행동요령",
    disaster_type: str = "태풍",
) -> str:
    return f'"{act_rmks}","{contents_url}","01","01001","01001002","","자연재난","{disaster_type}","{stage}"\n'


def test_header_echo_row_is_dropped(tmp_path: Path) -> None:
    """CSV export가 컬럼 설명을 데이터 행으로 반복하는 결함 행은 파싱에서 제외되어야 한다."""
    path = _write_csv(
        tmp_path,
        '"콘텐츠 내용","콘텐츠 URL","카테고리1코드","카테고리2코드","카테고리3코드",'
        '"카테고리4코드","카테고리1명칭","카테고리2명칭","카테고리3명칭"\n',
        _row("- 실제 지침 문장"),
    )
    rows = parse_rows(path)
    assert len(rows) == 1
    assert rows[0]["actRmks"] == "- 실제 지침 문장"


def test_dash_row_is_a_standalone_chunk(tmp_path: Path) -> None:
    path = _write_csv(tmp_path, _row("- 실제 지침 문장"))
    chunks = chunk_csv(path)
    assert chunks == [
        Chunk(
            text="- 실제 지침 문장",
            disaster_type="태풍",
            stage="특보중 행동요령",
            url=None,
        )
    ]


def test_no_prefix_row_with_stage_is_standalone_not_numbered(tmp_path: Path) -> None:
    """접두사 없는 일반 문장(59/62/63행 케이스)은 숫자 그룹에 억지로 끼워넣지 않는다."""
    path = _write_csv(
        tmp_path,
        _row("이웃과 함께 안전을 확인하고 정보를 공유합니다.", stage="예보시 행동요령"),
        _row("1. 태풍의 진로를 확인합니다.", stage="예보시 행동요령"),
    )
    chunks = chunk_csv(path)
    standalone = [c for c in chunks if c.step_order is None]
    numbered = [c for c in chunks if c.step_order is not None]
    assert len(standalone) == 1
    assert standalone[0].text == "이웃과 함께 안전을 확인하고 정보를 공유합니다."
    assert len(numbered) == 1


def test_url_only_row_without_stage_is_excluded(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        _row(
            "태풍 대비 국민 행동요령(20초 스팟)",
            contents_url="http://example.com/video",
            stage="",
        ),
    )
    assert chunk_csv(path) == []


def test_empty_act_rmks_row_is_excluded_even_with_a_stage(tmp_path: Path) -> None:
    """실제 홍수 코퍼스의 아이콘 이미지 행(본문 텍스트 없음, 단계는 있음) 회귀 테스트 —
    인용할 텍스트가 없으니 stage 유무와 무관하게 제외돼야 한다."""
    path = _write_csv(
        tmp_path,
        _row(
            "",
            contents_url="http://mepv2.safekorea.go.kr/.../icon_07.png",
            stage="홍수 우려 때는",
            disaster_type="홍수",
        ),
    )
    assert chunk_csv(path) == []


def test_numbered_rows_are_grouped_with_step_order_and_total(tmp_path: Path) -> None:
    path = _write_csv(
        tmp_path,
        _row("1. 첫 번째 단계", stage="예보시 행동요령"),
        _row("2. 두 번째 단계", stage="예보시 행동요령"),
        _row("3. 세 번째 단계", stage="예보시 행동요령"),
    )
    chunks = chunk_csv(path)
    assert len(chunks) == 3
    assert all(c.step_total == 3 for c in chunks)
    assert sorted(c.step_order for c in chunks) == [1, 2, 3]


def test_numbered_groups_do_not_mix_across_stage(tmp_path: Path) -> None:
    """같은 재난이라도 단계(예보시/특보중)가 다르면 별개 그룹으로 취급한다."""
    path = _write_csv(
        tmp_path,
        _row("1. 예보시 단계", stage="예보시 행동요령"),
        _row("1. 특보중 단계", stage="특보중 행동요령"),
        _row("2. 특보중 단계", stage="특보중 행동요령"),
    )
    chunks = chunk_csv(path)
    by_stage = {
        c.stage: c for c in chunks if c.text == "1. 예보시 단계" or c.text == "1. 특보중 단계"
    }
    assert by_stage["예보시 행동요령"].step_total == 1
    assert by_stage["특보중 행동요령"].step_total == 2


@pytest.mark.skipif(not FIXTURE_PATH.exists(), reason="typhoon_sample.csv fixture not present")
def test_committed_typhoon_fixture_shape() -> None:
    """실제 커밋된 픽스처에 규칙을 적용했을 때의 전체 모양 — 회귀 방지용."""
    rows = parse_rows(FIXTURE_PATH)
    chunks = chunk_rows(rows)

    excluded_count = sum(1 for r in rows if not r["safety_cate_nm3"].strip())
    assert len(rows) == len(chunks) + excluded_count

    numbered = [c for c in chunks if c.step_order is not None]
    standalone = [c for c in chunks if c.step_order is None]
    assert numbered and standalone

    groups = {(c.disaster_type, c.stage) for c in numbered}
    for disaster_type, stage in groups:
        group_chunks = [c for c in numbered if (c.disaster_type, c.stage) == (disaster_type, stage)]
        totals = {c.step_total for c in group_chunks}
        assert totals == {len(group_chunks)}
        assert sorted(c.step_order for c in group_chunks) == list(range(1, len(group_chunks) + 1))
