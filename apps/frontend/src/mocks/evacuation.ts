export const mockAlert = {
  area: '관악구',
  warning: '호우 경보',
  announcedAt: '8월 21일 (수) 10:28',
  source: '기상청 공식 특보',
} as const

export const mockProfile = {
  preregistered: false,
  ageGroup: '70대',
  gender: '여성',
  mobility: '계단 이용에 도움이 필요함',
} as const

export const mockShelter = {
  name: '신림중학교 체육관',
  address: '서울 관악구 신림동',
  type: '지상 대피소',
  minutes: 13,
  distance: '520m',
  tags: ['지상 2층 이상', '여유고 +4.2m', '수용 380명', '야간 개방'],
  recommendationDeadline: '21:35',
  minutesRemaining: 23,
} as const

export const mockRoute = {
  blockedSegments: 3,
  avoidedDistance: '520m',
  avoidedMinutes: 13,
  unusedShortestDistance: '450m',
} as const
