// API contract types. The single source of truth is
// packages/contracts/openapi.yaml. This file mirrors its
// `components.schemas` — field names, enum values, nullability and
// required-ness follow the spec exactly. When the spec changes, this file
// MUST be updated in the same PR — do not edit one without the other.
//
// PRINCIPLE: this file mirrors the ENTIRE contract, not just the types
// consumed by current screens. Types like GuardianStatus, Stage,
// SessionResponseRequest, and SafetyStatus exist here because they exist in
// the spec — removing them would make it impossible to tell whether a type
// is absent from the contract or merely unused on screen. Every type in
// openapi.yaml has a 1:1 counterpart here regardless of current screen
// consumption. Individual "not consumed by any screen" annotations on
// single types are intentionally omitted — the principle stated here covers
// them all.
//
// A small number of frontend-only fields (clearly marked as such where they
// appear, e.g. Profile.consents and the ConsentFlags block at the bottom)
// extend the contract types for the /ops surrogate-registration screen. They
// are NOT in openapi.yaml and are kept in a separated, labelled section so
// the contract surface is never confused with the screen-only extension.
//
// Nullability rules applied (see openapi.yaml conventions):
//   - spec `type: [X, 'null']` AND listed in `required`  → `field: X | null`
//     (key always present, value may be null). NO `?`.
//   - spec `type: [X, 'null']` AND NOT in `required`      → `field?: X | null`
//     (key may be absent).
//   - spec optional (not required, no null union)         → `field?: X`.

// ---- Enums / literals -------------------------------------------------

export type Stage = 1 | 2 | 3

export type Housing = 'banjiha' | 'lowland' | 'normal'

export type Mobility = 'ok' | 'slow' | 'assisted'

export type Vision = 'ok' | 'low' | 'blind'

export type Hearing = 'ok' | 'bad'

// Contract-aligned UI language union. The spec lists ko, vi, zh, en. Korean
// and Vietnamese have full UI dictionaries today; zh and en fall back to
// Korean at the `t()` resolution layer — no partial translations are shipped.
export type Language = 'ko' | 'vi' | 'zh' | 'en'

export type RegisteredBy =
  | 'self'
  | 'guardian'
  | 'welfare_center'
  | 'employer'

export type ShelterBasis = 'coordinate' | 'dongCode'

// 8-point compass bearing. Spec allows the literal 'null' inside the enum
// union; in TS we model that as `Bearing | null` (key may carry null).
export type Bearing = 'N' | 'NE' | 'E' | 'SE' | 'S' | 'SW' | 'W' | 'NW'

export type RefusalReason = 'no_evidence' | 'out_of_scope' | 'unsafe'

// v0.7: DeviceRegisterRequest.role. Which recipient this device belongs to —
// `ward` gets the first-dispatch alert, `guardian` gets the closed-loop
// second dispatch only. No default; the contract requires the caller to
// state it explicitly (see openapi.yaml DeviceRegisterRequest.role).
export type DeviceRole = 'ward' | 'guardian'

// Ward survival signal. Values mirror the openapi.yaml GuardianLastResponse
// enum; how they are surfaced on screen is a separate UI decision, not a
// property of this type.
export type GuardianLastResponse = 'home' | 'outside' | 'none'

export type GuardianNotice = 'first' | 'followup' | 'none'

// v0.3: where the request location sits relative to the current hazard zone.
export type HazardMatch = 'inside' | 'outside' | 'unknown'

// Shelter-list availability state, mirroring the contract enum:
//   ok                   — the list is usable (real-time or cached with a
//                          timestamp). Items may be non-empty or empty.
//   all_excluded         — the server found candidates but excluded every
//                          one (침수 위험·운영 중단·가는 길 위험). The UI
//                          must render the AllExcludedNotice.
//   cache_only           — the upstream shelter API was unreachable; the
//                          server answered from a pre-cached list. dataAsOf
//                          carries the cache timestamp and the UI must
//                          disclose stale data.
//   upstream_unavailable — a normal 200 response (NOT an error). The server
//                          could not build a list at all; items is empty.
//                          The UI must show fallback guidance (고지대 이동,
//                          챗봇) — never a bare "주변에 대피소가 없습니다"
//                          that could make the user stay in place.
export type ShelterAvailability =
  | 'ok'
  | 'all_excluded'
  | 'cache_only'
  | 'upstream_unavailable'

