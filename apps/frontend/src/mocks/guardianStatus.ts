// Mock data for the guardian mobile UI (/guardian) — first-pass UI work
// only, built BEFORE the #122 GuardianStatus API/FCM contract merges. Every
// value below is hardcoded example data, kept in this single file so a real
// response can later replace `GUARDIAN_MOCK` without touching the screens
// that read it (see pages/Guardian.tsx for how it's consumed).
//
// DO NOT read this as a measurement or a finalized contract shape — it is a
// presentation-layer placeholder, same spirit as mocks/profiles.ts and
// mocks/chatReplies.ts.

import grandma from '../assets/grandma.png'
import grandpa from '../assets/grandpa.png'

// The persona drives which profile photo renders. Keeping this as a key
// (rather than baking a specific image import into GUARDIAN_MOCK) means the
// same card component works unchanged if the mock protected person is later
// swapped from 박순자(grandma) to a 할아버지 case(grandpa) — only this map
// or the mock object's `persona` field needs to change, not any component.
export type Persona = 'grandma' | 'grandpa'

export const PERSONA_IMAGE: Record<Persona, string> = {
  grandma,
  grandpa,
}

export interface ProtectedPerson {
  name: string
  relation: string
  age: number
  persona: Persona
}

export interface AlertInfo {
  disaster: string
  district: string
  sentAt: string
}

// 'caution' is the only level this mock UI renders today (첨부 시안 기준).
// Kept as a union rather than a bare string so a future 'safe' / 'danger'
// state has a typed home instead of a magic string appearing ad hoc.
export type StatusLevel = 'caution' | 'safe' | 'danger'

export interface StatusInfo {
  level: StatusLevel
  headline: string
  detailLines: string[]
  lastResponseAt: string
}

// One question/answer/note triple. `note` is the supporting explanation line
// shown under the answer (「행동 기록상, …」 style) — optional because a
// freeform fallback answer may not always need one.
export interface QaTurn {
  question: string
  answer: string
  note?: string
}

export interface GuardianMockData {
  protectedPerson: ProtectedPerson
  alert: AlertInfo
  status: StatusInfo
  // Each recommended question carries its own canned answer/note in one
  // object — the button label IS `question`, so tapping it just appends
  // this exact object to `turns`. No separate string-keyed lookup table:
  // a question and its answer used to live in two places (this array's
  // label + a `mockAnswers[question]` map) that had to match character for
  // character, so any edit to one silently broke the other's lookup.
  recommendedQuestions: QaTurn[]
  // Shown for any freeform question that isn't one of the three recommended
  // ones. Deliberately a refusal-shaped answer, not an invented one — see
  // the phrasing rule below.
  freeformFallback: QaTurn
}

// PHRASING RULE for every answer/note string in this file (carries over to
// however the real 보호자 응답 정확도 verifier is written later):
//   - State only what the (mock) log observed.
//   - Absence of a log entry is phrased as "확인되지 않습니다" /
//     "기록이 없습니다" — never "하지 않았습니다" (that asserts a negative
//     fact the log cannot prove).
//   - No inferred duration, no inferred count, no inferred cause.
//   - No "그 뒤" / "이후" — don't imply a sequence or causal link the log
//     itself doesn't state.
export const GUARDIAN_MOCK: GuardianMockData = {
  protectedPerson: {
    name: '박순자',
    relation: '어머니',
    age: 76,
    persona: 'grandma',
  },
  alert: {
    disaster: '호우 경보',
    district: '관악구',
    sentAt: '8월 21일 (수) 10:28',
  },
  status: {
    level: 'caution',
    headline: '주의가 필요한 상황이에요',
    detailLines: ['호우 경보 안내 메시지를 발송했어요.', '아직 확인 응답이 없어요.'],
    lastResponseAt: '10:33',
  },
  recommendedQuestions: [
    {
      question: '현재 대피 절차를 진행하고 있나요?',
      answer: '대피 절차를 진행했다는 기록은 확인되지 않습니다.',
      note: '행동 기록에서 안내 메시지 확인 기록만 확인됩니다.',
    },
    {
      question: '도움을 요청한 상태인가요?',
      answer: '도움을 요청했다는 기록은 확인되지 않습니다.',
      note: '행동 기록상 도움 요청과 관련된 이벤트가 없습니다.',
    },
    {
      question: '현재까지 어떤 행동을 했나요?',
      answer: '기록된 행동은 안내 메시지 확인입니다.',
      note: '그 외 추가로 기록된 행동은 없습니다.',
    },
  ],
  freeformFallback: {
    question: '',
    answer: '해당 질문에 대해 확인된 행동 기록이 없습니다.',
    note: '기록에 없는 내용은 답변드리기 어렵습니다.',
  },
}
