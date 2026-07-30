// Mock adapter. Returns fixture data with an artificial 200–600ms delay
// so loading states are actually visible in the UI. The delay is the only
// "behavior" beyond data return; no real I/O happens.
//
// Personas and fixtures exercise several branches end-to-end:
//   - messageMode: p001 grounded (with sources), p004 official_fallback
//     (preapproved template, empty sources).
//   - ShelterList.availability: 'ok' for the default flow; cache_only (p007,
//     stale snapshot with dataAsOf); upstream_unavailable (p005, empty list
//     with fallback guidance); all_excluded (p011, every shelter excluded).
//   - hazardMatch: inside (default), outside (p003), unknown (p008).
//
// The freshness/outage axis is carried by availability + dataAsOf:
//   - availability 'cache_only' + non-null dataAsOf = stale snapshot.
//   - availability 'upstream_unavailable' + non-null dataAsOf = upstream
//     outage, items empty, fallback guidance must stay.

import type {
  Ack,
  ApiClient,
  ChatRequest,
  ChatResponse,
  DeviceRegisterRequest,
  GuardianStatus,
  Language,
  Profile,
  RegistrationTarget,
  SessionResponse,
  ShelterList,
  ShelterSearchRequest,
} from './types'
import { PROFILES } from '../mocks/profiles'
import {
  SHELTERS_ALL_EXCLUDED_VERTICAL,
  SHELTERS_COORDINATE_INSIDE,
  SHELTERS_DONG_CACHE,
  SHELTERS_DONG_INSIDE,
  SHELTERS_DONG_OUTSIDE,
  SHELTERS_DONG_UNKNOWN,
  SHELTERS_UPSTREAM_UNAVAILABLE,
} from '../mocks/shelters'
import { CHAT_RULES } from '../mocks/chatReplies'
import { ADMIN_DONG } from '../mocks/adminDong'
import {
  isStoreEnabled,
  getRegistration,
} from './firestore'

// Reference coordinates for the demo area (관악구 서원동/신림동). These
// mirror the lat/lng embedded in the shelter fixtures (`../mocks/shelters`)
// and live here so that:
//   1. The map demo has a documented fallback center when no shelter has
//      coordinates (used by ShelterMap's "no coord" branch indirectly via
//      the search result).
//   2. Tests have a single canonical demo coord pair to assert against,
//      instead of fishing it out of a fixture.
// Values are illustrative, not surveyed — see shelters.ts for the same
// disclaimer.
export const DEMO_AREA_COORDS: ReadonlyArray<{ lat: number; lng: number }> = [
  { lat: 37.4827, lng: 126.9295 }, // [데모] 서원복지회관 근처
  { lat: 37.4791, lng: 126.9403 }, // [데모] 신림체육관 근처
]

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// 200–600ms inclusive pseudo-random delay.
function randomDelay(): Promise<void> {
  const ms = 200 + Math.floor(Math.random() * 401)
  return delay(ms)
}

