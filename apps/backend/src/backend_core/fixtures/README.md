# fixtures — 오프라인 예비모드용 사전 캐시

`shelters.jsonl`은 **가짜 대피소 목록**입니다(주소 번지는 `000`으로 비워 둔 이유). 실제
대피소는 행정안전부 재난안전데이터 공유 플랫폼에서 받아 교체합니다 — Backend/Infra S1-2.

이 파일은 두 가지 역할을 겸합니다.

1. **워킹 스켈레톤의 대피소 데이터** — 외부 API 승인 전에도 관통 흐름이 돌아가게 합니다.
2. **오프라인 예비모드의 사전 캐시** — 상류 API가 죽었을 때 폴백할 대상입니다(AGENTS.md
   하드 제약). 그래서 픽스처가 `src/` 안에 있습니다: 배포 이미지에 함께 실려야 장애 시점에
   존재합니다.

⚠️ 캐시에서 응답하면 `ShelterList.availability`가 `cache_only`가 되고 `dataAsOf`가 채워집니다.
프론트는 이 값으로 "낡은 데이터"임을 사용자에게 고지합니다 — 조용히 실시간인 척하면
안 됩니다.

## 스키마

| 필드 | 비고 |
|---|---|
| `id` `name` `address` | 그대로 노출 |
| `lat` `lng` | 거리·방향 계산용. 사용자 좌표는 여기 저장되지 않습니다 |
| `isUnderground` | `true`면 호우·침수 재난에서 **서버가 제외**합니다(클라이언트 판단 금지) |
| `hasStairs` | `stairsOk: false`인 사용자에게 상위 배치하지 않습니다 |
| `capacity` | 없으면 `null` |
| `dongCode` | 행정동 코드 10자리 — 조회 키 |

---

# 실 API 응답 replay 픽스처

위 `shelters.jsonl`은 스켈레톤 오프라인 스텁이고,
아래는 실 API를 1회 호출해 동결한 replay 픽스처다. 성격이 다르므로 섞지 않는다.

replay 픽스처도 `src/` 안에 두지만 근거가 다르다. 오프라인 폴백용이 아니라 **코드와 같은
버전으로 움직이고 컨테이너 안에서도 재생할 수 있어야 하기 때문**이다. 실제 내용은 스키마
재현용 표본 10건이라 폴백 캐시로 쓸 수 없다 — 대피소 픽스처는 강릉 한파쉼터 10곳이고,
MVP 1차 대상인 호우·침수와 지역이 맞지 않는다. **폴백용 대피소 캐시는 별도 과제다.**

## 규칙

- 파일명: `{api_source}_{event_type}_{수집일자}.json`
- 수집 후 수정 금지. 갱신이 필요하면 새 파일로 추가하고 사유를 이 문서에 기록한다.
- 동일 이름으로 재수집하면 `collect_fixture.py`가 거부한다.
- 테스트·시연·평가는 실 API가 아니라 이 파일들만 참조한다.
- 응답은 body만이 아니라 봉투째(`header.resultCode`, `totalCount` 포함) 저장한다.
  상류가 무엇을 주장했는지 남아야 오류 응답도 재생할 수 있다.
- 수집 스크립트: `apps/backend/scripts/collect_fixture.py`
- 파일 끝에는 개행을 둔다(`end-of-file-fixer` 훅 규약). 수집 스크립트가 저장 시점에 붙인다.
- sha256은 저장소 blob(LF) 기준이다. 수집 스크립트가 `newline="\n"`으로 저장하므로 어느 OS에서 돌려도 출력값이 이 기준과 같다. 손으로 검산할 때는 주의 — `core.autocrlf=true`인 Windows 작업 트리는 CRLF로 체크아웃되므로 CR을 빼고 계산해야 한다.
- 표의 sha256은 `tests/test_collect_fixture.py`가 커밋된 파일에서 다시 계산해 대조한다. 값이 어긋나면 CI가 잡는다.

## 커밋 전 확인 — 사람에 관한 정보

실 API 응답에는 **사람에 관한 정보가 섞여 들어온다.** 커밋 전에 눈으로 열어 확인한다.

