// SummaryScreen 안전수칙 목록용 작은 아이콘 3종. 텍스트 앞의 "·" 점을
// 대체한다 — 항목 뜻을 아이콘으로도 바로 알아볼 수 있게 하는 게 목적이라
// 장식이 아니라 정보(어떤 행동인지)를 담는다. 색은 `C.mandatory`(ISO 7010
// 지시표지 파랑)를 쓴다 — 이 표준은 "반드시 해야 하는 행동"을 파랑 원형으로
// 구분하므로, 배경의 하자드 옐로(경고)·도착 화면의 초록(안전)과 헷갈리지
// 않는 세 번째 색 카테고리로 의도했다.
import { C } from '../../lib/tokens'

const ICON_PROPS = { width: 20, height: 20, viewBox: '0 0 24 24' } as const

export function PowerIcon() {
  return (
    <svg {...ICON_PROPS} aria-hidden="true">
      <rect x="6" y="4" width="12" height="16" rx="2" fill="none" stroke={C.mandatory} strokeWidth="2" />
      <line x1="12" y1="8" x2="12" y2="13" stroke={C.mandatory} strokeWidth="2" strokeLinecap="round" />
      <circle cx="12" cy="17" r="1.4" fill={C.mandatory} />
    </svg>
  )
}

export function DoorIcon() {
  return (
    <svg {...ICON_PROPS} aria-hidden="true">
      <rect x="5" y="3" width="14" height="18" rx="1" fill="none" stroke={C.mandatory} strokeWidth="2" />
      <circle cx="15" cy="12" r="1.3" fill={C.mandatory} />
      <path d="M19 12 h4" stroke={C.mandatory} strokeWidth="2" strokeLinecap="round" />
      <path d="M20.5 9.5 L23 12 L20.5 14.5" stroke={C.mandatory} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function StairsIcon() {
  return (
    <svg {...ICON_PROPS} aria-hidden="true">
      <path
        d="M4 20 h4 v-4 h4 v-4 h4 v-4 h4 v-2"
        fill="none"
        stroke={C.mandatory}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
