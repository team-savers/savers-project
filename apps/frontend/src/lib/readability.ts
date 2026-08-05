// Readability + 행정 용어 치환 (clarity metric instrumentation).
//
// 이 모듈은 명확성 지표의 **rule-based 절반만** 담당한다. rule-based check
// 가 이 모듈이고, 별도의 독립적인 LLM 채점은 이 모듈이 다루지 않는다.
// 따라서 아래 지표는 휴리스틱이며, 최종 평가 점수와는 다를 수 있다.
//
// 다섯 가지를 담당하며, 모두 순수(console.info 부수효과 제외):
//
//   1. 사전 export (아래 참조) — 행정 용어 → 쉬운 우리말 매핑 (rule-based
//      only; NLP/형태소 분석은 도입하지 않았다).
//        - term 은 문자열 배열(string[]) 로 보관한다.
//        - 20개 이상의 항목을 유지한다.
//   2. substituteAdminTerms()    — 문장 안의 행정 용어를 쉬운 말로 바꾼다.
//                                  길이가 긴 term 부터 치환하여 짧은 term 이
//                                  먼저 매칭되어 의미가 깨지는 사태를 막는다.
//   3. computeSubstitutionStats()— (원문 대비) 행정 용어 치환 통계. 분모는
//                                  근거 원문에 등장한 행정용어 수, 분자는
//                                  그중 생성문에 남아있지 않은 수. 원문이
//                                  없으면 측정 불가 → null.
//   4. hasSingleAction()         — "한 가지 행동을 바로 할 수 있는지"
//                                  휴리스틱.
//   5. measureReadability()      — 위 측정값들을 한 번에 모아 돌려준다.
//                                  한 화면 렌더당 1회만 호출해야 한다.
//                                  영속 저장소에는 넣지 않는다.
//
// 평가 기준 (목표):
//   - 행정 용어 → 쉬운 말 치환율 ≥ 90% (rule-based + 독립적 LLM 채점)
//   - "한 가지 행동 지침" 포함율 100%
//
// 휴리스틱 주의:
//   - 치환 사전은 본 작업에서 정리한 목록이며, 도메인이 확장되면 항목을
//     추가한다. 한국어 자연어의 모든 표현을 완벽히 다루지는 못한다 —
//     채점은 "유효 후보만 카운트" 방식으로 하여 위양성(false positive)이
//     지표를 부풀리지 않게 한다.
//   - NLP/형태소 분석은 도입하지 않았다. 정해진 사전 + 경로만 사용한다.

// 타입만 가져온다(런타임 의존 없음) — 단계적 노출의 지침 판별이 화면
// 언어별로 갈리기 때문이다(아래 STEP_DIRECTIVE_PATTERNS 참조).
import type { Language } from '../api/types'

// ---- Term dictionary --------------------------------------------------

export type TermCategory =
  | 'hazard' // 위험/재해
  | 'action' // 행동 지침
  | 'place' // 장소
  | 'time' // 시간
  | 'admin' // 행정/제도

export interface AdminTermMeta {
  plain: string
  category: TermCategory
}

// term 은 문자열 배열(string[]) 로 보관한다.
// 사전의 "term" 문자열만 노출한다. plain/category 메타데이터는 별도 맵
// (TERM_META)으로 연결한다 — 이렇게 분리해야 치환 로직이 깨지지 않는다.
export const ADMIN_TERMS: string[] = [
  // hazard
  '호우주의보',
  '호우경보',
  '도시침수',
  '하천범람',
  '산사태',
  '상습침수구역',
  '침수 위험 지역',
  '침수구역',
  '저지대',
  '반지하 주택',
  '하천 범람',
  '급경사지',
  '침수도로',
  '감전사고',
  '휩쓸림 위험',
  '배수로의 토사 유출',
  '토사 유출 징후',
  '토사 유출',
  '붕괴 위험',
  '붕괴 우려나',
  '축대 붕괴 우려',
  '붕괴 우려',
  '축대 붕괴',
  '매몰사고',
  '인명피해',
  '재산피해',
  '수방자재',
  '자동차 시동 꺼짐이 우려되는',
  '자동차 시동 꺼짐이 발생하면',
  '산비탈의 낙석',
  '낙석',
  // action
  '긴급대피',
  '사전대피',
  '수직대피',
  '수평대피',
  '대피소로 이동',
  '대피 명령',
  '대피 권고',
  '대피',
  '구조 요청',
  '긴급 구조',
  '응급구조',
  '구급차 파견',
  '전입 통보',
  '안전 확인',
  '진입금지 표지',
  '진입금지 안내를 보면',
  '진입금지 구역에도 들어가지 마세요',
  '야외활동 자제 안내에 따라',
  '접근 금지 안내가 나오면',
  // place
  '임시대피소',
  '지정대피소',
  '대피소',
  '주민센터',
  '행정복지센터',
  '지하공간',
  '지하차도',
  '저지대 주택',
  '상가',
  '임시주거시설',
  '배수로',
  '하천변',
  '해안가',
  '논둑',
  // time
  '즉시',
  '신속히',
  '사전',
  '야간',
  '심야',
  '주행 중',
  // admin
  '행정안전부',
  '기상청',
  '소방청',
  '지자체',
  '지방자치단체',
  '관할 기관',
  '재난문자',
  '긴급재난문자',
  '재난 안전데이터',
  '국민행동요령',
  '안전취약계층',
  '안전취약계층에 해당하면',
  '재해예방 활동',
  '이·통장',
]