긴급재난문자(DSSP-IF-00247)에서 실제로 걸렸다. 받은 10건 중 9건이 실종자 안내였고
본문에 실명·나이·키·몸무게·착의·신체 특징이 그대로 들어 있었다. 원본이 이미 공개
방송된 문자여도 마찬가지다 — 공개 저장소에 커밋되면 브랜치를 지워도 커밋 해시로
접근되고, 완전 삭제에는 GitHub Support 요청이 필요하다.

**자동으로 걸리지 않는다.** gitleaks, GitHub push protection, pre-commit의
`detect-private-key`는 전부 키 패턴만 본다. 사람에 관한 정보를 보는 게이트는 없다.

섞여 있으면 **마스킹하지 말고 파일째 제외한다.** 마스킹은 원본이 커밋 히스토리에
남고, 어디까지 지웠는지 검증할 방법이 없다. 제외한 사실과 사유는 아래 수집 이력에
적는다.

## 수집 이력

| 파일 | 출처 | 수집일 | sha256[:12] | 비고 |
|---|---|---|---|---|
| safetydata_shelter_baseline_20260730.json | 통합대피소 DSSP-IF-10941 | 2026-07-30 | 69012c0f2276 | 상류 74726건 중 10건 |
| safetydata_emergency_sms_baseline_20260730.json | 긴급재난문자 DSSP-IF-00247 | 2026-07-30 | — | **제외** — 실종자 실명·신체정보 포함. 호우 특보 시점 재수집 예정 |
| safetydata_flood_trace_baseline_20260730.json | 침수흔적도 DSSP-IF-00117 | 2026-07-30 | 3e674af60e19 | 상류 38003건 중 10건 |
| safetydata_hazard_zone_baseline_20260730.json | 지역재해위험지구 DSSP-IF-00058 | 2026-07-30 | 747a6acd4dbd | 상류 2930건 중 10건 |
| safetydata_flood_trace_line_baseline_20260730.json | 침수흔적도 심선 DSSP-IF-20678 | 2026-07-30 | 6e4c7c3bfe2a | 상류 38381건 중 10건 |
| kma_vilage_fcst_baseline_20260730.json | 기상청 단기예보 | 2026-07-30 | 7b2cc9480405 | 발표 1700, nx60 ny127, 300건 14종 |

---

# 경로 그래프 snapshot (issue #224)

침수 회피 경로 엔진(ADR-0017)이 Overpass 상태와 무관하게 준비되도록, 신림동 보행 그래프를
GraphML snapshot으로 동결해 package-data로 싣는다. 로더(`route_snapshot`)는 NetworkX만 쓰고
OSMnx를 import하지 않으므로 기본 backend 환경(geo extra 미설치)과 기본 CI에서도 **네트워크
호출 없이** 읽는다.

## 운영 기본 vs 합성 표본 — 절대 섞지 않는다

- **운영 기본**: `sillim_walk.graphml` + `sillim_walk.metadata.json`. 실제 OSM 추출본이며
  `source_kind: "osm"`이다. **지금은 커밋돼 있지 않다**(실시간 OSM 다운로드가 이번 범위 밖).
  따라서 운영 경로는 부재 상태이고, 엔진의 snapshot-first 경계는 Overpass로 폴백한다.
- **합성 표본**: `sillim_walk.sample.graphml` + `sillim_walk.sample.metadata.json`.
  `build_sample_graph()`로 만든 결정론적 표본으로 `source_kind: "synthetic"`이며 **테스트 전용**이다.
  좌표는 지어낸 격자이지 실측 위치가 아니다. `snapshot_id`가
  `sillim-walk-v2-synthetic-e81aa44f21cc`(실제 커밋된 sample ID)처럼 합성임을 드러내고,
  `SnapshotIdentity.is_synthetic`으로도 판독된다. **운영 기본 신림동 snapshot으로 쓰지 않는다.**

⚠️ 합성 표본을 `sillim_walk.graphml`로 이름만 바꿔 운영 기본으로 승격하지 말 것. 실제 OSM
추출본이 없으면 **부재로 두어 Overpass 폴백**이 돌게 한다.

## snapshot-first 경계와 폴백 조건

`route_engine.load_sillim_walking_graph_snapshot_first`가 기본 그래프 로딩 경계다.
`prepare_sillim_safe_route_engine`의 기본 `graph_loader`도 이것이다.