// v0.3: provenance of the generated alert body — RAG-grounded vs. preapproved
// fallback.
export type MessageMode = 'grounded' | 'official_fallback'

// v0.3: GuardianStatus.safetyStatus. Mirrors the contract enum.
export type SafetyStatus = 'unknown'

// v0.3: reason categories for server-excluded shelters.
export type ExcludedReason = 'underground' | 'closed' | 'unreachable'

// v0.3: fixed error code enum (Error.code). Mirrors the enum list in
// packages/contracts/openapi.yaml Error.code 1:1. The contract file is the
// single source of truth — keep this list and the spec in lockstep.
export type ErrorCode =
  | 'SESSION_NOT_FOUND'
  | 'SESSION_EXPIRED'
  | 'INVALID_REQUEST'
  // POST /v1/session/{token}/events 전용(409) — 같은 Idempotency-Key를 다른
  // type/payload로 재사용했을 때.
  | 'IDEMPOTENCY_KEY_CONFLICT'
  | 'RATE_LIMITED'
  | 'INTERNAL'
  // generation 구간 전용 — 생성 백엔드/벡터 DB 장애(503).
  | 'UPSTREAM_UNAVAILABLE'

// ---- Composite schemas ------------------------------------------------


export interface Guardian {
  name: string
  phone: string
  relation: string
}

// "care" is a free-form Korean string (e.g. 영유아, 와상 가족) or null.
// Required + nullable per spec → key always present, value may be null.
export type CareSubject = string

export interface Profile {
  userId: string
  name: string
  // 행정동 코드 10자리. 발송 대상 매칭 키.
  dongCode: string
  dongName: string
  // 법정동 코드 10자리. optional + nullable — coord2RegionCode 실측에서만 채워짐.
  bjdCode?: string | null
  housing: Housing
  mobility: Mobility
  stairsOk: boolean
  easyText: boolean
  vision: Vision
  hearing: Hearing
  language: Language
  livesAlone: boolean
  // Required + nullable. null = "no care subject" (a definite fact, not unknown).
  care: CareSubject | null
  // Required + nullable. null이면 프론트는 [보호자 호출] 버튼을 렌더하지 않는다.
  guardian: Guardian | null
  registeredBy: RegisteredBy
  // Frontend-only — NOT in the API contract. Three separate consent flags
  // captured on the /ops surrogate-registration screen (personal / sensitive /
  // location). Optional so every existing Profile literal (mock personas,
  // backend-shaped responses) stays valid without touching them; the /ops
  // screen is the only producer. See ConsentFlags below for the per-item
  // meaning. When the contract grows a registration-write endpoint that
  // carries consent state, this field is promoted into the spec.
  consents?: ConsentFlags
  // Frontend-only — NOT in the API contract. true 이면 이 프로필이 실제
  // 등록 문서에서 만들어진 세션임을 뜻한다. 데모 페르소나(mock personas)
  // 는 이 필드를 설정하지 않으므로 undefined/falsy 이고, 기존 화면 동작이
  // 그대로 유지된다. 등록 세션에서는 이름·행정동만 진짜이고 나머지 프로필
  // 항목은 특기사항이 없다는 뜻의 중립 기본값이므로, 화면은 이 마커가
  // true 일 때 그 사실을 담담하게 한 줄로 드러낸다.
  fromRegistration?: boolean
}

export interface Source {
  title: string
  // 원문 인용. 생성 문장이 아니라 회수된 원문 그대로.
  quote: string
  url?: string | null
}

export interface AlertMessage {
  title: string
  // Pre-rendered personalized body. The generator already produced this —
  // the frontend renders it verbatim (no template slot mapping).
  body: string
  // v0.3: required. Downstream scoring code assumes the key is present;
  // empty array is allowed (but `messageMode: 'grounded'` with empty sources
  // is a contract violation — see openapi.yaml AlertMessage.messageMode).
  sources: Source[]
  // v0.3: required. Source kind of the body — RAG-grounded vs. preapproved
  // fallback.
  messageMode: MessageMode
}