// term → 메타데이터. ADMIN_TERMS 의 각 항목은 반드시 이 맵에 대응값을
// 가진다. 모듈 로드 시점에 한 번만 검증한다.
const TERM_META: Record<string, AdminTermMeta> = {
  // hazard
  호우주의보: { plain: '비가 많이 올 수 있어 조심해야 함', category: 'hazard' },
  호우경보: { plain: '매우 많은 비가 쏟아져 위험함', category: 'hazard' },
  도시침수: { plain: '도시에 물이 넘쳐서 길이 잠김', category: 'hazard' },
  하천범람: { plain: '강물이 넘쳐서 주변이 잠김', category: 'hazard' },
  산사태: { plain: '산의 흙과 돌이 쏟아져 내려옴', category: 'hazard' },
  상습침수구역: { plain: '비가 오면 자주 물이 차는 곳', category: 'hazard' },
  '침수 위험 지역': { plain: '물이 차기 쉬운 위험한 곳', category: 'hazard' },
  침수구역: { plain: '물이 차 있는 곳', category: 'hazard' },
  저지대: { plain: '주변보다 낮아 물이 모이는 곳', category: 'hazard' },
  '반지하 주택': { plain: '지하에 있는 집', category: 'hazard' },
  '하천 범람': { plain: '강물이 넘치는 일', category: 'hazard' },
  급경사지: { plain: '가파른 비탈', category: 'hazard' },
  침수도로: { plain: '물에 잠긴 도로', category: 'hazard' },
  감전사고: { plain: '전기에 닿아 다치는 사고', category: 'hazard' },
  '휩쓸림 위험': { plain: '물살에 떠밀릴 위험', category: 'hazard' },
  '배수로의 토사 유출': {
    plain: '물이 빠지는 길에서 흙과 돌이 흘러나오는 일',
    category: 'hazard',
  },
  '토사 유출 징후': { plain: '흙과 돌이 흘러나올 조짐', category: 'hazard' },
  '토사 유출': { plain: '흙과 돌이 흘러나오는 일', category: 'hazard' },
  '붕괴 위험': { plain: '무너질 위험', category: 'hazard' },
  '붕괴 우려나': { plain: '무너질 가능성이 있거나', category: 'hazard' },
  '축대 붕괴 우려': {
    plain: '쌓아 올린 벽이 무너질 가능성',
    category: 'hazard',
  },
  '붕괴 우려': { plain: '무너질 가능성', category: 'hazard' },
  '축대 붕괴': { plain: '쌓아 올린 벽이 무너지는 일', category: 'hazard' },
  매몰사고: { plain: '흙이나 무너진 것에 깔리는 사고', category: 'hazard' },
  인명피해: { plain: '사람이 다치거나 숨지는 피해', category: 'hazard' },
  재산피해: { plain: '집이나 물건이 망가지는 피해', category: 'hazard' },
  수방자재: { plain: '물을 막는 물품', category: 'hazard' },
  '자동차 시동 꺼짐이 우려되는': {
    plain: '자동차 시동이 꺼질 수 있는',
    category: 'hazard',
  },
  '자동차 시동 꺼짐이 발생하면': {
    plain: '자동차 시동이 꺼지면',
    category: 'hazard',
  },
  '산비탈의 낙석': { plain: '산에서 돌이 떨어지는 것', category: 'hazard' },
  낙석: { plain: '돌이 떨어지는 것', category: 'hazard' },
  // action
  긴급대피: { plain: '지금 바로 안전한 곳으로 피함', category: 'action' },
  사전대피: { plain: '위험이 오기 전에 미리 피함', category: 'action' },
  수직대피: { plain: '건물의 높은 층으로 피함', category: 'action' },
  수평대피: { plain: '옆에 있는 안전한 건물로 피함', category: 'action' },
  '대피소로 이동': { plain: '안전한 곳(대피소)으로 가기', category: 'action' },
  '대피 명령': { plain: '지금 당장 피하라는 지시', category: 'action' },
  '대피 권고': { plain: '안전을 위해 피하는 것이 좋음', category: 'action' },
  대피: { plain: '안전한 곳으로 피하기', category: 'action' },
  '구조 요청': { plain: '도와달라고 구급·구조에 전화하기', category: 'action' },
  '긴급 구조': { plain: '위험에 빠진 사람을 구하는 일', category: 'action' },
  응급구조: { plain: '위급한 사람을 살리는 구조', category: 'action' },
  '구급차 파견': { plain: '구급차를 보내 달라고 신청', category: 'action' },
  '전입 통보': { plain: '이 사 갔음을 알림', category: 'action' },
  '안전 확인': { plain: '다친 데가 없는지 살핌', category: 'action' },
  '진입금지 표지': { plain: '들어가지 말라는 표지', category: 'action' },
  '진입금지 안내를 보면': {
    plain: '들어가지 말라는 안내를 보면',
    category: 'action',
  },
  '진입금지 구역에도 들어가지 마세요': {
    plain: '들어가지 못하게 막아 둔 곳에는 가지 마세요',
    category: 'action',
  },
  '야외활동 자제 안내에 따라': {
    plain: '밖에서 하는 활동을 줄이라는 안내에 따라',
    category: 'action',
  },
  '접근 금지 안내가 나오면': {
    plain: '다가가지 말라는 안내가 나오면',
    category: 'action',
  },
  // place
  임시대피소: { plain: '잠깐 머무르는 안전한 곳', category: 'place' },
  지정대피소: { plain: '정해진 안전한 곳', category: 'place' },
  대피소: { plain: '안전하게 피하는 곳', category: 'place' },
  주민센터: { plain: '동네의 도움을 주는 곳', category: 'place' },
  행정복지센터: {
    plain: '주민센터(동네의 도움을 주는 곳)',
    category: 'place',
  },
  지하공간: { plain: '지하에 있는 곳', category: 'place' },
  지하차도: { plain: '지하로 내려가는 길', category: 'place' },
  '저지대 주택': { plain: '낮은 곳에 있는 집', category: 'place' },
  상가: { plain: '가게', category: 'place' },
  임시주거시설: { plain: '잠시 머무는 곳', category: 'place' },
  배수로: { plain: '물이 빠지는 길', category: 'place' },
  하천변: { plain: '강가', category: 'place' },
  해안가: { plain: '바닷가', category: 'place' },
  논둑: { plain: '논 가장자리 둑길', category: 'place' },
  // time
  즉시: { plain: '곧바로', category: 'time' },
  신속히: { plain: '빨리', category: 'time' },
  사전: { plain: '미리', category: 'time' },
  야간: { plain: '밤', category: 'time' },
  심야: { plain: '늦은 밤', category: 'time' },
  '주행 중': { plain: '운전하는 동안', category: 'time' },
  // admin
  행정안전부: { plain: '나라의 안전을 챙기는 부처', category: 'admin' },
  기상청: { plain: '날씨를 알려주는 곳', category: 'admin' },
  소방청: { plain: '불 및 구조를 담당하는 곳', category: 'admin' },
  지자체: { plain: '시·군·구청', category: 'admin' },
  지방자치단체: { plain: '시·군·구청', category: 'admin' },
  '관할 기관': { plain: '담당하는 공공기관', category: 'admin' },
  재난문자: { plain: '재난 안내 문자', category: 'admin' },
  '긴급재난문자': { plain: '급하게 보내는 재난 안내 문자', category: 'admin' },
  '재난 안전데이터': { plain: '재난 대비 공공 정보', category: 'admin' },
  국민행동요령: { plain: '국민이 따라 할 안전 행동', category: 'admin' },
  안전취약계층: { plain: '재난 때 도움이 더 필요한 사람', category: 'admin' },
  '안전취약계층에 해당하면': {
    plain: '재난 때 도움이 더 필요한 사람이라면',
    category: 'admin',
  },
  '재해예방 활동': { plain: '재난 피해를 막는 활동', category: 'admin' },
  '이·통장': { plain: '마을 이장이나 통장', category: 'admin' },
}