// Whitespace and punctuation split for tokenizing a free-text question.
// Korean and Vietnamese both segment on spaces; punctuation is stripped so a
// trailing comma/question mark does not fuse into a token.
const QUESTION_SPLIT = /[\s.,?!~'"()`]+/u

// Korean subject/topic/object particles that may attach to a noun stem when
// the user writes without spaces (e.g. "물이", "대피소를"). Listed for
// documentation; the matcher accepts any all-Hangul remainder after a stem,
// which is a superset of these particles and also covers verb endings such
// as "침수됐어요" (stem 침수 + 됐어요).
const KO_PARTICLES = new Set([
  '이', '가', '은', '는', '을', '를', '도', '의', '에', '에서', '으로', '로',
  '와', '과', '한테', '께', '보다', '처럼', '이다', '요', '어요', '네요',
])

// True when every character of `s` is a modern Hangul syllable
// (가..힣). Used to accept a Korean stem followed by particles or verb
// endings (침수됐어요) while rejecting a stem glued to Latin/digits, which
// would indicate a different lexical unit (e.g. "yoga" against keyword "ga").
function isAllHangul(s: string): boolean {
  for (const ch of s) {
    const code = ch.codePointAt(0)
    if (code === undefined || code < 0xac00 || code > 0xd7a3) return false
  }
  return s.length > 0
}

// True if `token` matches `keyword` under the word-aware rule:
//   - exact equality, OR
//   - the keyword is a STEM PREFIX of the token (token starts with the
//     keyword) and the trailing characters are all Hangul (Korean
//     particles/verb endings), so inflection does not hide a real hit.
//
// Two deliberate non-rules:
//   - We never match the keyword as a SUFFIX or middle substring of a longer
//     token. That is what stops "반려동물이" from matching "물이" (물이 is a
//     suffix there) and "yoga" from matching "ga" (ga is a suffix).
//   - We never use a raw substring test even for 2+ char keywords. The
//     collision space (ga inside yoga, ap inside map, ...) is not worth the
//     tiny gain in recall, and any keyword that genuinely needs substring
//     matching should be expressed as a more specific entry instead.
function tokenMatchesKeyword(token: string, keyword: string): boolean {
  if (token === keyword) return true
  if (keyword.length === 0) return false
  if (token.startsWith(keyword)) {
    const rest = token.slice(keyword.length)
    if (rest.length === 0) return true
    if (isAllHangul(rest)) return true
    if (KO_PARTICLES.has(rest)) return true
  }
  return false
}

// Word-aware rule matcher. Multi-word keywords (e.g. Vietnamese "tầng hầm",
// "nơi trú ẩn") are matched against the whole question as a phrase (the
// internal space is part of the lexical unit, and the surrounding tokens
// cannot merge into it); single-word keywords go through tokenMatchesKeyword
// so a stem cannot fire from inside a longer, unrelated word.
function questionMatchesRule(question: string, keywords: string[]): boolean {
  const tokens = question.split(QUESTION_SPLIT).filter((t) => t.length > 0)
  for (const kw of keywords) {
    const k = kw.toLowerCase()
    if (k.includes(' ')) {
      if (question.includes(k)) return true
      continue
    }
    for (const tok of tokens) {
      if (tokenMatchesKeyword(tok.toLowerCase(), k)) return true
    }
  }
  return false
}

// v0.3: AlertMessage now requires `sources` (non-optional) and `messageMode`.
// Personas with `messageMode: 'grounded'` carry a retrieved source; the
// fallback persona ships an empty sources array with `official_fallback`.
//
// Vietnamese mock copy: vi-language personas (p002/p009/p010) receive a
// Vietnamese alert title + body + source quote. The messageMode and stage
// are identical to the Korean path — only the rendered language differs.
// The Vietnamese text below is a hand-written demo adaptation, NOT the
// verbatim output of the real generator — it exists so the Vietnamese
// response path runs end-to-end without a live backend.
function buildSession(profileId: string): SessionResponse | null {
  const profile = PROFILES[profileId]
  if (profile === undefined) {
    return null
  }
  const isFallback = profileId === 'p004'
  const isVi = profile.language === 'vi'
  return {
    issuedAt: new Date().toISOString(),
    stage: 2,
    profile,
    message: isVi
      ? {
          title: '[SAVERS] Cảnh báo mưa lớn — Seowon-dong',
          body: `Đã phát hành cảnh báo mưa lớn tại nơi bạn đăng ký (Seowon-dong). ${profile.name}, hãy mang giày và chuẩn bị di chuyển ngay.`,
          sources: isFallback
            ? []
            : [
                {
                  title: '[demo] Hướng dẫn ứng phó — Bộ Hành chính và An toàn',
                  quote:
                    'Người dân ở khu vực có nguy cơ ngập nước (tầng hầm, vùng trũng) phải lập tức di chuyển lên tầng trên hoặc đến tòa nhà cao gần nhất.',
                },
              ],
          messageMode: isFallback ? 'official_fallback' : 'grounded',
        }
      : {
          title: '[세이버스] 서원동 호우경보',
          body: `등록하신 자택(서원동)에 호우경보가 발령됐습니다. ${profile.name}님, 지금 신발을 신고 이동 준비를 하세요.`,
          sources: isFallback
            ? []
            : [
                {
                  title: '[demo] 국민행동요령 — 호우 시 대피 권고',
                  quote:
                    '침수 위험 지역(반지하·저지대) 거주자는 즉시 위층 또는 인근 높은 건물로 대피한다.',
                },
              ],
          messageMode: isFallback ? 'official_fallback' : 'grounded',
        },
  }
}

// 행정동 이름으로 코드를 찾는다. 데모 범위에서 검증된 동만 목록에 있으므로,
// 등록 문서의 dongName 이 목록에 없으면 코드를 알 수 없다 — 지어내지 않고
// 빈 문자열을 돌려준다. 빈 dongCode 는 아래쪽(Landing/ShelterGuide)에서
// 「대피소를 안내하지 못함」 경로로 이어진다.
function lookupDongCodeByName(dongName: string): string {
  for (const d of ADMIN_DONG) {
    if (d.name === dongName) return d.code
  }
  return ''
}

// 등록 문서로 세션을 만든다. 데모 페르소나가 아닌, 실제 등록으로 생긴
// userId 가 알림을 탭하고 /a?t=<userId> 로 들어온 경우에 쓰인다.
//
// 저장소에 실제로 있는 항목(STORED_FIELDS)은 userId · name · dongName ·
// phone · sendState · lastSentAt · isRead · hasToken · deviceToken 뿐이다.
// 그 밖의 프로필 항목(주거 형태·거동·계단·시력·청력·돌봄·보호자 등)은
// 등록 화면에서 아예 받지 않고 저장소에도 적지 않는다. 그래서 이 세션의
// 프로필에서 그 항목들은 중립 기본값이다 — 「특기사항 없음」의 의미이지
// 「확인했더니 괜찮더라」가 아니다.
//
// ⚠️ 데모 페르소나의 건강·장애 값을 복사해 오지 않는다. 그건 그 사람 정보
// 가 아니다. 등록한 적 없는 취약 특성을 화면이 단정하면 잘못된 안내가
// 나간다.
//
// 행정동을 못 찾으면(조회 실패) dongCode 를 빈 문자열로 둔다 — 지어내지
// 않는다. 그러면 ShelterGuide 가 「대피소를 안내하지 못함」 경로로 간다.
async function buildSessionFromRegistration(
  userId: string,
): Promise<SessionResponse | null> {
  // 저장소가 꺼져 있으면 등록 문서를 읽을 수 없다 — 기존 동작(세션 오류)을
  // 유지한다.
  if (!isStoreEnabled()) return null
  const rec = await getRegistration(userId)
  if (rec === null) return null
  const dongCode = lookupDongCodeByName(rec.dongName)
  // 프로필 항목 중 저장된 값은 name · dongName 뿐이다. dongCode 는 dongName
  // 으로 조회해 채운다. 나머지는 특기사항 없음에 해당하는 중립 기본값이다.
  const profile: Profile = {
    userId: rec.userId,
    name: rec.name,
    dongName: rec.dongName,
    dongCode,
    // 주거·거동·시력·청력·돌봄·보호자는 저장하지 않는다 — 중립 기본값.
    housing: 'normal',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'ko',
    livesAlone: true,
    care: null,
    guardian: null,
    registeredBy: 'guardian',
    // 이 프로필이 등록 문서에서 만들어졌음을 표시. 이름·행정동만 진짜이고
    // 나머지는 특기사항 없음의 중립 기본값이라는 사실을 화면이 드러내게 한다.
    fromRegistration: true,
  }
  const isVi = profile.language === 'vi'
  return {
    issuedAt: new Date().toISOString(),
    stage: 2,
    profile,
    message: isVi
      ? {
          title: `[SAVERS] Cảnh báo mưa lớn — ${rec.dongName}`,
          body: `Đã phát hành cảnh báo mưa lớn tại nơi bạn đăng ký (${rec.dongName}). ${rec.name}, hãy kiểm tra hướng dẫn.`,
          sources: [],
          messageMode: 'official_fallback',
        }
      : {
          title: `[세이버스] ${rec.dongName} 호우경보`,
          body: `${rec.dongName}에 호우경보가 발령됐습니다. ${rec.name}님, 안내를 확인해 주세요.`,
          sources: [],
          messageMode: 'official_fallback',
        },
  }
}

// Pick the ShelterList fixture for a given request. Branch logic mirrors
// the fixture axis labels (hazardMatch / availability).
function pickShelterList(req: ShelterSearchRequest): ShelterList {
  const hasCoordinate = req.lat !== undefined && req.lng !== undefined
  const sessionToken = req.sessionToken

  // p005 — upstream API outage demo. availability is upstream_unavailable,
  // items is empty, but the fallback guidance stays (the network may be
  // down, but the last guidance must still reach the user).
  if (sessionToken === 'p005') {
    return SHELTERS_UPSTREAM_UNAVAILABLE
  }
  // p007 — cached snapshot (real-time API down, served from cache).
  // availability is cache_only; dataAsOf is non-null so the UI discloses
  // stale data.
  if (sessionToken === 'p007') {
    return SHELTERS_DONG_CACHE
  }
  // p011 — all_excluded demo. Every shelter was excluded by the server.
  // The coord-vs-dong distinction is irrelevant here (items is empty either
  // way), so this check runs before the hasCoordinate branch below.
  if (sessionToken === 'p011') {
    return SHELTERS_ALL_EXCLUDED_VERTICAL
  }
  if (hasCoordinate) {
    return SHELTERS_COORDINATE_INSIDE
  }
  // p003 — outside the hazard zone (wording differs).
  if (sessionToken === 'p003') {
    return SHELTERS_DONG_OUTSIDE
  }
  // p008 — unknown hazard zone (kept ready, not collapsed to "outside").
  if (sessionToken === 'p008') {
    return SHELTERS_DONG_UNKNOWN
  }
  return SHELTERS_DONG_INSIDE
}

// Detect whether a canned flood answer instructs the resident to go upstairs.
// The flood rule in CHAT_RULES tells basement residents to move to an upper
// floor ("위층으로 대피하세요" / "di chuyển lên tầng trên"). That instruction
// is correct for someone who CAN use stairs but is unsafe for someone
// registered as stairsOk: false — the shelter list already excludes stairs
// facilities for them, so the chat answer must not contradict that.
function isVerticalEvacuationAnswer(
  answer: string | null,
  locale: Language,
): boolean {
  if (answer === null) return false
  if (locale === 'vi') {
    return /lên tầng trên|di chuyển lên tầng/i.test(answer)
  }
  return /위층으로|위층|높은 층으로|높은 건물로/i.test(answer)
}

export const mockAdapter: ApiClient = {
  async getSession(token: string): Promise<SessionResponse> {
    await randomDelay()
    const session = buildSession(token)
    if (session !== null) {
      return session
    }
    // 데모 페르소나에 없는 토큰. 저장소가 켜져 있으면 등록 문서를 읽어
    // 그 사람 세션을 만든다. 저장소가 꺼져 있거나 문서가 없으면 null 이
    // 돌아오며, 아래 기존 에러 경로로 간다 — 이 모드에서는 데모 페르소나
    // 토큰만 의미가 있으므로 그대로 둔다.
    const regSession = await buildSessionFromRegistration(token)
    if (regSession !== null) {
      return regSession
    }
    throw new Error(`unknown session token: ${token}`)
  },

  async postSessionResponse(
    token: string,
    response: 'home' | 'outside',
  ): Promise<Ack> {
    await randomDelay()
    void token
    void response
    return { ok: true }
  },

  async getRegistrationTarget(
    registrationToken: string,
  ): Promise<RegistrationTarget> {
    await randomDelay()
    // Registration tokens map 1:1 to profiles for the demo. The contract
    // returns ONLY minimum identifying info — no health/disability fields.
    const profile = PROFILES[registrationToken]
    if (profile === undefined) {
      throw new Error(`unknown registration token: ${registrationToken}`)
    }
    return {
      wardName: profile.name,
      dongName: profile.dongName,
      registeredBy: profile.registeredBy,
    }
  },

  async searchShelters(req: ShelterSearchRequest): Promise<ShelterList> {
    await randomDelay()
    void req.limit
    return pickShelterList(req)
  },

  async postChat(req: ChatRequest): Promise<ChatResponse> {
    await randomDelay()
    // Locale selects the reply language. Each rule carries at least a Korean
    // reply; Vietnamese is present for the two demo languages that have UI
    // translations today. zh/en (and any other language the contract may add)
    // fall back to Korean so every locale gets a concrete answer.
    const locale: Language = req.locale === 'vi' ? 'vi' : 'ko'
    // The session token identifies the profile. The chat layer must consult
    // the profile so it does not give a stairs-unable resident an instruction
    // to go upstairs — the shelter list already treats that person as
    // stairs-unable, and the chat answer must stay consistent with that.
    const profile = PROFILES[req.token]
    // Unknown / unresolvable session token. We must NOT return a rule answer
    // here: there is no profile behind the question, so no evidence-grounded
    // instruction can be produced for this person. Refusing is the honest
    // product outcome — the resident is told there is no confirmed guidance
    // rather than being handed a canned evacuation instruction that does not
    // belong to them.
    if (profile === undefined) {
      return locale === 'vi'
        ? { answer: null, refusalReason: 'no_evidence', sources: [] }
        : { answer: null, refusalReason: 'no_evidence', sources: [] }
    }
    // The question is matched word-aware (see questionMatchesRule): a token
    // must equal a keyword or have it as a stem with only particles left
    // over. This keeps a single syllable from firing inside an unrelated
    // longer word (반려동물 vs 물, 불안 vs 불) without losing legitimate
    // phrasings where the syllable stands on its own.
    const q = req.question.toLowerCase()
    for (const rule of CHAT_RULES) {
      if (rule.keywords.length === 0) {
        continue
      }
      if (questionMatchesRule(q, rule.keywords)) {
        const reply = rule.reply[locale] ?? rule.reply.ko
        // A resident registered as unable to use stairs must not be told to
        // go upstairs (the flood rule's answer says "위층으로 대피하세요").
        // When the profile says stairsOk: false, the canned vertical-
        // evacuation instruction is unsafe for THIS person, so we refuse
        // with no_evidence rather than deliver an answer we cannot stand
        // behind. Refusal is a legitimate product outcome here — the real
        // generator would condition on the profile the same way.
        if (
          profile !== undefined &&
          profile.stairsOk === false &&
          isVerticalEvacuationAnswer(reply.answer, locale)
        ) {
          break
        }
        return reply
      }
    }
    // Fall back to the no-evidence terminal rule.
    const fallback = CHAT_RULES[CHAT_RULES.length - 1]
    return fallback.reply[locale] ?? fallback.reply.ko
  },

  async registerDevice(req: DeviceRegisterRequest): Promise<Ack> {
    await randomDelay()
    void req
    return { ok: true }
  },

  async unregisterDevice(
    registrationToken: string,
    fcmToken: string,
  ): Promise<Ack> {
    await randomDelay()
    void registrationToken
    void fcmToken
    return { ok: true }
  },

  async getGuardianStatus(token: string): Promise<GuardianStatus> {
    await randomDelay()
    const profile = PROFILES[token]
    if (profile === undefined) {
      throw new Error(`unknown guardian token: ${token}`)
    }
    return {
      wardName: profile.name,
      wardPhone: profile.guardian?.phone ?? null,
      stage: 2,
      dongName: profile.dongName,
      // v0.3: openedAt/respondedAt replace the previous single timestamp.
      // Both null here means the ward has neither opened the link nor tapped
      // a response yet.
      openedAt: null,
      respondedAt: null,
      lastResponse: 'none',
      // v0.3: safetyStatus is always 'unknown' for now (no inference).
      safetyStatus: 'unknown',
      acknowledgedByGuardian: false,
    }
  },

  async postGuardianAcknowledge(token: string): Promise<Ack> {
    await randomDelay()
    void token
    return { ok: true }
  },
}