export interface SessionResponse {
  // v0.3: top-level `userId` removed — `profile.userId` is the single source.
  stage: Stage
  issuedAt?: string
  message: AlertMessage
  profile: Profile
}

// v0.9 (ADR-0016): "이 요청자 기준" 개인 적합성 주의. 시설 속성
// (isUnderground/hasStairs)과는 다른 축 — 같은 대피소도 보는 사람에 따라
// 값이 달라진다. 제외가 아니라 주의다: 주의가 붙어도 대피소는 목록에
// 남고 정렬 순서만 뒤로 간다(openapi.yaml Shelter.cautions 설명 참고).
export type ShelterCaution = 'stairs' | 'over_time'

export interface Shelter {
  id: string
  name: string
  address: string
  lat?: number
  lng?: number
  // 직선거리(m).
  distanceM: number
  // 방향. 지도를 못 쓰는 상황(전맹·지도 실패)의 텍스트 폴백.
  // Optional + nullable per spec (openapi.yaml Shelter.bearing is NOT in the
  // `required` list and uses `type: [string, 'null']`). key may be absent.
  bearing?: Bearing | null
  isUnderground: boolean
  hasStairs: boolean
  capacity?: number | null
  // v0.9 (ADR-0016): required, default []. 빈 배열 = 이 요청자에게 주의
  // 없음. 키는 항상 존재한다(openapi.yaml Shelter.required에 포함).
  cautions: ShelterCaution[]
}

// v0.3: server-side exclusion aggregate (ShelterList.excluded items).
export interface ShelterExclusion {
  reason: ExcludedReason
  count: number
}

export interface ShelterList {
  hazardMatch: HazardMatch
  // Required. Availability of the shelter list. See ShelterAvailability for
  // the full semantics of each value. The freshness axis (real-time vs
  // cached) lives here: cache_only and upstream_unavailable carry cache/outage
  // state that was previously a separate field.
  availability: ShelterAvailability
  basis: ShelterBasis
  // Required + nullable. null = real-time data; a timestamp string = cached
  // snapshot (pair with availability 'cache_only' or 'upstream_unavailable').
  // The UI must disclose stale data when dataAsOf is non-null.
  dataAsOf: string | null
  // Required. Server-excluded facilities grouped by reason.
  excluded: ShelterExclusion[]
  items: Shelter[]
}

// v0.3: POST /v1/shelters/search request body. Coordinates move into the
// body (so they don't linger in URLs/logs) and `sessionToken` lets the
// server look up the profile internally — health/disability fields are
// NEVER sent back from the client.
export interface ShelterSearchRequest {
  sessionToken: string
  dongCode: string
  lat?: number
  lng?: number
  limit?: number
}

// v0.3: POST /v1/session/{token}/response request body.
export interface SessionResponseRequest {
  response: 'home' | 'outside'
}

// ---- v0.5/v0.10 session-log (user action events) -----------------------
//
// POST /v1/session/{token}/events (operationId postSessionEvent). Only the
// user-action side of SessionEvent is modeled here — the system-event 5
// (alert_dispatched · push_accepted · followup_due · followup_unreachable ·
// guardian_notified) are written by Backend/the push system only and are
// never posted from the browser (openapi.yaml UserActionEventCreate).

// Server-recorded UTC receipt time (RFC3339, `Z` suffix). The client never
// sends this — the server stamps it on receipt (openapi.yaml EventTimestamp).
export type EventTimestamp = string

export type UserActionEventType =
  | 'situation_check_selected'
  | 'profile_review_started'
  | 'profile_review_completed'
  | 'profile_review_skipped'
  | 'choice_screen_viewed'
  | 'help_request_selected'
  | 'direct_evacuation_selected'
  | 'evacuation_guidance_viewed'
  | 'route_guidance_started'
  | 'next_guidance_requested'
  | 'emergency_call_119_selected'
  | 'arrival_confirmed_by_user'

// No fields allowed — coordinates/profile/contact info are deliberately kept
// out (openapi.yaml EmptyEventPayload, additionalProperties: false).
export type EmptyEventPayload = Record<string, never>

export interface GuidanceStepPayload {
  // 1-based step index the user asked to see next. Not a route position.
  guidanceStep: number
}