// Some terms need a different surface depending on their immediate grammar
// slot. Korean conjugation cannot be derived safely from an arbitrary plain
// string, so these are explicit and opt-in; TERM_META.plain remains the
// legacy fallback for every term without a surface here.
type SurfaceContext =
  | 'noun'
  | 'modifier'
  | 'directImperative'
  | 'directConnective'
  | 'objectDo'
  | 'objectPastConnective'
  | 'objectRequest'
  | 'objectApply'
  | 'recipientImperative'
  | 'directionalImperative'

type TermSurfaces = Partial<Record<SurfaceContext, string>>

const TERM_SURFACES: Readonly<Partial<Record<string, TermSurfaces>>> = {
  호우주의보: {
    modifier: '많은 비에 대한 주의 알림',
  },
  호우경보: {
    noun: '매우 많은 비가 와서 위험하다는 경보',
  },
  도시침수: {
    noun: '도시에 물이 넘쳐 길이 잠긴 일',
  },
  하천범람: {
    noun: '강물이 넘치는 일',
  },
  산사태: {
    noun: '산의 흙과 돌이 쏟아져 내려오는 일',
  },
  저지대: {
    modifier: '주변보다 낮은 곳의',
  },
  긴급대피: {
    directImperative: '지금 바로 안전한 곳으로 피하세요',
    directConnective: '지금 바로 안전한 곳으로 피하고',
  },
  사전대피: {
    directImperative: '위험이 오기 전에 미리 피하세요',
    objectDo: '위험이 오기 전에 미리 피하세요',
  },
  수직대피: {
    directImperative: '건물의 높은 층으로 피하세요',
    directionalImperative: '피하세요',
  },
  수평대피: {
    directImperative: '옆에 있는 안전한 건물로 피하세요',
    directionalImperative: '피하세요',
  },
  '대피소로 이동': {
    directImperative: '안전한 곳(대피소)으로 가세요',
  },
  '대피 권고': {
    noun: '안전을 위해 피하라는 안내',
  },
  대피: {
    directImperative: '안전한 곳으로 피하세요',
  },
  '구조 요청': {
    objectDo: '도와달라고 구급·구조에 전화하세요',
  },
  '긴급 구조': {
    objectRequest: '위험에 빠진 사람을 구해 달라고 하세요',
  },
  '구급차 파견': {
    objectApply: '구급차를 보내 달라고 하세요',
  },
  '전입 통보': {
    recipientImperative: '이사 왔거나 간 사실을 알리세요',
  },
  '안전 확인': {
    objectPastConnective: '다친 데가 없는지 확인한 뒤',
    modifier: '다친 데가 없는지 확인하는',
  },
}

// 정확성 검증. ADMIN_TERMS 의 모든 항목이 TERM_META 에 대응값을 가져야
// 한다. 모듈 로드 시점에 한 번만 검사한다.
if (ADMIN_TERMS.length < 20) {
  console.warn(
    `[readability] ADMIN_TERMS has only ${ADMIN_TERMS.length} entries — expected ≥ 20.`,
  )
}
for (const t of ADMIN_TERMS) {
  if (TERM_META[t] === undefined) {
    // 개발자에게만 보이는 경고. 사용자 화면에는 영향 없음.
    console.warn(`[readability] TERM_META missing entry for "${t}"`)
  }
}

// ---- Replacement core -------------------------------------------------

export interface Replacement {
  original: string
  // Dictionary's canonical plain form. Context-aware rendering may choose a
  // grammatical surface variant while this public reporting value stays
  // stable for callers that aggregate repeated occurrences.
  plain: string
  category: TermCategory
  count: number
}

// ---- Josa (postposition) correction ----------------------------------
//
// After substituting an admin term with a plain phrase, the following josa
// may become grammatically wrong because the substituted phrase ends in a
// different final consonant (jongseong) than the original term did. The
// canonical example: "호우경보가" → "매우 많은 비가 쏟아져 위험함가"
// (the trailing "가" was correct for "호우경보" but is wrong after "위험함").
//
// This re-derives the josa from the jongseong of the LAST character of the
// plain substitution. The rule set:
//   이/가 · 은/는 · 을/를 · 와/과 · 로/으로
// ㄹ 받침 takes "로" (not "으로") — the special ㄹ rule.
//
// Unicode Hangul syllable block: 0xAC00..0xD7A3. For a syllable S:
//   jongseongIndex = (S - 0xAC00) % 28
//   jongseongIndex === 0 → no final consonant (받침 없음) → 이/은/을/와/로
//   jongseongIndex !== 0 → final consonant present → 가/는/를/과/으로
//  jongseongIndex === 8 (ㄹ) → uses "로" even though it has a consonant.
//
// Non-Hangul final char (Latin letter, digit, punctuation): do NOT rewrite
// the josa — there is no reliable jongseong to compute from. The original
// josa is preserved as-is.

