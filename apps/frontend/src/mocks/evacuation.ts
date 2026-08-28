import type { Guardian, ShelterCaution } from '../api/types'

export const mockAlert = {
  area: '관악구',
  warning: '호우 경보',
  announcedAt: '8월 21일 (수) 10:28',
  source: '[데모] 기상청 공식 특보',
} as const

export const mockProfile = {
  preregistered: false,
  ageGroup: '70대',
  gender: '여성',
  mobility: '계단 이용에 도움이 필요함',
} as const

// v0.9 (ADR-0016): `cautions`는 실제 계약 `Shelter.cautions`와 같은 값
// 집합('stairs' | 'over_time')을 쓴다 — 이 화면(/evacuation)은 다른 모든
// 필드(name/address/type/tags/…)와 마찬가지로 실제 API가 아니라 고정
// mock 하나를 그리는 자체 완결형 데모라, 이 필드도 같은 성격이다. 다만
// 실제 계약이 정의한 값 밖의 새 caution 의미를 만들지 않기 위해 타입을
// api/types.ts에서 그대로 가져와 쓴다.
//
// ['stairs'] 하나를 택했다 — mockProfile.mobility가 이미 "계단 이용에
// 도움이 필요함"이라고 말하고 있어, 이 대피소에 계단 주의가 붙는 쪽이
// 데모 시나리오 안에서 서로 앞뒤가 맞는다(새로 지어낸 맥락이 아니라 기존
// mock 서사와 일치시킨 것).
export const mockShelter = {
  name: '[데모] 신림중학교 체육관',
  address: '서울 관악구 신림동',
  type: '지상 대피소',
  minutes: 13,
  distance: '520m',
  tags: ['지상 2층 이상', '여유고 +4.2m', '수용 380명', '야간 개방'],
  cautions: ['stairs'] as ShelterCaution[],
  recommendationDeadline: '21:35',
  minutesRemaining: 23,
} as const

// v0.9: HelpRequestStep offers a guardian contact button alongside 119,
// same as the real Profile.guardian contract (Guardian: name/relation/
// phone, null = no guardian). This demo reuses an existing guardian
// example already used in mocks/profiles.ts (이영희 · 딸 ·
// 010-0000-0001) instead of inventing new demo data. `null` here would
// mean "no guardian" and HelpRequestStep hides the guardian button in
// that case — this demo profile has one, so both contact buttons show.
export const mockGuardian: Guardian | null = {
  name: '이영희',
  phone: '010-0000-0001',
  relation: '딸',
}

export const mockRoute = {
  blockedSegments: 3,
  avoidedDistance: '520m',
  avoidedMinutes: 13,
  unusedShortestDistance: '450m',
} as const
