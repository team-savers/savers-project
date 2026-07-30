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

위 `shelters.jsonl`·`dev_sample_flood_event.json`은 스켈레톤 오프라인 스텁이고,
아래는 실 API를 1회 호출해 동결한 replay 픽스처다. 성격이 다르므로 섞지 않는다.

## 규칙

- 파일명: `{api_source}_{event_type}_{수집일자}.json`
- 수집 후 수정 금지. 갱신이 필요하면 새 파일로 추가하고 사유를 이 문서에 기록한다.
- 동일 이름으로 재수집하면 `collect_fixture.py`가 거부한다.
- 테스트·시연·평가는 실 API가 아니라 이 파일들만 참조한다.
- 응답은 body만이 아니라 봉투째(`header.resultCode`, `totalCount` 포함) 저장한다.
  상류가 무엇을 주장했는지 남아야 오류 응답도 재생할 수 있다.
- 수집 스크립트: `apps/backend/scripts/collect_fixture.py`

## 수집 이력

| 파일 | 출처 | 수집일 | sha256[:12] | 비고 |
|---|---|---|---|---|
| safetydata_shelter_baseline_20260730.json | 통합대피소 DSSP-IF-10941 | 2026-07-30 | a6558b1c6d44 | 상류 74726건 중 10건 |
| safetydata_emergency_sms_baseline_20260730.json | 긴급재난문자 DSSP-IF-00247 | 2026-07-30 | a0fb852f1d1e | 상류 57097건 중 10건 |
| safetydata_flood_trace_baseline_20260730.json | 침수흔적도 DSSP-IF-00117 | 2026-07-30 | 3ab79382156d | 상류 38003건 중 10건 |
| safetydata_hazard_zone_baseline_20260730.json | 지역재해위험지구 DSSP-IF-00058 | 2026-07-30 | f727bdc18f64 | 상류 2930건 중 10건 |
| safetydata_flood_trace_line_baseline_20260730.json | 침수흔적도 심선 DSSP-IF-20678 | 2026-07-30 | ad029519f033 | 상류 38381건 중 10건 |
| kma_vilage_fcst_baseline_20260730.json | 기상청 단기예보 | 2026-07-30 | 061083861e57 | 발표 1700, nx60 ny127, 300건 14종 |