// Whether a character is a precomposed Hangul syllable (the block that
// has a computable jongseong). Returns false for jamo, Latin, digits, etc.
function isHangulSyllable(ch: string | undefined): boolean {
  if (ch === undefined || ch.length === 0) return false
  const code = ch.codePointAt(0)
  if (code === undefined) return false
  return code >= 0xac00 && code <= 0xd7a3
}

// Final consonant (jongseong) presence for a Hangul syllable.
//   true  → 받침 있음 (except ㄹ which is handled specially by callers)
//   false → 받침 없음
function hasJongseong(ch: string): boolean {
  const code = ch.codePointAt(0)
  if (code === undefined) return false
  return (code - 0xac00) % 28 !== 0
}

// The special ㄹ jongseong (index 8 in the Unicode Hangul syllable table).
// ㄹ 받침 takes "로"/"와" like a 받침없음 syllable for the 으/로 pair.
function isRieulJongseong(ch: string): boolean {
  const code = ch.codePointAt(0)
  if (code === undefined) return false
  return (code - 0xac00) % 28 === 8
}

// Josa pairs. Each entry: [withJongseong, withoutJongseong]. The caller
// picks based on the last char of the substituted phrase.
const JOSA_PAIRS: ReadonlyArray<{
  pair: [string, string]
  // ㄹ 받침 overrides to the withoutJongseong variant (the Korean ㄹ-dorobo rule).
  rieulTakesWithout?: boolean
}> = [
  { pair: ['이', '가'] },
  { pair: ['은', '는'] },
  { pair: ['을', '를'] },
  { pair: ['과', '와'] },
  { pair: ['으로', '로'], rieulTakesWithout: true },
]

// Map each possible trailing josa char to the pair it belongs to and the
// direction of correction. We index by the FIRST character of each josa
// form so we can detect "이"/"가" etc. in the source text regardless of
// which variant the original author used.
//
// For two-char josa ("으로"/"로") we key on '으' and '로'. A trailing
// "으로" maps to the withJongseong slot; a trailing "로" maps to the
// withoutJongseong slot. We detect "으로" as a two-char sequence before
// falling back to the single "로" key.
interface JosaRule {
  pairIndex: number
  // The slot this josa currently occupies: 0 = withJongseong, 1 = without.
  currentSlot: 0 | 1
  // Length of the matched josa in the source text (1 or 2 chars).
  matchLen: number
}

function matchJosa(after: string): JosaRule | null {
  // Two-char josa first so "으로" is not mistaken for "으".
  if (after.startsWith('으로')) {
    return { pairIndex: 4, currentSlot: 0, matchLen: 2 }
  }
  const head = after.charAt(0)
  for (let i = 0; i < JOSA_PAIRS.length; i++) {
    const { pair } = JOSA_PAIRS[i]
    // pair[0] = withJongseong form, pair[1] = withoutJongseong form.
    if (head === pair[0] && pair[0].length === 1) {
      return { pairIndex: i, currentSlot: 0, matchLen: 1 }
    }
    if (head === pair[1] && pair[1].length === 1) {
      return { pairIndex: i, currentSlot: 1, matchLen: 1 }
    }
  }
  return null
}

// Returns the correct josa string for a given substituted phrase's last
// char and a matched josa rule. Respects the ㄹ special case.
function correctJosa(
  lastChar: string,
  rule: JosaRule,
): string {
  const entry = JOSA_PAIRS[rule.pairIndex]
  if (entry === undefined) return ''
  // Decide the desired slot from the jongseong of the last char.
  let desiredSlot: 0 | 1
  if (!isHangulSyllable(lastChar)) {
    // Non-Hangul — keep whatever the source had.
    desiredSlot = rule.currentSlot
  } else if (isRieulJongseong(lastChar) && entry.rieulTakesWithout === true) {
    desiredSlot = 1
  } else if (hasJongseong(lastChar)) {
    desiredSlot = 0
  } else {
    desiredSlot = 1
  }
  const out = entry.pair[desiredSlot]
  return out ?? ''
}

// (term, meta) 쌍을 길이-우선 정렬한 사본. 긴 term 부터 치환해야 짧은
// term 이 먼저 매칭되어 의미가 깨지는 일이 없다 (예: "대피소"가 "대피"를
// 포함).
const SORTED_ENTRIES: ReadonlyArray<{ term: string; meta: AdminTermMeta }> =
  ADMIN_TERMS
    .map((term) => ({ term, meta: TERM_META[term] }))
    .filter((e): e is { term: string; meta: AdminTermMeta } => e.meta !== undefined)
    .sort((a, b) => b.term.length - a.term.length)

interface SurfaceMatch {
  context: SurfaceContext | 'legacy'
  consume: number
  recipient?: string
}

// Kept for countAdminTermOccurrences(), which still uses placeholders to
// prevent overlapping dictionary terms from being counted twice.
const PLACEHOLDER_PREFIX = '\uE000'
const PLACEHOLDER_SUFFIX = '\uE001'

// A bare term must not begin inside a larger Hangul compound. The scanner
// still permits the longer dictionary entry at the compound's first letter,
// so "지정대피소" can match while "대피소로 이동" cannot start at its middle.
function hasLeftLexicalBoundary(text: string, start: number): boolean {
  return start === 0 || !isHangulSyllable(text.charAt(start - 1))
}

function findEntryAt(
  text: string,
  start: number,
): { term: string; meta: AdminTermMeta } | undefined {
  return SORTED_ENTRIES.find(
    (entry) =>
      text.startsWith(entry.term, start) && hasLeftLexicalBoundary(text, start),
  )
}

function hasDirectionImmediatelyBefore(text: string, start: number): boolean {
  const before = text.slice(Math.max(0, start - 32), start)
  return /[가-힣]+(?:으로|로)\s*$/.test(before)
}

