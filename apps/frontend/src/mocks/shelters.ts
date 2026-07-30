// Mock shelters around 서원동/신림동. Synthetic data — see ./README.md.
//
// Fixture variety:
//   - one with isUnderground: true (server-excluded from `items`, surfaced
//     in `excluded: [{reason:'underground', count:N}]`).
//   - two with hasStairs: true (must sink below for stairsOk:false).
//   - a mix of bearing: Bearing and bearing: null (the latter happens when
//     only the dongCode basis is known — no coordinate).
//
// ShelterList fixtures cover these branches:
//   - hazardMatch:    inside / outside / unknown — one fixture each.
//   - availability:   ok (real-time list), cache_only (stale snapshot),
//                     upstream_unavailable (empty list, fallback guidance),
//                     all_excluded (every candidate excluded).
//   - dataAsOf:       null (real-time) AND a string (cache snapshot).
//
// `excluded` mirrors what the server would have stripped — the frontend
// does NOT re-filter underground items; it trusts the server.
//
// Coordinates (lat/lng) are synthetic-but-plausible positions around
// 관악구 서원동/신림동 (lat ~37.47–37.49, lng ~126.92–126.95) so the Kakao
// Map in ShelterMap has real pins to render. They are NOT surveyed — only
// good enough for the demo. Public shelter data sources do carry missing
// coordinates from time to time; `sh05` ([데모] 관악민원센터) keeps
// lat/lng undefined ON PURPOSE so the "no-coord shelter still appears in
// the text list, just without a marker" path is exercised end-to-end. The
// contract makes lat/lng optional (`Shelter.lat?: number`); this fixture
// honours that.

import type { Bearing, Shelter, ShelterList } from '../api/types'

// Distance figures are illustrative straight-line meters from a notional
// basis point and only need to be plausible for the demo, not surveyed.