폴백은 snapshot을 **쌍(pair) 단위**로 판정한다 — GraphML과 metadata 사이드카는 한 snapshot이다.

- **GraphML과 metadata가 둘 다 부재**할 때만 기존 `load_raw_sillim_walking_graph`(Overpass)를
  정확히 1회 호출한다(진짜로 운영 snapshot이 없는 상태).
- **한쪽만 있는 half-pair**(GraphML만 또는 metadata만)는 *부재*가 아니라 *손상*으로 본다.
  `SnapshotFileMissingError`를 던지고 **Overpass는 호출하지 않는다** — half-pair를 부재로
  취급하면 패키징 오류가 네트워크 다운로드 뒤로 숨는다.
- 쌍이 **있으면** 엄격히 로드한다 — checksum 불일치, schema 오류, 크기 초과, GraphML 손상,
  그래프 검증 실패는 모두 `RouteSnapshotError`로 던지고 **Overpass 폴백을 하지 않는다**(손상된
  snapshot을 조용히 새 다운로드로 감추지 않는다).

`overpass_loader` 기본값은 `None`이며 호출 시점에 `load_raw_sillim_walking_graph`로 resolve한다
(정의 시점 바인딩이 아니라서 테스트가 모듈 속성을 monkeypatch하면 폴백이 그것을 집는다).

## provenance 보존 (SnapshotIdentity)