// Only immediate, bounded grammar tails are recognized. This intentionally
// avoids a Korean morphology engine and leaves unknown action contexts alone.
function classifySurfaceContext(
  text: string,
  start: number,
  end: number,
): SurfaceMatch {
  const after = text.slice(end)
  const recipient = after.match(/^(?:을|를)\s*([^,.!?]+?에게)\s+하세요/)
  if (recipient !== null) {
    return {
      context: 'recipientImperative',
      consume: recipient[0].length,
      recipient: recipient[1],
    }
  }
  const objectPastConnective = after.match(/^(?:을|를)\s+한\s+뒤/)
  if (objectPastConnective !== null) {
    return { context: 'objectPastConnective', consume: objectPastConnective[0].length }
  }
  const objectRequest = after.match(/^(?:을|를)\s+요청하세요/)
  if (objectRequest !== null) {
    return { context: 'objectRequest', consume: objectRequest[0].length }
  }
  const objectApply = after.match(/^(?:을|를)\s+신청하세요/)
  if (objectApply !== null) {
    return { context: 'objectApply', consume: objectApply[0].length }
  }
  const objectDo = after.match(/^(?:을|를)\s+하세요/)
  if (objectDo !== null) {
    return { context: 'objectDo', consume: objectDo[0].length }
  }
  if (after.startsWith('하세요')) {
    return {
      context: hasDirectionImmediatelyBefore(text, start)
        ? 'directionalImperative'
        : 'directImperative',
      consume: '하세요'.length,
    }
  }
  if (after.startsWith('하고')) {
    return { context: 'directConnective', consume: '하고'.length }
  }
  if (matchJosa(after) !== null || after.startsWith(',')) {
    return { context: 'noun', consume: 0 }
  }
  if (/^\s+[가-힣]/.test(after)) {
    return { context: 'modifier', consume: 0 }
  }
  return { context: 'legacy', consume: 0 }
}

function selectSurface(
  entry: { term: string; meta: AdminTermMeta },
  match: SurfaceMatch,
): string | null {
  const surfaces = TERM_SURFACES[entry.term]
  const surface =
    match.context === 'legacy'
      ? undefined
      : surfaces?.[match.context]
  if (surface !== undefined) {
    return match.context === 'recipientImperative' && match.recipient !== undefined
      ? `${match.recipient} ${surface}`
      : surface
  }

  // A term with explicit grammatical surfaces is context-sensitive. When its
  // current non-legacy slot is not defined, keeping the original term is safer
  // than falling back to a predicate-like plain phrase that may break syntax.
  if (surfaces !== undefined && match.context !== 'legacy') {
    return null
  }

  // A noun/action plain string before another noun, or an unrecognized action
  // ending, is more likely to be broken than helpful. Keep the source term in
  // those cases until a safe surface is explicitly supplied.
  if (
    entry.meta.category === 'action' &&
    (match.context === 'modifier' || match.context === 'legacy')
  ) {
    return null
  }
  return entry.meta.plain
}

// 한 문장을 치환한다. 한 번 왼쪽에서 오른쪽으로만 읽으므로 삽입한 평문은
// 다시 사전 매칭하지 않는다. 길이 우선 정렬은 findEntryAt()에서 유지된다.

export function substituteAdminTerms(text: string): {
  plain: string
  replaced: Replacement[]
} {
  if (typeof text !== 'string' || text.length === 0) {
    return { plain: '', replaced: [] }
  }

  const replacementCounts = new Map<string, number>()
  let plain = ''
  let cursor = 0

  while (cursor < text.length) {
    const entry = findEntryAt(text, cursor)
    if (entry === undefined) {
      plain += text.charAt(cursor)
      cursor += 1
      continue
    }

    const end = cursor + entry.term.length
    // A named destination followed by the stock "로 이동하세요" instruction is
    // already a clear, intact movement phrase. Keeping it also prevents the
    // shorter movement dictionary entry from being reached inside the name.
    if (
      entry.meta.category === 'place' &&
      text.startsWith('로 이동하세요', end)
    ) {
      plain += entry.term
      cursor = end
      continue
    }
    const context = classifySurfaceContext(text, cursor, end)
    const surface = selectSurface(entry, context)
    if (surface === null) {
      plain += entry.term
      cursor = end
      continue
    }

    let next = end + context.consume
    let rendered = surface
    // Josa is copied only when the source tail remains in place. Contextual
    // surfaces that consume an ending already contain their own conjugation.
    if (context.consume === 0) {
      const rule = matchJosa(text.slice(end))
      if (rule !== null) {
        const lastChar = rendered.charAt(rendered.length - 1)
        rendered += correctJosa(lastChar, rule)
        next = end + rule.matchLen
      }
    }

    plain += rendered
    replacementCounts.set(
      entry.term,
      (replacementCounts.get(entry.term) ?? 0) + 1,
    )
    cursor = next
  }

  const replaced: Replacement[] = []
  // Preserve the existing longest-first reporting order and public fields.
  for (const entry of SORTED_ENTRIES) {
    const count = replacementCounts.get(entry.term)
    if (count !== undefined) {
      replaced.push({
        original: entry.term,
        plain: entry.meta.plain,
        category: entry.meta.category,
        count,
      })
    }
  }

  return { plain, replaced }
}

// ---- Clarity metrics --------------------------------------------------

// 행정용어가 한 텍스트에 등장하는 총 횟수를 센다(길이-우선 매칭으로 중복
// 카운트 방지). 치환율의 분모(원문)와 분자 계산(생성문에 남은 수) 양쪽에
// 쓰인다 — 같은 알고리즘을 써야 두 텍스트를 공정하게 비교할 수 있다.
function countAdminTermOccurrences(text: string): {
  total: number
  byTerm: Record<string, number>
} {
  if (typeof text !== 'string' || text.length === 0) {
    return { total: 0, byTerm: {} }
  }
  let work = text
  const byTerm: Record<string, number> = {}
  for (const entry of SORTED_ENTRIES) {
    if (!work.includes(entry.term)) {
      continue
    }
    const parts = work.split(entry.term)
    if (parts.length > 1) {
      const count = parts.length - 1
      byTerm[entry.term] = (byTerm[entry.term] ?? 0) + count
      const idx = Object.keys(byTerm).length - 1
      const ph = `${PLACEHOLDER_PREFIX}${idx}${PLACEHOLDER_SUFFIX}`
      work = parts.join(ph)
    }
  }
  const total = Object.values(byTerm).reduce((s, n) => s + n, 0)
  return { total, byTerm }
}

