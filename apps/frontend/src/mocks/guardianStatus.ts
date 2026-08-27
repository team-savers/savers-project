// Mock data for the guardian mobile UI (/guardian) — a mock-based UI preview
// route (see pages/Guardian.tsx header comment for scope). Every value below
// is hardcoded example data, kept in this single file so a real response can
// later replace `GUARDIAN_MOCK` without touching the screens that read it.
//
// DO NOT read this as a measurement or a finalized contract shape — it is a
// presentation-layer placeholder, same spirit as mocks/profiles.ts and
// mocks/chatReplies.ts. It DOES, however, follow the shape and meaning of the
// existing Guardian contract (`GuardianStatus`/`SafetyStatus` in
// ../api/types.ts, and the `GuardianQuestionId` enum in
// packages/contracts/openapi.yaml) — the mock exercises real contract
// fields/values instead of inventing its own status vocabulary.

import type { GuardianStatus } from '../api/types'
import grandma from '../assets/grandma.webp'
import grandpa from '../assets/grandpa.webp'

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

// Presentation-only fields with no home in the Guardian contract (profile
// photo, relation label, age) — kept as a separate mock type from
// `GuardianStatus` rather than smuggled into it, per the review note that
// display-only fields may stay in a separate presentation mock.
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

// Mirrors packages/contracts/openapi.yaml `GuardianQuestionId` — the three
// recommended-question ids the Guardian Q&A contract supports in this phase.
// The contract deliberately closes support to exactly these three (list-
// outside/free-text input is 422, not a 200 fallback) — do not add a fourth
// value or a free-text id here.
//
// Not yet mirrored into api/types.ts: that file mirrors the browser-facing
// endpoints already wired into a screen (getGuardianStatus, etc.); the
// Guardian ask/answer contract types have no real caller yet since /guardian
// here stays a mock-only UI preview. Add them there together with the real
// `/v1/guardian/{token}/ask` wiring, not before.
export type GuardianQuestionId = 'evacuation_progress' | 'help_request' | 'arrival_status'

// One question/answer/note triple, one per recommended `questionId`.
// `questionId` ties the button to the contract question it stands for so a
// screen never has to guess from the label text. `note` is an optional
// supporting line under the answer — none of today's three answers need one.
export interface QaTurn {
  questionId: GuardianQuestionId
  question: string
  answer: string
  note?: string
}

export interface GuardianMockData {
  protectedPerson: ProtectedPerson
  alert: AlertInfo
  // Directly typed as the `GuardianStatus` contract shape (api/types.ts)
  // instead of a screen-invented status summary — this mock's job is to
  // exercise the real response fields (openedAt/respondedAt/lastResponse/
  // safetyStatus), not to add a judgement layer on top of them. `stage` is
  // part of the contract response and kept here for shape-completeness, even
  // though the screen does not render it as a safety level (see
  // pages/Guardian.tsx).
  status: GuardianStatus
  // Exactly 3 entries, 1:1 with GuardianQuestionId. No free-form entry and
  // no 4th question — the contract closes support to these three.
  recommendedQuestions: QaTurn[]
}

// PHRASING RULE for every answer/note string in this file (carries over to
// however the real 보호자 응답 정확도 verifier is written later):
//   - State only what the (mock) log observed, and only that it is *recorded*
//     — never assert the underlying real-world action itself (a recorded
//     "도착 완료" button press is not proof of actual arrival).
//   - Absence of a log entry is phrased as "확인되지 않습니다" /
//     "기록이 없습니다" — never "하지 않았습니다" (that asserts a negative
//     fact the log cannot prove).
//   - No inferred duration, no inferred count, no inferred cause.
//   - No "그 뒤" / "이후" — don't imply a sequence or causal link the log
//     itself doesn't state.
//   - A "전달" (delivered, evidence-found) answer includes the KST minute-
//     level 24-hour clock time the event was recorded at (e.g. "14시 05분").
//   - `openedAt` (알림 열람) is `GuardianStatus` display-only information; it
//     is never cited as Q&A evidence, since the Q&A contract's evidence
//     scope for these three questions is the session event log, not the
//     guardian-link-open timestamp.
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
    wardName: '박순자',
    stage: 2,
    dongName: '신사동',
    // 10:33 KST (2026-08-21). Link opened, no [집이에요]/[밖이에요] response
    // yet — see the phrasing rule above for why this is shown as-is, not as
    // a safety signal.
    openedAt: '2026-08-21T01:33:00Z',
    respondedAt: null,
    lastResponse: 'none',
    // Always 'unknown' per contract — FE does not compute a safety status.
    safetyStatus: 'unknown',
  },
  recommendedQuestions: [
    {
      questionId: 'evacuation_progress',
      question: '대피 관련 행동 기록이 있나요?',
      answer: '14시 05분에 상황 선택 화면을 본 기록이 있습니다.',
    },
    {
      questionId: 'help_request',
      question: '도움 요청 기록이 있나요?',
      answer: '14시 07분에 도움 요청 버튼을 누른 기록이 있습니다.',
    },
    {
      questionId: 'arrival_status',
      question: '도착 완료 버튼 기록이 있나요?',
      answer: '14시 18분에 도착 완료 버튼을 누른 기록이 있습니다.',
    },
  ],
}