// Request DTO for postSessionEvent. Mirrors the spec's if/then/else: only
// `next_guidance_requested` carries GuidanceStepPayload, the other 11 types
// carry EmptyEventPayload.
export type UserActionEventCreate =
  | {
      type: Exclude<UserActionEventType, 'next_guidance_requested'>
      payload: EmptyEventPayload
    }
  | { type: 'next_guidance_requested'; payload: GuidanceStepPayload }

// Response of a successful postSessionEvent — the same event with the
// server-assigned `at`. System events are never returned here.
export type RecordedUserActionEvent =
  | {
      type: Exclude<UserActionEventType, 'next_guidance_requested'>
      at: EventTimestamp
      payload: EmptyEventPayload
    }
  | {
      type: 'next_guidance_requested'
      at: EventTimestamp
      payload: GuidanceStepPayload
    }

export interface ChatRequest {
  token: string
  question: string
  locale?: Language
}

export interface ChatResponse {
  // null when the guardrail suppressed the answer (refusalReason then set).
  // Required + nullable — null is a definitive "no answer generated" signal.
  answer: string | null
  sources: Source[]
  refusalReason?: RefusalReason | null
}

// v0.3: registration token (long-lived, 1-person) replaces the old `token`
// field. Resolves the circular dependency (FCM registration previously
// required a session token, which only exists at dispatch time).
export interface DeviceRegisterRequest {
  registrationToken: string
  fcmToken: string
  // v0.7: required. No default — see DeviceRole above for why a fallback
  // would silently misroute first-dispatch alerts to a guardian device.
  role: DeviceRole
  userAgent?: string | null
}

// v0.7: body of POST/DELETE /v1/guardian/{token}/device. Neither `role` nor
// `registrationToken` is carried — the path's guardian token already answers
// both (role is fixed to `guardian` by the path, the target ward is resolved
// server-side from that token).
export interface GuardianDeviceRegisterRequest {
  fcmToken: string
  userAgent?: string | null
}

// v0.3: GET /v1/registration/{registrationToken} response. Minimum
// identifying info for the surrogate-registration confirm screen —
// disability/health fields are deliberately NOT included.
export interface RegistrationTarget {
  wardName: string
  dongName: string
  registeredBy: RegisteredBy
}

export interface Ack {
  ok: boolean
}

export interface GuardianStatus {
  wardName: string
  wardPhone?: string | null
  stage: Stage
  dongName?: string
  // v0.3: presence split into two timestamps (was a single merged field).
  // When the ward opened the link (session GET success). Does NOT change on
  // the response POST. Required + nullable — null = not opened yet.
  openedAt: string | null
  // When the ward submitted a survival response. Updated together with
  // lastResponse by the response POST. Required + nullable.
  respondedAt: string | null
  lastResponse: GuardianLastResponse
  // Which guardian notice was most recently accepted for this disaster.
  // Required; `none` means neither the first nor follow-up notice was sent.
  lastNotice: GuardianNotice
  // v0.3: required. Currently always `unknown` — no inference is made from
  // opens/taps.
  safetyStatus: SafetyStatus
  // v0.7: required. Whether this WARD has one or more `role: guardian`
  // devices registered server-side — the unit is the ward, not a browser.
  // true does NOT mean "the browser currently viewing this page is
  // subscribed"; a different guardian device can make this true while the
  // current browser has never subscribed (openapi.yaml GuardianStatus.pushEnabled).
  pushEnabled: boolean
  acknowledgedByGuardian?: boolean
}

// ---- v0.6/v0.10 guardian Q&A (session-log grounded, not corpus RAG) ----
//
// POST /v1/guardian/{token}/ask (operationId postGuardianAsk). Answers are
// generated from that session's SessionEvent log only — no vector search,
// no free-text question. See openapi.yaml GuardianQuestionId for the full
// per-question evidence-scope table.

// The three recommended questions. This is the CLOSED set — no free-text
// question type exists in the contract, and none is added here.
export type GuardianQuestionId =
  | 'evacuation_progress'
  | 'help_request'
  | 'arrival_status'