// 근거 원문(sourceQuotes) 대비 생성문(body) 의 행정용어 치환 통계.
//
// 치환율 정의:
//   치환율 = (원문에 있었으나 생성문에 남아 있지 않은 행정용어 수)
//            / (원문에 등장한 행정용어 수)
//
// 비교 대상이 있어야 성립한다. 분모는 원문(국민행동요령 quote 들을 합친
// 텍스트)에서 사전에 있는 행정용어가 등장한 총 횟수, 분자는 그중 생성문
// (LLM 이 만든 body)에 여전히 남아 있는 용어 수를 뺀 값이다. 원문이 어려운
// 말을 쓰고 생성문이 쉰 말로 바꿨으면 1.0 에 가깝게 나온다.
//
// 이 정의가 이전 버전("원문에서 인식한 용어 중 치환한 비율")과 다른 점:
// 이전 버전은 분모·분자가 같은 알고리즘(사전 매칭 → 치환)이었으므로 항상
// 1.0 이 나와 지표로서 무의미했다. 현재 버전은 두 독립 텍스트(원문 vs
// 생성문)를 비교하므로 생성 품질에 따라 0~1 사이의 의미 있는 값이 나온다.
//
// 원문(sourceQuotes 결합)이 비어 있으면 측정할 수 없다. 이때 0이나 1로
// 채우지 않고 null 을 반환한다 — "못 쟀다"와 "0%"는 다르다.
export function computeSubstitutionStats(
  body: string,
  sourceQuotes: string[],
): { total: number; replaced: number; ratio: number | null } {
  const sourceText = (sourceQuotes ?? []).join('\n')
  if (sourceText.length === 0) {
    return { total: 0, replaced: 0, ratio: null }
  }

  const source = countAdminTermOccurrences(sourceText)
  if (source.total === 0) {
    // 원문에 사전 상의 행정용어가 하나도 없으면 비교 기준이 없다.
    // 0/0 은 정의되지 않으므로 null.
    return { total: 0, replaced: 0, ratio: null }
  }

  const remaining = countAdminTermOccurrences(body)
  // 분자 = 원문에 있었으나 생성문에 남아 있지 않은 행정용어 수.
  // (음수가 나올 수 없도록 min 처리 — 생성문이 원문보다 용어를 더 많이
  // 쓰는 극단적 케이스 방어. 정상이라면 remaining.total <= source.total.)
  const replaced = Math.max(0, source.total - remaining.total)
  const ratio = replaced / source.total
  return { total: source.total, replaced, ratio }
}

// 한 문장이 "한 가지 행동을 즉시 할 수 있는지" 판단하는 휴리스틱.
//
// "한 가지 행동" 판정 규칙:
//   - 문장을 어절/문장 부호로 나눈다.
//   - 각 부분에서 행동 지시(category === 'action') term 이 등장하는지
//     검사.
//   - 행동 term 이 정확히 1개 등장하는 구조를 "found" 로 본다.
//   - 행동 term 이 0개이거나 2개 이상이면 "found: false" — 한 가지
//     행동이 아니다.
//
// 이 휴리스틱은 명확한 한계를 가진다: NLP가 없으므로 "가까운 대피소로
// 이동하고 보호자에게 전화하세요" 같은 복문을 "두 행동"으로 올바르게
// 잡아내지만, "이동 준비를 하세요" 같은 일상어 행동 표현은 잡지 못한다.
// 이 한계는 의도적으로 수용된다 — 사전 + 경로 기반 접근만으로 커버하고,
// 자연어 이해는 별도의 독립적 LLM 채점이 담당한다.
//
// 반환:
//   { found: true,  action: '<원문 term>' }  — 한 가지 행동 발견
//   { found: false, action: null }          — 0개 또는 2개 이상
export function hasSingleAction(text: string): {
  found: boolean
  action: string | null
} {
  if (typeof text !== 'string' || text.length === 0) {
    return { found: false, action: null }
  }

  // 행동 term 들을 길이-우선으로 매칭하여 중복 카운트를 막는다.
  let work = text
  const matchedActions: { term: string; count: number }[] = []

  const actionEntries = SORTED_ENTRIES.filter(
    (e) => e.meta.category === 'action',
  )
  for (const entry of actionEntries) {
    if (!work.includes(entry.term)) {
      continue
    }
    const parts = work.split(entry.term)
    if (parts.length > 1) {
      const count = parts.length - 1
      matchedActions.push({ term: entry.term, count })
      const idx = matchedActions.length - 1
      const ph = `${PLACEHOLDER_PREFIX}${idx}${PLACEHOLDER_SUFFIX}`
      work = parts.join(ph)
    }
  }

  const totalActionCount = matchedActions.reduce((s, a) => s + a.count, 0)
  if (totalActionCount !== 1) {
    return { found: false, action: null }
  }

  const single = matchedActions[0]
  if (single === undefined) {
    return { found: false, action: null }
  }
  return { found: true, action: single.term }
}

// ---- Aggregate readability metric ------------------------------------

export interface ReadabilityMetric {
  // 행정 용어 → 쉬운 말 치환 통계. (생성문 body 에서 사전에 있는 행정용어가
  // 등장한 고유 term 수 — 쉬운 말로 안 바뀌고 남은 어려운 말의 종류 수.)
  adminTermCount: number
  // 발견된 행정 용어 원문(term) 목록. 중복 제거. UI에서 "어려운 말 N종"
  // 표기 및 평가 하네스에서 모두 쓰인다.
  adminTermsFound: string[]
  // 행정 용어 → 쉬운 말 치환 비율. ratio 는 원문(sourceQuotes)이 비어 있거나
  // 원문에 사전 상의 행정용어가 없으면 null 이다(측정 불가).
  substitutionRatio: {
    total: number
    replaced: number
    ratio: number | null
  }
  // "한 가지 행동 지침" 포함 여부.
  hasSingleAction: {
    found: boolean
    action: string | null
  }
  // 글자 수. 단순 length.
  charCount: number
  // 문장 수. 마침표/느낌표/물음표 + 줄바꿈 기준.
  sentenceCount: number
  // 측정 시각(ISO). 채점 자동화에서 그대로 사용.
  measuredAt: string
}