// Inside the hazard zone, real-time (dataAsOf: null), normal availability.
// Underground shelter moved into `excluded` (count: 1).
export const SHELTERS_DONG_INSIDE: ShelterList = {
  hazardMatch: 'inside',
  availability: 'ok',
  basis: 'dongCode',
  dataAsOf: null,
  excluded: [{ reason: 'underground', count: 1 }],
  items: [
    {
      id: 'sh01',
      name: '[데모] 서원복지회관',
      address: '서울 특별시 관악구 서원로 12',
      lat: 37.4827,
      lng: 126.9295,
      distanceM: 220,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh02',
      name: '[데모] 신림체육관',
      address: '서울 특별시 관악구 신림로 100',
      lat: 37.4791,
      lng: 126.9403,
      distanceM: 480,
      bearing: null,
      isUnderground: false,
      hasStairs: true,
    },
    {
      id: 'sh04',
      name: '[데모] 난향초교',
      address: '서울 특별시 관악구 난향로 33',
      lat: 37.4768,
      lng: 126.9331,
      distanceM: 720,
      bearing: null,
      isUnderground: false,
      hasStairs: true,
    },
    {
      id: 'sh05',
      name: '[데모] 관악민원센터',
      address: '서울 특별시 관악구 신림로 217',
      // ⚠️ No lat/lng — this is the "좌표 누락" test fixture. Keeps its
      // text-list entry but is skipped by ShelterMap's marker loop.
      distanceM: 950,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh06',
      name: '[데모] 관악노인복지센터',
      address: '서울 특별시 관악구 청룡로 50',
      lat: 37.4742,
      lng: 126.9278,
      distanceM: 600,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
  ],
}

// Outside the hazard zone — shelter list still returned, wording differs.
export const SHELTERS_DONG_OUTSIDE: ShelterList = {
  hazardMatch: 'outside',
  availability: 'ok',
  basis: 'dongCode',
  dataAsOf: null,
  excluded: [],
  items: [
    {
      id: 'sh01',
      name: '[데모] 서원복지회관',
      address: '서울 특별시 관악구 서원로 12',
      lat: 37.4827,
      lng: 126.9295,
      distanceM: 220,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh06',
      name: '[데모] 관악노인복지센터',
      address: '서울 특별시 관악구 청룡로 50',
      lat: 37.4742,
      lng: 126.9278,
      distanceM: 600,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
  ],
}

// Unknown hazard zone (좌표 누락·역지오코딩 실패·위험구역 데이터 결측).
// UI keeps evacuation readiness + action buttons (does NOT collapse to "outside").
export const SHELTERS_DONG_UNKNOWN: ShelterList = {
  hazardMatch: 'unknown',
  availability: 'ok',
  basis: 'dongCode',
  dataAsOf: null,
  excluded: [{ reason: 'underground', count: 1 }],
  items: [
    {
      id: 'sh01',
      name: '[데모] 서원복지회관',
      address: '서울 특별시 관악구 서원로 12',
      lat: 37.4827,
      lng: 126.9295,
      distanceM: 220,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh02',
      name: '[데모] 신림체육관',
      address: '서울 특별시 관악구 신림로 100',
      lat: 37.4791,
      lng: 126.9403,
      distanceM: 480,
      bearing: null,
      isUnderground: false,
      hasStairs: true,
    },
  ],
}

// Coordinate-basis variant — same shelters gain bearing values; distances
// recomputed to a notional user coordinate for demo plausibility.
// Real-time (dataAsOf: null), inside hazard zone.
export const SHELTERS_COORDINATE_INSIDE: ShelterList = {
  hazardMatch: 'inside',
  availability: 'ok',
  basis: 'coordinate',
  dataAsOf: null,
  excluded: [{ reason: 'underground', count: 1 }],
  items: [
    {
      id: 'sh01',
      name: '[데모] 서원복지회관',
      address: '서울 특별시 관악구 서원로 12',
      lat: 37.4827,
      lng: 126.9295,
      distanceM: 180,
      bearing: 'NE' as Bearing,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh02',
      name: '[데모] 신림체육관',
      address: '서울 특별시 관악구 신림로 100',
      lat: 37.4791,
      lng: 126.9403,
      distanceM: 410,
      bearing: 'SE' as Bearing,
      isUnderground: false,
      hasStairs: true,
    },
    {
      id: 'sh04',
      name: '[데모] 난향초교',
      address: '서울 특별시 관악구 난향로 33',
      lat: 37.4768,
      lng: 126.9331,
      distanceM: 680,
      bearing: 'NW' as Bearing,
      isUnderground: false,
      hasStairs: true,
    },
    {
      id: 'sh05',
      name: '[데모] 관악민원센터',
      address: '서울 특별시 관악구 신림로 217',
      // ⚠️ No lat/lng — same as SHELTERS_DONG_INSIDE; this fixture keeps
      // the no-coord shelter so the coordinate-basis path also exercises
      // the "missing coord, no marker" branch.
      distanceM: 990,
      bearing: 'N' as Bearing,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh06',
      name: '[데모] 관악노인복지센터',
      address: '서울 특별시 관악구 청룡로 50',
      lat: 37.4742,
      lng: 126.9278,
      distanceM: 550,
      bearing: 'S' as Bearing,
      isUnderground: false,
      hasStairs: false,
    },
  ],
}

// Cached snapshot: the upstream shelter API was unreachable so the server
// answered from a pre-cached list. availability is cache_only and dataAsOf
// carries the cache timestamp — the UI must disclose this is not fresh data.
export const SHELTERS_DONG_CACHE: ShelterList = {
  hazardMatch: 'inside',
  availability: 'cache_only',
  basis: 'dongCode',
  dataAsOf: '2026-07-20T03:00:00.000Z',
  excluded: [],
  items: [
    {
      id: 'sh01',
      name: '[데모] 서원복지회관',
      address: '서울 특별시 관악구 서원로 12',
      lat: 37.4827,
      lng: 126.9295,
      distanceM: 220,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
    {
      id: 'sh06',
      name: '[데모] 관악노인복지센터',
      address: '서울 특별시 관악구 청룡로 50',
      lat: 37.4742,
      lng: 126.9278,
      distanceM: 600,
      bearing: null,
      isUnderground: false,
      hasStairs: false,
    },
  ],
}

// Upstream API outage: the server could not build a list at all. This is a
// normal 200 response (NOT an error) — availability is upstream_unavailable,
// items is empty, and the UI must keep the fallback guidance visible so the
// last guidance still reaches the user even when the network is down. The
// user must never see a bare "주변에 대피소가 없습니다" that could make them
// stay in place.
//
// `dataAsOf` carries the timestamp of the last successful cache snapshot.
// The contract requires cached data to disclose its as-of time so the UI
// can show "언제 기준 정보인지". The value below is a static fixture
// timestamp (the demo does not advance the clock); it only needs to be a
// plausible ISO timestamp, not the real last-good time.
export const SHELTERS_UPSTREAM_UNAVAILABLE: ShelterList = {
  hazardMatch: 'unknown',
  availability: 'upstream_unavailable',
  basis: 'dongCode',
  dataAsOf: '2026-07-21T02:30:00.000Z',
  excluded: [],
  items: [],
}

// All-excluded: the server found candidates for this location but excluded
// ALL of them (침수 위험·운영 중단·가는 길을 알 수 없음). `items` is empty by
// definition (everything was excluded); the UI must render the
// AllExcludedNotice and NOT fall through to the empty-list "주변에 안내
// 가능한 대피소가 없습니다" fallback line.
export const SHELTERS_ALL_EXCLUDED_VERTICAL: ShelterList = {
  hazardMatch: 'inside',
  availability: 'all_excluded',
  basis: 'dongCode',
  dataAsOf: null,
  excluded: [
    { reason: 'underground', count: 2 },
    { reason: 'closed', count: 1 },
    { reason: 'unreachable', count: 1 },
  ],
  items: [],
}

// Re-export the bare Shelter[] arrays for any caller that still wants the
// raw list (kept for backwards compatibility during the v0.3 migration).
export const SHELTERS_DONG: Shelter[] = SHELTERS_DONG_INSIDE.items
export const SHELTERS_COORDINATE: Shelter[] = SHELTERS_COORDINATE_INSIDE.items