export interface GuardianAskRequest {
  questionId: GuardianQuestionId
  // Fixed to 'ko' for this segment — see openapi.yaml GuardianAskRequest for
  // why this is narrower than the Language union used elsewhere.
  locale?: 'ko'
}

// Union of all 18 SessionEvent discriminator keys (12 user actions + 6
// system events) — the citable-evidence universe. Mirrors
// openapi.yaml GuardianEvidenceType 1:1; kept in lockstep with
// UserActionEventType if that list ever changes.
export type GuardianEvidenceType =
  | UserActionEventType
  | 'alert_dispatched'
  | 'push_accepted'
  | 'guardian_informed'
  | 'followup_due'
  | 'followup_unreachable'
  | 'guardian_notified'

// evacuation_progress may cite any of the 12 user-action events.
export type EvacuationProgressEvidenceType = UserActionEventType

// help_request / arrival_status each narrow to their own small set.
export type HelpRequestEvidenceType =
  | 'help_request_selected'
  | 'emergency_call_119_selected'

export type ArrivalStatusEvidenceType = 'arrival_confirmed_by_user'

// One evidence entry backing one answer sentence. `present: false` means
// "not found in this session's log" — NOT "did not happen" (see
// openapi.yaml GuardianEvidence). `T` narrows `type` per question.
export interface GuardianEvidenceConfirmed<
  T extends GuardianEvidenceType = GuardianEvidenceType,
> {
  type: T
  present: true
  at: string
}

export interface GuardianEvidenceNotFound<
  T extends GuardianEvidenceType = GuardianEvidenceType,
> {
  type: T
  present: false
  at?: null
}

export type GuardianEvidence<
  T extends GuardianEvidenceType = GuardianEvidenceType,
> = GuardianEvidenceConfirmed<T> | GuardianEvidenceNotFound<T>

export type EvacuationProgressEvidence =
  GuardianEvidence<EvacuationProgressEvidenceType>
export type HelpRequestEvidence = GuardianEvidence<HelpRequestEvidenceType>
export type ArrivalStatusEvidence = GuardianEvidence<ArrivalStatusEvidenceType>

// Answer body text. "선택완료 확인되지 않습니다" style — reports only what
// the log shows, never asserts safety (openapi.yaml GuardianAnswerBody).
export type GuardianAnswerBody = string

export type NonEmptyArray<T> = [T, ...T[]]

export interface GuardianAnswerEvacuationProgress {
  questionId: 'evacuation_progress'
  answer: GuardianAnswerBody
  sources: NonEmptyArray<EvacuationProgressEvidence>
  refusalReason: null
}

export interface GuardianAnswerHelpRequest {
  questionId: 'help_request'
  answer: GuardianAnswerBody
  sources: NonEmptyArray<HelpRequestEvidence>
  refusalReason: null
}

export interface GuardianAnswerArrivalStatus {
  questionId: 'arrival_status'
  answer: GuardianAnswerBody
  sources: NonEmptyArray<ArrivalStatusEvidence>
  refusalReason: null
}

// The only refusal shape. `answer: null` + `sources: []` is a definitive
// "nothing to cite" signal, not an error (openapi.yaml GuardianAnswerRefused).
export interface GuardianAnswerRefused {
  questionId: GuardianQuestionId
  answer: null
  sources: []
  refusalReason: 'no_evidence'
}

// Delivered-or-refused, nothing in between — enforced by this union, mirroring
// the spec's oneOf (openapi.yaml GuardianAnswer).
export type GuardianAnswer =
  | GuardianAnswerEvacuationProgress
  | GuardianAnswerHelpRequest
  | GuardianAnswerArrivalStatus
  | GuardianAnswerRefused

// v0.3: Error.code is now a fixed enum (was free-form string).
export interface Error {
  code: ErrorCode
  message: string
}