// 문장 구분자. 한국어 문장 부호(。！？)는 거의 쓰이지 않으므로
// 서양 부호(.!?)와 줄바꿈을 기준으로 삼는다.
const SENTENCE_END = /[.!?。\n]/

// 한 화면의 가독성 지표를 잼다.
//
// 이전에는 measureReadability(original) 하나만 받았지만, 치환율이
// "원문 대비 생성문" 비교로만 성립하므로 근거 원문 배열(sourceQuotes)을
// 함께 받는다. 측정의 주대상은 body(서버가 준 생성문 원본)이며,
// sourceQuotes 는 치환율 계산을 위한 비교 기준만 제공한다.
//
// 이 함수는 사실상 순수 함수다: 부수 효과는 콘솔 출력(info) 뿐이고, 입력이
// 같으면 결과(measuredAt 제외)가 같다. measuredAt 은 호출 시각이므로 매번
// 달라진다.
//
// 강제 제약:
//   - 영속 저장소(브라우저 Web Storage 등) 사용 금지 → 측정 결과를
//     저장하지 않는다.
//   - 측정은 한 화면 렌더당 1회 → 호출자가 1회만 호출해야 한다. 본 모듈은
//     자체적으로 캐싱/메모이제이션 하지 않는다.
//   - 측정 결과는 console.info 로만 출력한다. (채점 자동화에서는 별도로
//     수집되며, 데모 화면에서는 콘솔만 보면 된다.)
//   - 측정 대상은 서버가 준 body 원본이다. 화면에
//     표시하려고 가공(치환 등)한 문자열을 재면 안 된다.
export function measureReadability(
  body: string,
  sourceQuotes: string[],
): ReadabilityMetric {
  const ratio = computeSubstitutionStats(body, sourceQuotes)
  const action = hasSingleAction(body)
  const { replaced } = substituteAdminTerms(body)

  const adminTermsFound = replaced.map((r) => r.original)
  const charCount = body.length
  const sentenceCount = countSentences(body)
  const measuredAt = new Date().toISOString()

  const metric: ReadabilityMetric = {
    adminTermCount: replaced.reduce((s, r) => s + (r.count > 0 ? 1 : 0), 0),
    adminTermsFound,
    substitutionRatio: ratio,
    hasSingleAction: action,
    charCount,
    sentenceCount,
    measuredAt,
  }

  // 개발/평가용 콘솔 출력. info 레벨이므로 경고로 보이지 않는다.
  console.info('[savers readability]', metric)

  return metric
}

function countSentences(text: string): number {
  if (typeof text !== 'string' || text.length === 0) {
    return 0
  }
  const pieces = text.split(SENTENCE_END).filter((s) => s.trim().length > 0)
  return Math.max(1, pieces.length)
}

// ---- 단계적 노출(EasyText "다음" 버튼) ----------------------------------
//
// splitIntoSteps/orderStepsDirectiveFirst는 원래 EasyText.tsx 안에 있었다
// (PR #50). 순수 함수라 프론트엔드에 테스트 러너가 들어오면 바로 테스트할
// 수 있도록 여기로 옮겼다(PR #50 리뷰 코멘트).

// apps/ai-engine의 guardrail._SENTENCE_SPLIT과 반드시 같은 기준을 써야
// 한다 — 두 곳이 서로 다른 문장 경계를 쓰면 "몇 문장인지"가 화면마다
// 달라진다.
const STEP_SENTENCE_SPLIT = /(?<=[.!?。])\s+|\n+/

// lookbehind(`(?<=...)`)는 Safari 16.4 이상에서만 지원된다. esbuild는 이
// 정규식 리터럴을 낮추지 못해(down-level 불가) 대상 브라우저가 이를
// 지원하지 않으면 경고만 내고 그대로 둔다 — `npm run build` 확인 결과
// (2026-08-04) 이 저장소의 기본 build target에서는 경고가 뜨지 않았다.
// 다시 확인하려면 `npm run build` 출력에 lookbehind 관련 경고가 있는지만
// 보면 된다(PR #50 리뷰).

// 숫자/구두점만 남은 조각("1.", "-", "②" 등 번호 매기기 목록의 마커)인지
// 판별한다. 이런 조각은 단독 스텝으로 두면 안 된다 — 사용자가 "1."만 있는
// 화면을 보고 탭해야 다음 내용이 나오는 결함이 생긴다.
const STEP_FRAGMENT_ONLY = /^[\s\d.\-)②③④⑤①]+$/

// "한 가지 행동 지침" 문장을 판별한다. 화면 언어별로 어미가 다르므로
// 언어별 표를 둔다 — 한국어 어미만 보면 베트남어 화면에서 지침을 못 찾고,
// 그러면 행동 문장이 첫 화면에서 사라진다(PR #50 리뷰, 머지 전 필수).
//
// ⚠️ ko의 두 패턴을 합집합하면 apps/ai-engine의 guardrail._DIRECTIVE_PATTERN
// (하세요|하십시오|주세요|가세요|마세요)과 **문자 그대로 같다**. 둘을 나눈
// 것은 순서를 고르기 위한 것일 뿐, 판별 대상 집합을 바꾼 게 아니다 — 이
// 동일성이 두 곳의 "지침 문장" 정의를 일치시키는 불변식이므로, 어미를
// 추가·삭제할 때는 guardrail 쪽과 함께 바꿔야 한다.
//
// 고유어 명령형(신으세요·닫으세요·챙기세요)은 양쪽 모두 매칭하지 못한다.
// 프론트에서만 넓히면 위 불변식이 깨지므로 여기서는 넓히지 않는다 — 못
// 찾으면 원문 순서를 그대로 두는 폴백이 동작하고, 패턴 확장은 ai-engine과
// 함께 처리할 후속 과제다.
//
// vi: 명령·권유는 `hãy`, 금지는 `đừng` / `không được`. 단어 경계(\b)를 쓰지
// 않는 이유는 `đ`가 ASCII 단어 문자가 아니어서 공백 뒤 `đừng`에 경계가 잡히지
// 않기 때문이다. ko 패턴도 경계 없이 부분 문자열로 판별하므로 방식이 같다.
const STEP_DIRECTIVE_PATTERNS: Partial<
  Record<Language, { action: RegExp; prohibition: RegExp }>