경계는 그래프만이 아니라 `LoadedRouteGraph(graph, identity)`를 돌려준다. `identity`는 snapshot
에서 왔으면 `SnapshotIdentity`, Overpass 폴백에서 왔으면 `None`이다. `prepare_sillim_safe_route_engine`
는 이 identity를 엔진에 실어 두고, 후속 SafetyReceipt가 `engine.snapshot_identity`로 조회한다.
최소 다음 5개 필드가 기본 경계를 통과한 뒤에도 안정적으로 읽힌다: `snapshot_id`, `source`,
`source_kind`, `attribution`, `is_synthetic`. bare 그래프를 돌려주는 레거시/커스텀 로더도
그대로 동작하며 그 경우 `snapshot_identity`는 `None`이다(PR #220 계약 하위 호환).

## metadata 스키마 (schema_version 2)

`schema_version`(현재 **2**), **`graph_kind`**(아래 참조), **`encoded_attrs`**(속성 인코딩
manifest — 아래 참조), `generated_at`(아래 계약 참조), `source`, **`source_kind`**(`osm` 또는
`synthetic` — 이 둘만 허용하며 임의 문자열은 `SnapshotSchemaMismatchError`로 거부),
`source_license`, `source_license_url`, `attribution`, `place`, `network_type`, `simplify`,
`osmnx_version`, `node_count`, `edge_count`, `graph_sha256`.
로더는 최상위가 JSON object인지, 필수 필드가 올바른 타입인지, `graph_kind`·`source_kind`가
허용값인지, `encoded_attrs` manifest 구조가 올바른지, `generated_at`가 계약을 만족하는지,
`node_count`·`edge_count`가 실제 개수와 **정확히 일치**하는지 검증한다(불일치 시 덮어쓰지 않고
node·edge 각각 독립 오류).

`graph_kind`와 `encoded_attrs`를 추가하면서 기존 v1 스키마와 호환되지 않으므로 `schema_version`을
**1 → 2**로 명시적으로 올렸다. 로더는 v2만 승인하고 v1은 `SnapshotSchemaMismatchError`로 거부한다.

### graph type marker (`graph_kind`)

GraphML round-trip은 Python 그래프 클래스를 보존하지 못한다 — 평행 간선이 없는 정상
`MultiDiGraph`는 저장 후 다시 읽으면 `DiGraph`로 축소된다. 그래서 그래프 타입을 metadata의
`graph_kind`(현재 유일 허용값 `"MultiDiGraph"`)로 선언하고, 로더는 이 marker를 근거로 GraphML을
`force_multigraph=True`로 읽은 뒤 결과가 directed(즉 `nx.MultiDiGraph`)인지 재확인한다. 이로써
평행 간선이 없는 정상 `MultiDiGraph`도 key를 보존한 채 round-trip에 성공하고, 무방향 그래프는
(강제해도 `MultiGraph`가 되므로) 여전히 거부된다. marker가 **없거나 타입이 문자열이 아니거나
`"MultiDiGraph"`가 아니면** `SnapshotSchemaMismatchError`다.

marker가 신뢰의 근거이므로, **공식 writer(`save_snapshot`)는 입력이 실제 `nx.MultiDiGraph`인지
저장 전에 검사하고 DiGraph·Graph·MultiGraph 입력은 `TypeError`로 거부한다** — 그래야 marker가
디스크 그래프 타입에 대해 거짓말을 할 수 없다.

로더는 그 밖에 비정수 edge key, `crs` graph 속성 누락, 빈 그래프(노드 0)를 거부한다. node id와
edge key는 정수로 강제·검증된다. NetworkX의 `ValueError`/`TypeError`/`ParseError`는 원인
chaining을 유지한 `SnapshotSchemaMismatchError`로 정규화되고 raw로 노출되지 않는다.

### 속성 인코딩: heterogeneous 타입 보존과 manifest ↔ GraphML 결합

`nx.write_graphml`의 타입 추론은 손실적이다 — 한 키에 `7`과 `"7"`이 섞이면 하나로 뭉개지고,
`1`과 `1.5`가 섞이면 아예 로드 불가 pair가 된다. 그래서 writer는 이 추론을 신뢰하지 않는다.

**인코딩 판정(heterogeneous 규칙).** 한 `(scope, key)`에 대해 그 scope의 모든 값의 정규화된
타입을 수집한 뒤, 다음 중 하나라도 해당하면 그 키의 **모든** 값을 `json.dumps(..., allow_nan=False)`
문자열로 인코딩한다.

- 타입이 둘 이상 섞임 — `int`/`str`, `int`/`float`, `float`/`str`, `str`/`bool` 등. **`bool`과
  `int`는 서로 다른 타입으로 분류**하므로 `True`/`1`도 섞이면 인코딩된다.
- `list`가 하나라도 존재(예: OSMnx `osmid=[101, 202]`).
- `None`이 하나라도 존재. (어떤 요소에 그 키가 **없는 것**은 값이 없는 것으로, `None`과 혼동하지
  않는다.)

homogeneous native scalar 키(모두 같은 `int`/`float`/`str`/`bool`)만 GraphML native로 남고, 실제
round-trip 타입이 정확히 보존된다.

**manifest ↔ GraphML 결합.** 인코딩된 값은 GraphML에서 예약 접두사 `savers::enc::`를 붙인 키 이름
아래에 저장된다 — 즉 **GraphML 자체가 어떤 키가 인코딩됐는지 선언**한다. metadata의 `encoded_attrs`
manifest는 그 사실의 중복 사본이고, loader는 각 scope에서 **GraphML의 예약 키 집합과 manifest가
정확히 일치**해야 로드한다. 그래서 metadata에서 scope나 key를 하나 지우거나 ghost key를 넣으면
GraphML의 관측 집합과 어긋나 `SnapshotSchemaMismatchError`로 거부된다 — metadata만 보고 인코딩
여부를 추측하지 않는다.

```json
"encoded_attrs": { "edge": ["osmid"], "graph": [], "node": [] }
```

- manifest에는 `graph`·`node`·`edge` **세 범위가 정확히 모두** 존재해야 하고, 각 목록은 중복 없이
  **정렬된 canonical form**이어야 한다. 누락·추가 범위, 비문자열·중복·비정렬 키는 모두 거부된다.
- 같은 이름의 키가 graph·node·edge에 있어도 scope별로 독립 판정·검증된다.
- **정상 문자열은 예약 접두사 키가 아니면 절대 디코딩되지 않는다.** `"@@json@@hello"` 같은 사용자
  문자열은 일반 키 아래 그대로 남아 int·list로 둔갑하지 않는다.
- 예약 접두사(`savers::enc::`)는 라운드트립·무결성 장치일 뿐 보안 경계가 아니다. 사용자 속성 이름이
  이 접두사로 시작하면 저장 전에 `SnapshotSerializationError`로 거부하고, loader가 반환하는 graph
  에는 예약 키가 남지 않는다(원래 이름으로 복원 후 제거).
- 예약 base key는 **빈 문자열이면 안 되고**, 한 entity가 같은 base key에 대해 **native 값과
  reserved 값을 동시에** 가지면 거부한다(native 값을 절대 덮어쓰지 않는다). 검증은 **전부 통과한
  뒤에만** graph에 적용하므로, 오류 중 일부 entity만 복원된 graph가 반환되지 않는다.
- 역직렬화는 `json.loads`만 쓰고 **`eval`·`exec`·`pickle` 등 임의 코드 실행을 하지 않는다.**
  `parse_constant`로 `NaN`/`Infinity`/`-Infinity` 토큰을 즉시 거부하고, 디코딩된 값은 **writer와
  동일한 값 계약**으로 다시 검증한다 — `dict`, `1e309`처럼 Infinity가 되는 수, 깊이 33 이상은 모두
  `SnapshotSchemaMismatchError`이며, 정상 scalar·중첩 list는 원래 타입으로 복원된다. malformed JSON은
  원인 chaining으로 정규화된다.

#### save와 load가 공유하는 graph 구조 계약

writer와 loader는 **하나의 구조 validation 함수**(`_validate_graph_structure`)를 공유한다 —
정확한 `nx.MultiDiGraph`, 유효한 str `crs`, node·edge ≥ 1, 정수(비-bool) node ID와 edge key,
유한한 수 node `x`/`y`·edge `length`. writer는 `deepcopy` 사본에 대해 이 계약을 **디스크 쓰기 전에**
검증하고(원본 무변경) 실패 시 `SnapshotSerializationError`, loader는 파싱 후 검증하고 실패 시
`SnapshotSchemaMismatchError`를 낸다. 같은 불변식을 양쪽에 중복 구현하지 않는다. 그래서 **공식
writer가 성공적으로 만든 pair는 공식 loader가 즉시 읽을 수 있다.** (routing 필수 float는 사본에서
`float`로 정규화해, int/float가 섞여 GraphML이 unloadable해지는 것을 막는다.)

#### 지원 / 비지원 속성 타입

| 분류 | 타입 | 처리 |
|---|---|---|
| 지원 | `None`, `bool`, `int`, **finite** `float`, `str` | native scalar 그대로, 또는 위 규칙에 따라 JSON |
| 지원 | 위 타입만 담은 `list`(중첩 포함, 깊이 ≤ `_MAX_ATTR_NESTING_DEPTH`=32) | JSON round-trip |
| 지원(정규화) | **실제** numpy 0-d scalar (`numpy.generic`) | lazy import 후 `isinstance` 확인, `.item()`으로 정규화 |
| 비지원 | `tuple` | **조용히 list로 바꾸지 않고** `SnapshotSerializationError` |
| 비지원 | `bytes`, `set`, `dict`, 임의 객체, numpy array(0-d 포함), numpy 위장 객체 | `SnapshotSerializationError` |
| 비지원 | 위 비지원 값·비유한 float·32 초과/자기참조 중첩을 담은 `list` | `SnapshotSerializationError` |
| 비지원 | 비유한 `float`(NaN/Infinity/-Infinity, numpy 포함) — 어디에 있든 | `SnapshotSerializationError` |

#### finite 요구와 unloadable pair 방지 (writer 선검증)

- **모든 float는 `math.isfinite()`를 통과**해야 한다 — routing 필수(node `x`/`y`, edge `length`)든,
  일반 속성이든, list·중첩 list 내부든, 실제 numpy float든. 비유한 값은 저장 전에 거부한다.
- JSON 인코딩은 `allow_nan=False`를 명시하므로 `NaN`/`Infinity`/`-Infinity`가 Python 전용 비표준
  JSON 토큰으로 파일에 기록되지 않는다.
- metadata 필수 필드는 write 전에 **loader와 동일한 타입·값 계약**으로 검증한다(`source`·
  `source_kind`·`attribution` 등이 문자열이 아니면, `source_kind`가 허용값이 아니면, `generated_at`
  계약 위반이면 거부).
- 자기참조 container는 최대 중첩 깊이 상수(32)로 `RecursionError` 이전에 typed error로 정규화한다.
- writer의 예외 정규화는 저장 경계별로 명시적이다(`deepcopy`·`json`·`nx.write_graphml`의
  `NetworkXError`/`ValueError`/`TypeError`). 넓은 `except Exception`으로 뭉개지 않고,
  `KeyboardInterrupt`·`SystemExit`·`MemoryError`는 잡지 않는다. wrapping 시 원인을
  `raise ... from`으로 보존하고, 직접 preflight 거부에는 가짜 cause를 만들지 않는다.
- **loader도** `nx.read_graphml` 경계에서 `MemoryError`·`KeyboardInterrupt`·`SystemExit`를 먼저
  재전파하고, 예상 가능한 XML/NetworkX/타입 변환 오류(`ValueError`·`TypeError`·`NetworkXError`·
  `ParseError`)만 원인 chaining과 함께 `SnapshotSchemaMismatchError`로 정규화한다.

#### 파일별 atomic write와 fail-closed (pair-level atomic 아님)

- 각 **개별 파일**의 replace만 atomic하다. GraphML과 metadata **pair 전체를 하나의 트랜잭션으로
  교체하지 않는다** — pair-level/crash-proof atomicity를 주장하지 않는다.
- 저장은 GraphML을 먼저 교체하고 **checksum을 담은 metadata를 마지막에** 교체한다. 두 교체 사이에
  실패하면 새 GraphML + 옛/없는 metadata가 남고, loader가 **checksum 불일치** 또는 (기존 pair가
  없었다면) `SnapshotFileMissingError`로 **fail-closed** 거부한다 — silent acceptance나 잘못된
  provenance는 없다. **재시도하면** 완전한 pair로 복구된다.
- 모든 검증은 디스크 쓰기 전에 끝나므로 검증 실패는 파일을 건드리지 않는다. temp 파일은 정상·예외
  경로 모두에서 정리된다(`finally`). OS 강제 종료 중 기존 pair의 가용성까지 보장하지는 않는다.

#### 원본 graph 무변경 · geometry

- `save_snapshot`은 입력 graph를 **`deepcopy`한 사본만** 변경한다. 위의 모든 오류 경로(직렬화·finite·
  metadata·writer)에서도 호출자가 넘긴 graph의 graph/node/edge 속성과 **객체 참조**(list·중첩 list·
  geometry)는 호출 전후 동일하다.
- `save_snapshot_from_osm`은 OSMnx가 돌려준 원본을 건드리지 않는다. shapely `geometry` 제거는
  `save_snapshot(drop_edge_attrs=("geometry",))`로 **사본에서만** 이뤄진다. geometry를 없앤 뒤에도
  node `x`/`y`, edge `length`·`osmid`, edge key, graph `crs`는 정확히 보존되고, 의미 있는 list
  속성(osmid·highway·name …)도 위 방식으로 보존된다. loader는 OSMnx 없이(core-only wheel) 읽는다.

#### 결정론의 범위

같은 graph **객체**를, 같은 node/edge/속성 **삽입 순서**로, 같은 `generated_at`으로 두 번 저장하면
GraphML bytes·metadata bytes·checksum이 동일하다(정렬된 manifest + `sort_keys` metadata).
**논리적으로 동일해도 삽입 순서가 다르면 byte 동일성을 보장하지 않는다** — 이번 범위에서 graph
canonicalization은 하지 않는다. (checksum은 무결성 확인이지 인증·변조 방지 수단이 아니다.)

### generated_at 계약

`generated_at`는 단순 문자열이 아니라 **timezone-aware ISO 8601 instant**여야 한다. 로더는
`datetime.fromisoformat`으로 파싱하고, tz 정보가 없으면(naive), UTC 정규화가 불가하면, 또는
**미래 시각**이면 `SnapshotSchemaMismatchError`로 거부한다(파싱 오류는 `__cause__`로 보존). 미래
판정에는 아주 작은 skew 상수 `route_snapshot._GENERATED_AT_MAX_SKEW = 5분`을 둔다 — 스냅샷을
생성한 호스트 시계가 loader보다 근소하게 앞설 수 있어서다. 상수를 작게 유지해 2027년 같은 명백한
미래 값은 여전히 거부된다. writer가 기본값으로 찍는 현재 UTC 시각은 정상 승인된다.

## 파일 크기 정책

GraphML과 metadata는 **각각 별도의 크기 상한**을 가진다(정상 크기가 크게 다르므로 상한도
오류 메시지도 분리한다).

- `route_snapshot.MAX_SNAPSHOT_BYTES = 25 MiB`(GraphML). 한 행정동 보행 그래프는 작아서(합성
  표본은 수 KB, 실제 신림동 walk 추출본도 1 MB 미만) 25 MiB는 넉넉한 상한이며, GitHub의 50 MiB
  경고 / 100 MiB 하드 리밋보다 한참 아래라 **Git LFS가 필요 없다**.
- `route_snapshot.MAX_SNAPSHOT_METADATA_BYTES = 64 KiB`(metadata 사이드카). 사이드카는 스칼라
  15개 남짓의 평면 JSON이라 실제 파일은 2 KiB 미만이다. 64 KiB는 정상 사이드카보다 몇 자릿수
  크지만, 손상·악성 파일을 **`json.loads`가 전체를 메모리에 읽기 전에** 차단한다.

두 파일 모두 **단일 파일 핸들에서 `상한 + 1`바이트까지만 bounded-read**한다. 읽은 길이가 상한을
넘으면 즉시 `SnapshotTooLargeError`(파싱 전)이고, 넘지 않으면 그 **같은 바이트**로 크기 판정·
checksum·파싱을 모두 수행한다. `stat()` 후 경로를 다시 열어 읽는 구조가 아니므로, 크기를 잰
파일과 실제 파싱한 바이트가 반드시 동일하다(TOCTOU 제거). 오류 메시지가 GraphML인지 metadata인지
밝히므로 어느 쪽이 초과했는지 로그만으로 판독된다. 상한과 정확히 같은 크기는 허용하고, 1바이트
초과부터 거부한다(metadata는 정확히 64 KiB 허용, 64 KiB + 1 거부). metadata는 이 bounded-read
바이트를 UTF-8 디코드 후 JSON 파싱하며, invalid UTF-8과 JSON 오류는 원인 chaining을 유지한
`SnapshotSchemaMismatchError`다.

`.graphml`은 `.gitignore` 무시 대상이 아니므로 **whitelist 예외가 필요 없다**. sha256이 metadata에
있으므로 `.gitattributes`에서 `*.graphml binary`로 두어 autocrlf 체크아웃이 LF를 CRLF로 바꿔
checksum을 깨뜨리지 못하게 한다.

## 라이선스와 attribution (실 OSM 추출본 교체 시에만)

합성 표본은 OSM 데이터가 아니므로 attribution은 「합성 표본 — OSM 데이터 아님」이며 **OSM
attribution 문구(`© OpenStreetMap contributors`)나 ODbL 안내를 담지 않는다** — 합성 데이터가
실제 OSM으로 오인되면 안 되기 때문이다. OSM attribution·ODbL 안내는 실제 OSM 추출본에만
적용한다. 실제 OSM 추출본을 만들면(`save_snapshot_from_osm`) 다음을 채운다.

- `attribution`: `© OpenStreetMap contributors`.
- `source_license`: ODbL 1.0, `source_license_url`: https://opendatacommons.org/licenses/odbl/1-0/ .
- 라우팅 엔진을 포함하는 앱은 OSM을 고지한다(링크: https://www.openstreetmap.org/copyright ).
- `place`·`network_type`·`generated_at`(실제 생성 시각)·`osmnx_version`·`node_count`·`edge_count`·
  raw GraphML `sha256`은 실제 값으로 기록된다.

저장된 추출본을 공개 저장소에 커밋하는 것은 실질적으로 파생 데이터베이스에 해당할 수 있고
(OSMF Attribution Guidelines의 substantial extraction 조항), share-alike 의무 범위는 법적 확인이
필요하다. 지리적 출처를 추정하거나 합성 데이터를 실제 OSM으로 표시하지 않는다.

## 재생성 절차

`route_snapshot`의 dev-only 함수로 만든다(런타임 로더는 파일을 절대 쓰지 않는다).

- 합성 표본(현재 커밋본, 네트워크 불필요):
  `build_sample_graph()` → `save_snapshot(snapshot_path=SAMPLE_SNAPSHOT_PATH, ..., source_kind="synthetic")`.
- 실 OSM 추출본(geo extra + 네트워크 필요, 함수 호출 시점에만 OSMnx 필요):
  `save_snapshot_from_osm(place=..., network_type="walk", simplify=True)` — 운영 경로에 쓴다.

`save_snapshot`은 입력이 실제 `nx.MultiDiGraph`인지 검사한 뒤(아니면 `TypeError`), 입력을
**`deepcopy`한 사본**에서만 속성을 정규화·JSON 인코딩해 GraphML로 쓰고(원본 무변경), 그 바이트의
sha256과 `schema_version: 2`, `graph_kind: "MultiDiGraph"`, 그리고 어떤 키를 인코딩했는지 적은
`encoded_attrs` manifest를 metadata에 기록한다. 같은 입력·같은 `generated_at`이면 결과가
바이트 단위로 결정적이다. 그래프를 손으로 고치고 metadata를 갱신하지 않으면
`tests/backend_core/test_route_snapshot.py`의 checksum 회귀 테스트가 잡는다.

## 장애 판독 (로더가 던지는 오류)

- `SnapshotFileMissingError` — graphml 또는 metadata 파일이 없다. **둘 다** 부재하면 운영 경로
  부재로 정상(→ Overpass 폴백). 한쪽만 부재한 half-pair는 손상으로 보아 이 오류이며 폴백하지
  않는다. 로더 직접 호출에서도, package-data 누락·경로 오설정에서도 이 오류다.
- `SnapshotTooLargeError` — graphml 또는 metadata가 각자의 크기 상한을 넘었다. 어느 파일인지
  메시지로 판독되며, 파싱 전에 거부된다.
- `SnapshotChecksumMismatchError` — graphml 바이트가 metadata의 `graph_sha256`과 다르다. 파일 손상
  또는 metadata 미갱신. autocrlf가 의심되면 `.gitattributes` binary 규칙을 확인한다.
- `SnapshotSchemaMismatchError` — metadata 최상위가 object가 아니거나(또는 invalid UTF-8/JSON),
  필수 필드 누락·타입 오류, `graph_kind`가 `"MultiDiGraph"` 아님, `source_kind`가 허용값
  (`osm`/`synthetic`) 아님, `generated_at`가 ISO 8601 아님·tz 없음·미래, `schema_version` 불일치
  (v2 아님), GraphML 파싱 실패(비정수 node id 등), `node_count`·`edge_count` 불일치(각각 독립),
  `crs` graph 속성 누락, 빈 그래프(노드 0), 비정수 edge key, node `x`/`y` 또는 edge `length`
  누락·비유한값, `encoded_attrs` manifest 오류(세 범위 정확 불일치·비-dict·비문자열·중복·비정렬 키),
  **manifest와 GraphML의 예약 키 집합 불일치**(metadata에서 scope/key를 지웠거나 ghost key 추가),
  **한 entity의 native+reserved 이중 표현**·빈 reserved base key, manifest-지정 키의 손상되거나
  비지원 형태(`dict`·비유한·과중첩)인 decoded payload, 또는 (marker를 강제 로드했는데) 결과가
  directed `MultiDiGraph`가 아니다(무방향 Graph·MultiGraph). 원인 예외는 chaining으로 보존된다.
  참고: 디스크 그래프 타입 자체(DiGraph 입력)는 **writer가 `TypeError`로** 막는다.
  `MemoryError`·`KeyboardInterrupt`·`SystemExit`는 이 오류로 바뀌지 않고 그대로 전파된다.
- `SnapshotSerializationError` — **저장(write) 경계 전용.** 구조 계약 위반(빈 그래프, `crs` 누락,
  node `x`/`y`·edge `length` 누락·비유한, 비정수 node id/edge key 등), 지원되지 않는 속성 값 타입
  (`tuple`·`bytes`·`set`·`dict`·numpy array·numpy 위장 객체·임의 객체, 또는 이들을 담은 `list`),
  비유한 float, 32 초과·자기참조 중첩, 예약 접두사와 충돌하는 사용자 키, loader 계약을 어길 metadata
  필드, 또는 `nx.write_graphml`/`json`의 `NetworkXError`/`ValueError`/`TypeError`를 **파일을 쓰기
  전에** 거부한다. raw 라이브러리 예외가 경계 밖으로 노출되지 않는다. wrapping 시 원인을 chaining하고
  직접 preflight 거부에는 cause가 없다. (load 경계에서는 나오지 않는다.)
- **Overpass 폴백 진입 조건**: 운영 snapshot 파일이 **쌍째** 부재할 때만. 위 오류들(half-pair
  포함)에서는 폴백하지 않는다.