// ---- API entrypoint signatures ----------------------------------------
//
// v0.10 endpoint set (see packages/contracts/openapi.yaml paths). Method
// names mirror the spec's `operationId`. The contract file is the single
// source of truth — keep these signatures and the spec in lockstep.
//   GET    /v1/session/{token}                       → getSession
//   POST   /v1/session/{token}/response              → postSessionResponse
//   POST   /v1/session/{token}/events                → postSessionEvent
//   GET    /v1/registration/{registrationToken}      → getRegistrationTarget
//   POST   /v1/shelters/search                       → searchShelters
//   POST   /v1/chat                                  → postChat
//   POST   /v1/devices                               → registerDevice
//   DELETE /v1/devices                               → unregisterDevice
//   GET    /v1/guardian/{token}                      → getGuardianStatus
//   POST   /v1/guardian/{token}/acknowledge          → postGuardianAcknowledge
//   POST   /v1/guardian/{token}/device                → registerGuardianDevice
//   DELETE /v1/guardian/{token}/device                → unregisterGuardianDevice
//   POST   /v1/guardian/{token}/ask                   → postGuardianAsk
// (`POST /v1/generate` / `POST /v1/answer` / `POST /v1/guardian/answer`
// (operationIds `postGenerate` / `postAnswer` / `postGuardianAnswer`) and
// `GET /internal/sessions/{token}/events` (`getSessionEvents`) are
// backend↔ai-engine / backend-internal only and are intentionally not on
// the browser-facing client.)

export interface ApiClient {
  getSession(token: string): Promise<SessionResponse>
  postSessionResponse(
    token: string,
    response: 'home' | 'outside',
  ): Promise<Ack>
  // Idempotency-Key is a required header per the contract (16-128 chars);
  // callers pass it explicitly rather than have the client invent one, since
  // only the caller knows whether this is a fresh user action or a retry of
  // the same one (openapi.yaml POST /v1/session/{token}/events).
  postSessionEvent(
    token: string,
    event: UserActionEventCreate,
    idempotencyKey: string,
  ): Promise<RecordedUserActionEvent>
  getRegistrationTarget(registrationToken: string): Promise<RegistrationTarget>
  searchShelters(req: ShelterSearchRequest): Promise<ShelterList>
  postChat(req: ChatRequest): Promise<ChatResponse>
  registerDevice(req: DeviceRegisterRequest): Promise<Ack>
  unregisterDevice(
    registrationToken: string,
    fcmToken: string,
  ): Promise<Ack>
  getGuardianStatus(token: string): Promise<GuardianStatus>
  postGuardianAcknowledge(token: string): Promise<Ack>
  // Renewal path for a guardian's push subscription — see
  // GuardianDeviceRegisterRequest for why this takes no role/registrationToken.
  registerGuardianDevice(
    token: string,
    req: GuardianDeviceRegisterRequest,
  ): Promise<Ack>
  unregisterGuardianDevice(
    token: string,
    req: GuardianDeviceRegisterRequest,
  ): Promise<Ack>
  // Closed-set recommended question only — no free-text question path exists.
  postGuardianAsk(token: string, req: GuardianAskRequest): Promise<GuardianAnswer>
}

// ---- Frontend-only consent flags (NOT in the API contract) --------------
//
// The three consent items collected on the /ops surrogate-registration screen
// (personal info / sensitive info / location info) have no home in
// packages/contracts/openapi.yaml yet. They are a frontend-only concern at
// this stage: the operator screen records which consents were given so the
// status table can show them, but no endpoint carries these fields today.
//
// When the contract grows a registration-write endpoint that carries consent
// state, these flags move into the spec and get re-translated here alongside
// the rest of the schemas — not before. Until then they stay in this clearly
// separated block so it is obvious they are not part of the contract surface.
//
// `keyof ConsentFlags` is also the source of truth for the per-item identity
// used by the /ops UI (checkbox ids, status-table rows). Adding a consent
// item means adding a key here AND a matching entry in the Ops.tsx wording
// constant — the two are kept in lockstep on purpose.

export type ConsentKey = 'personal' | 'sensitive' | 'location'

export interface ConsentFlags {
  // 개인정보(성함·연락처·사는 곳) 수집 동의. 필수 — 미동의 시 등록 불가.
  personal: boolean
  // 민감정보(장애·건강 관련) 수집 동의. 선택 — 미동의 시 맞춤 안내가 제한됨.
  sensitive: boolean
  // 위치정보(알림 열람 시점 1회, 미저장) 이용 동의. 선택 — 미동의 시 등록
  // 행정동 기준으로만 안내됨.
  location: boolean
}