> = {
  ko: { action: /(하세요|하십시오|주세요|가세요)/, prohibition: /마세요/ },
  vi: { action: /hãy/i, prohibition: /(đừng|không được)/i },
}

// 번호·불릿 마커로 시작하는 스텝인지. 목록은 순서 자체가 의미이므로 재배열
// 대상이 아니다 — "1. 창문을 닫으세요. 2. 밖으로 나가세요."에서 2번을 앞으로
// 끌어올리면 사용자가 읽는 순서가 원문과 뒤집힌다(PR #50 리뷰).
// STEP_FRAGMENT_ONLY는 "마커뿐인 조각"을 전체 일치로 보는 반면, 이쪽은
// "마커로 시작하는 문장"을 접두 일치로 본다 — 쓰임이 다르다.
const STEP_LIST_MARKER_PREFIX = /^\s*(?:\d+\s*[.)]|[-•·]|[①②③④⑤])/

// 문장 단위로 쪼갠다. 번호 매기기 목록의 마커 조각("1." 등)은 독립 스텝으로
// 두지 않고 인접 문장에 붙인다.
export function splitIntoSteps(text: string): string[] {
  const raw = text
    .split(STEP_SENTENCE_SPLIT)
    .map((s) => s.trim())
    .filter((s) => s.length > 0)

  const merged: string[] = []
  for (const piece of raw) {
    const last = merged[merged.length - 1]
    if (last !== undefined && STEP_FRAGMENT_ONLY.test(last)) {
      // 이전 조각이 마커뿐이었다면(마커 혼자만 있어도) 지금 조각을 그 뒤에
      // 붙인다 — 마커가 연달아 나오는 경우("1." "-")도 이 분기로 합쳐진다.
      merged[merged.length - 1] = `${last} ${piece}`
      continue
    }
    merged.push(piece)
  }

  // 텍스트 마지막이 마커뿐으로 끝나는 드문 경우 — 붙일 다음 문장이 없으니
  // 이전 문장에 붙인다.
  if (merged.length > 1) {
    const lastIdx = merged.length - 1
    const last = merged[lastIdx]
    const prev = merged[lastIdx - 1]
    if (last !== undefined && prev !== undefined && STEP_FRAGMENT_ONLY.test(last)) {
      merged[lastIdx - 1] = `${prev} ${last}`
      merged.pop()
    }
  }

  return merged
}

// 행동 지침 문장을 첫 스텝으로 끌어올린다. 원문 순서가 "상황 설명 → 행동
// 지침"이면 단계적 노출의 첫 화면에 행동 지침이 없어, 사용자가 왜
// 대피해야 하는지도 모른 채 화면을 넘겨야 정작 무엇을 해야 하는지 보게
// 된다 — Landing.tsx의 "푸시로 읽은 문장과 화면 문장이 같아야 한다"
// 불변식, ai-engine의 test_message_is_self_contained(ADR-0005, "본문만
// 읽어도 행동이 나와야 한다")와 충돌한다(PR #50 리뷰 블로킹 코멘트).
// 지침 문장을 찾아 맨 앞으로 옮기고 나머지는 원래 상대 순서를 유지한다.
// 지침 문장이 없으면(이미 첫 문장이거나, 매칭되는 어미가 없으면) 원문
// 순서를 그대로 둔다.
//
// lang 은 화면 언어다 — 지침 어미가 언어마다 다르므로 반드시 받아야 한다.
// 표에 없는 언어(zh·en)는 재배열하지 않고 원문 순서를 그대로 둔다: 그 언어의
// 어미를 판별할 근거가 없는 상태에서 순서를 바꾸면 아무 문장이나 첫 화면에
// 올릴 수 있다.
export function orderStepsDirectiveFirst(steps: string[], lang: Language): string[] {
  const patterns = STEP_DIRECTIVE_PATTERNS[lang]
  if (patterns === undefined) return steps

  // 번호 목록이면 재배열을 건너뛴다(STEP_LIST_MARKER_PREFIX 주석 참조).
  if (steps.some((s) => STEP_LIST_MARKER_PREFIX.test(s))) return steps

  const idx = findDirectiveIndex(steps, patterns)
  if (idx <= 0) return steps
  const directive = steps[idx]
  if (directive === undefined) return steps
  return [directive, ...steps.slice(0, idx), ...steps.slice(idx + 1)]
}

// 승격할 지침 문장의 인덱스. 금지문("…마세요", "đừng …")보다 **실제로 할
// 행동**을 먼저 찾는다 — 첫 화면이 "지하 주차장에 가지 마세요"로 시작하면
// 사용자가 처음 보는 문장이 "할 일"이 아니라 "하지 말 것"이 되고, 정작 할
// 행동은 탭 뒤에 남는다(PR #50 리뷰). 행동 문장이 없을 때에만 금지문을
// 승격한다 — 금지문뿐인 문안에서는 그것이 유일한 지침이다.
function findDirectiveIndex(
  steps: string[],
  patterns: { action: RegExp; prohibition: RegExp },
): number {
  const { action, prohibition } = patterns
  const actionIdx = steps.findIndex((s) => action.test(s) && !prohibition.test(s))
  if (actionIdx !== -1) return actionIdx
  return steps.findIndex((s) => action.test(s) || prohibition.test(s))
}
