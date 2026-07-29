// ChatDock — 하단 추가 질문 영역.
//
// 이 화면의 정체성이 걸린 부분이다: «근거 없으면 답하지 않는다». 답변이
// 없을 때 그럴듯한 문장을 만들어 채우면 재난 상황에서 사람을 잘못 움직인다.
// 그래서 거절(refusal)이 오류가 아니라 «정상 응답»으로 설계돼 있고, 거절
// 화면에도 반드시 다음 행동(대피소 다시 보기)이 붙는다.
//
// 계약 불변식:
//   - ChatResponse 의 sources 가 비어 있으면 answer 는 null 이어야 한다.
//     근거 없는 답변 문장은 계약이 금지하는 환각이다. 위반한 응답이 오면
//     ReplyView 가 답변을 «숨기고» no_evidence 거절 화면을 대신 렌더한다.
//   - refusalReason 분류는 서버가 소유한다. 프론트는 자연어를 분류하지
//     않는다 — 키 매핑만 한다(refusalNoticeKey).

import { useState } from 'react'
import type { CSSProperties, FormEvent } from 'react'
import { api } from '../api/client'
import type {
  ChatResponse,
  Language,
  Profile,
  RefusalReason,
} from '../api/types'
import { t } from '../lib/i18n'
import type { StringKey } from '../lib/i18n'
import { C, FONT_MONO, ICON, SHADOW_CARD } from '../lib/tokens'

interface Props {
  token: string
  // Profile drives the quick-reply button set (housing / care / livesAlone).
  // null = no profile resolved yet → only the two always-on buttons render.
  profile?: Profile | null
  lang: Language
}

// Maximum number of quick-reply buttons rendered. This is capped at 4
// (more is too much for an elderly-person screen). The buildQuickReplies
// array is sliced to this length before rendering.
const MAX_QUICK = 4

// Stable id on the ShelterGuide section. Kept as a constant here so the
// scroll target is documented at the call site and lives in exactly one
// place. The id is applied to the section in ShelterGuide.tsx.
const SHELTER_SECTION_ID = 'shelter-section'

interface QuickReply {
  id: string
  // Dictionary key — resolved to the active language at render time.
  textKey:
    | 'chat.quick.goOut'
    | 'chat.quick.pet'
    | 'chat.quick.upperFloor'
    | 'chat.quick.familyCare'
    | 'chat.quick.alone'
}

// Build the profile-conditioned quick-reply list. The two always-on entries
// come first; the conditional ones append in the documented order
// (housing → care → livesAlone fallback). livesAlone's fallback is only
// used when neither the housing nor the care condition applied.
//
// registration-built sessions (profile.fromRegistration === true) ship
// `stairsOk: true` as a neutral placeholder that was never confirmed by a
// guardian. The `upperFloor` quick reply ("위층으로 올라가도 되나요?")
// must NOT be offered to such a session — it would steer the resident
// toward a vertical-evacuation question when their stairs ability is
// genuinely unknown. The housing check (banjiha / lowland) is necessary
// but no longer sufficient; fromRegistration suppresses the button.
function buildQuickReplies(profile: Profile | null | undefined): QuickReply[] {
  const out: QuickReply[] = [
    { id: 'go-out', textKey: 'chat.quick.goOut' },
    { id: 'pet', textKey: 'chat.quick.pet' },
  ]

  const housing = profile?.housing
  const housingMatch = housing === 'banjiha' || housing === 'lowland'
  // Suppress the upperFloor reply for registration-built sessions where
  // stairs ability was never confirmed (fromRegistration === true).
  const fromRegistration = profile?.fromRegistration === true
  if (housingMatch && !fromRegistration) {
    out.push({ id: 'upper-floor', textKey: 'chat.quick.upperFloor' })
  }

  const careMatch = profile?.care != null && profile.care !== ''
  if (careMatch) {
    out.push({ id: 'family-care', textKey: 'chat.quick.familyCare' })
  }

  // livesAlone fallback ONLY when neither of the above applied.
  if (!housingMatch && !careMatch && profile?.livesAlone === true) {
    out.push({ id: 'alone', textKey: 'chat.quick.alone' })
  }

  return out.slice(0, MAX_QUICK)
}

// Scroll the shelter section into view. This is the entirety of the
// "대피소 다시 보기" action: it does NOT refetch any data — the section is
// already rendered above. Smooth scroll per spec.
function scrollShelterIntoView(): void {
  const el = document.getElementById(SHELTER_SECTION_ID)
  if (el !== null) {
    el.scrollIntoView({ behavior: 'smooth' })
  }
}

// Honest, state-specific notice copy for each refusal branch. The label is
// decided from the refusalReason ONLY (the server owns intent
// classification — the frontend never classifies natural language itself).
//
// Returns the dictionary key for the notice; the caller resolves it with
// `t()`.
function refusalNoticeKey(reason: RefusalReason | null | undefined): StringKey {
  if (reason === 'no_evidence') {
    return 'chat.refusal.no_evidence'
  }
  if (reason === 'out_of_scope') {
    return 'chat.refusal.out_of_scope'
  }
  if (reason === 'unsafe') {
    return 'chat.refusal.unsafe'
  }
  // Fallback for an absent or unrecognized refusalReason. We MUST NOT leak
  // the raw value to the screen; this neutral copy is the honest fallback.
  return 'chat.refusal.fallback'
}

// ---- 표현 상수 --------------------------------------------------------

const INPUT_STYLE: CSSProperties = {
  width: '100%',
  minHeight: '56px',
  border: `1.5px solid ${C.border}`,
  borderRadius: '12px',
  padding: '15px 16px',
  fontFamily: 'inherit',
  fontSize: '17px',
  color: C.navy,
  background: C.bg,
  outline: 'none',
}

// 빠른 질문 칩. 흰 카드 + 틸 테두리. 연파랑 배경 위 검은 글씨는 "이미
// 눌린 것"처럼 보인다.
const QUICK_STYLE: CSSProperties = {
  width: '100%',
  minHeight: '52px',
  padding: '14px 16px',
  fontFamily: 'inherit',
  fontSize: '16.5px',
  fontWeight: 700,
  letterSpacing: '-.015em',
  textAlign: 'left',
  color: C.navy,
  background: C.white,
  border: `1.5px solid #9DC9C4`,
  borderRadius: '13px',
  cursor: 'pointer',
}

export function ChatDock({ token, profile, lang }: Props) {
  const [open, setOpen] = useState<boolean>(false)
  const [question, setQuestion] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [reply, setReply] = useState<ChatResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  // Last sentence actually dispatched. The duplicate-send guard + the retry
  // button both read this: tapping the same quick-reply button again without
  // a different turn in between is a no-op, and the network-error 다시 시도
  // button re-sends exactly this sentence.
  const [lastSent, setLastSent] = useState<string | null>(null)
  // Set of sentences already asked in this session. Used to (a) hide a
  // quick-reply button once its answer has been received, and (b) decide
  // whether to render the re-show button vs. the "직접 입력해 주세요" hint
  // when the user taps [다른 것도 물어볼래요].
  const [asked, setAsked] = useState<Set<string>>(() => new Set())
  // Whether the quick-reply list is currently re-shown after being hidden
  // by a send. The first send hides the list; tapping
  // [다른 것도 물어볼래요] re-shows it (filtered by `asked`).
  const [showQuick, setShowQuick] = useState<boolean>(true)

  // Core dispatcher shared by the free-text form, the quick-reply buttons,
  // and the network-error retry button. All paths call postChat with a
  // `question` and surface the same reply bubble — no contract difference.
  // `allowDuplicate` is true for the free-text path (each typed submit is
  // an explicit user intent) and for the retry path (re-sending the same
  // sentence after a failure is intentional). Quick-reply taps pass false
  // so the same button tapped twice in a row does not spam the endpoint.
  async function sendQuestion(
    q: string,
    allowDuplicate: boolean,
  ): Promise<void> {
    if (q === '' || loading) return
    if (!allowDuplicate && lastSent === q) return
    setLoading(true)
    setError(null)
    setReply(null)
    setLastSent(q)
    // A dispatched sentence is recorded as asked. The reply bubble will
    // surface below; the quick-reply list is hidden until the user asks
    // to see it again (and then asked-sentences stay excluded).
    setAsked((prev) => {
      const next = new Set(prev)
      next.add(q)
      return next
    })
    setShowQuick(false)
    try {
      const r = await api.postChat({ token, question: q, locale: lang })
      setReply(r)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  async function ask(e: FormEvent): Promise<void> {
    e.preventDefault()
    const q = question.trim()
    if (q === '') return
    // Clear the field on dispatch so the user sees their sentence leave; the
    // reply will surface below. Free-text submits pass allowDuplicate=true.
    setQuestion('')
    await sendQuestion(q, true)
  }

  async function onQuickReply(text: string): Promise<void> {
    // Quick-reply taps go through allowDuplicate=false: the same button
    // tapped twice without a different turn in between is suppressed.
    await sendQuestion(text, false)
  }

  async function retryLast(): Promise<void> {
    // Re-send the last dispatched sentence after a network failure.
    // allowDuplicate=true so the retry fires even though lastSent already
    // equals the sentence.
    if (lastSent === null) return
    await sendQuestion(lastSent, true)
  }

  // The quick replies are filtered by `asked`: a sentence that has already
  // been answered is removed (the same answer twice has no value). When the
  // filtered set is empty, the re-show button is replaced with a hint.
  const allQuick = buildQuickReplies(profile)
  // Resolve each quick-reply key to the active language for display AND
  // for the asked-set filter (the asked set stores resolved strings so the
  // filter comparison is language-consistent within a single session).
  const resolvedQuick = allQuick.map((qr) => ({
    id: qr.id,
    text: t(qr.textKey, lang),
  }))
  const availableQuick = resolvedQuick.filter((qr) => !asked.has(qr.text))
  const allAsked = availableQuick.length === 0

  // Decide which follow-up affordance the reply area renders. The button is
  // NEVER inert — each label maps to a concrete handler (re-show / scroll).
  //
  // CONTRACT INVARIANT — ChatResponse: when `sources` is empty, `answer`
  // MUST be null. An answer text with no sources is a hallucination the
  // contract forbids; ReplyView suppresses the answer in that case and
  // renders the no-evidence refusal instead. The follow-up logic therefore
  // treats a contract-violating reply the same as an explicit no_evidence
  // refusal so the resident still gets a real next action (reshelter).
  const replyViolatesInvariant =
    reply !== null && reply.answer !== null && reply.sources.length === 0
  const effectiveAnswerNull =
    reply !== null && (reply.answer === null || replyViolatesInvariant)
  const showReshelterAfterReply =
    effectiveAnswerNull &&
    (reply === null ||
      reply.refusalReason === 'no_evidence' ||
      reply.refusalReason === 'unsafe' ||
      reply.refusalReason === null ||
      reply.refusalReason === undefined ||
      replyViolatesInvariant)
  const showAskMoreAfterReply =
    reply !== null &&
    !replyViolatesInvariant &&
    (reply.answer !== null || reply.refusalReason === 'out_of_scope')

  return (
    <section
      aria-label={t('chat.sectionLabel', lang)}
      style={{
        borderTop: `1.5px solid ${C.border}`,
        paddingTop: '16px',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls="chat-panel"
        style={{
          width: '100%',
          minHeight: '56px',
          padding: '16px',
          fontFamily: 'inherit',
          fontSize: '17px',
          fontWeight: 800,
          letterSpacing: '-.015em',
          background: open ? C.navy : C.white,
          color: open ? C.white : C.tealText,
          border: `2px solid ${open ? C.navy : C.tealText}`,
          borderRadius: '14px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: '9px',
        }}
      >
        <svg viewBox="0 0 24 24" style={{ ...ICON, width: 20, height: 20 }}>
          <path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z" />
        </svg>
        {open ? t('chat.toggle.open', lang) : t('chat.toggle.closed', lang)}
      </button>

      {open && (
        <div id="chat-panel" style={{ marginTop: '13px' }}>
          {/* While a request is in flight, surface an honest in-progress
              status with role="status" so assistive tech announces it. The
              screen is never blank — this paragraph is rendered alongside
              the (disabled) input. */}
          {loading && (
            <p
              role="status"
              aria-live="polite"
              style={{
                margin: '0 0 11px',
                padding: '14px 16px',
                background: C.tealBg,
                borderRadius: '13px',
                fontSize: '16px',
                fontWeight: 700,
                color: C.tealText,
                letterSpacing: '-.015em',
              }}
            >
              {t('chat.status.searching', lang)}
            </p>
          )}

          {/* Quick reply buttons — vertical column, ≥52px tap target. Only
              rendered when showQuick is true (the first send hides them;
              [다른 것도 물어볼래요] re-shows them, filtered by `asked`).
              When every sentence has been asked, the list is replaced by a
              "직접 입력해 주세요" hint so the re-show button is never a dead
              control. */}
          {showQuick && !allAsked && (
            <div
              aria-label={t('chat.quickListLabel', lang)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '8px',
                marginBottom: '13px',
              }}
            >
              {availableQuick.map((qr) => {
                const isDuplicate = qr.text === lastSent
                const disabled = loading && isDuplicate
                return (
                  <button
                    key={qr.id}
                    type="button"
                    onClick={() => onQuickReply(qr.text)}
                    disabled={disabled}
                    style={{
                      ...QUICK_STYLE,
                      opacity: disabled ? 0.55 : 1,
                      cursor: disabled ? 'progress' : 'pointer',
                    }}
                  >
                    {qr.text}
                  </button>
                )
              })}
            </div>
          )}
          {showQuick && allAsked && (
            <p
              style={{
                margin: '0 0 13px',
                padding: '14px 16px',
                background: C.greyBg,
                borderRadius: '13px',
                fontSize: '16px',
                lineHeight: 1.62,
                color: C.body,
                textWrap: 'pretty',
              }}
            >
              {t('chat.quickExhausted', lang)}
            </p>
          )}

          <form
            onSubmit={ask}
            style={{
              background: C.white,
              borderRadius: '16px',
              padding: '17px 18px',
              boxShadow: SHADOW_CARD,
            }}
          >
            <label
              htmlFor="chat-input"
              style={{
                display: 'block',
                fontSize: '16px',
                fontWeight: 700,
                color: C.navy,
                letterSpacing: '-.015em',
                lineHeight: 1.55,
                marginBottom: '10px',
                textWrap: 'pretty',
              }}
            >
              {t('chat.inputLabel', lang)}
            </label>
            <input
              id="chat-input"
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={t('chat.placeholder', lang)}
              style={INPUT_STYLE}
            />
            <button
              type="submit"
              disabled={loading || question.trim() === ''}
              style={{
                width: '100%',
                minHeight: '52px',
                marginTop: '10px',
                padding: '14px',
                fontFamily: 'inherit',
                fontSize: '16.5px',
                fontWeight: 800,
                letterSpacing: '-.015em',
                color: C.white,
                background:
                  loading || question.trim() === '' ? C.tertiary : C.tealText,
                border: 'none',
                borderRadius: '12px',
                cursor:
                  loading || question.trim() === '' ? 'not-allowed' : 'pointer',
              }}
            >
              {loading ? t('chat.sendBusy', lang) : t('chat.send', lang)}
            </button>
          </form>

          {/* Network failure: role="alert" notice + a 다시 시도 button that
              re-sends the last dispatched sentence. Never leaves the user
              staring at a stuck screen. */}
          {error !== null && (
            <div
              role="alert"
              style={{
                marginTop: '13px',
                padding: '17px 18px',
                background: C.white,
                border: `2px solid ${C.alertBorder}`,
                borderRadius: '16px',
                boxShadow: SHADOW_CARD,
              }}
            >
              <p
                style={{
                  margin: '0 0 13px',
                  fontSize: '16px',
                  lineHeight: 1.6,
                  color: C.alertText,
                  textWrap: 'pretty',
                }}
              >
                {t('chat.errorPrefix', lang)} {error}
              </p>
              <button
                type="button"
                onClick={retryLast}
                disabled={loading || lastSent === null}
                style={{
                  width: '100%',
                  minHeight: '52px',
                  padding: '14px',
                  fontFamily: 'inherit',
                  fontSize: '16.5px',
                  fontWeight: 800,
                  letterSpacing: '-.015em',
                  color: C.white,
                  background:
                    loading || lastSent === null ? C.tertiary : C.alert,
                  border: 'none',
                  borderRadius: '12px',
                  cursor:
                    loading || lastSent === null ? 'not-allowed' : 'pointer',
                }}
              >
                {t('chat.retry', lang)}
              </button>
            </div>
          )}

          {reply !== null && (
            <ReplyView
              reply={reply}
              lang={lang}
              violatesInvariant={replyViolatesInvariant}
              onAskMore={() => setShowQuick(true)}
              onReshelter={scrollShelterIntoView}
              showReshelter={showReshelterAfterReply}
              showAskMore={showAskMoreAfterReply}
            />
          )}
        </div>
      )}
    </section>
  )
}

interface ReplyViewProps {
  reply: ChatResponse
  lang: Language
  // True when the reply carries an answer text but NO sources — a contract
  // violation (ChatResponse requires answer === null when sources is empty).
  // When true, ReplyView suppresses the answer text entirely and renders the
  // no-evidence refusal notice instead, so a hallucinated answer never reaches
  // the screen.
  violatesInvariant: boolean
  // Re-show the quick-reply list (filtered by `asked` in the parent).
  onAskMore: () => void
  // Scroll the shelter section into view.
  onReshelter: () => void
  // Whether the [대피소 다시 보기] button should render.
  showReshelter: boolean
  // Whether the [다른 것도 물어볼래요] button should render.
  showAskMore: boolean
}

function ReplyView({
  reply,
  lang,
  violatesInvariant,
  onAskMore,
  onReshelter,
  showReshelter,
  showAskMore,
}: ReplyViewProps) {
  // No-answer branch. The notice copy is decided by refusalNoticeKey(); we
  // never invent an answer text here (evidence-grounded generation).
  //
  // A contract-violating reply (answer !== null but sources empty) is treated
  // identically to an explicit null-answer reply here — the answer text is
  // suppressed and the no-evidence refusal notice is shown instead. The
  // refusalReason of a violating reply may be null/unset (the server did not
  // know it was violating), so we coerce to 'no_evidence' for the notice.
  if (reply.answer === null || violatesInvariant) {
    const reason: RefusalReason | null | undefined = violatesInvariant
      ? reply.refusalReason ?? 'no_evidence'
      : reply.refusalReason
    const notice = t(refusalNoticeKey(reason), lang)
    return (
      // 거절은 «실패가 아니다». 근거 없으면 답하지 않는다는 약속이 지켜진
      // 결과다. 그래서 회색 빈칸이 아니라 네이비 테두리 카드로 또렷하게
      // 그린다 — 사용자가 "고장났나"가 아니라 "답을 안 주는 이유가 있구나"로
      // 읽어야 한다.
      <div
        role="status"
        style={{
          marginTop: '13px',
          padding: '20px',
          background: C.white,
          border: `2px solid ${C.navy}`,
          borderRadius: '18px',
          boxShadow: SHADOW_CARD,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            gap: '10px',
            marginBottom: '12px',
          }}
        >
          <svg
            viewBox="0 0 24 24"
            style={{
              ...ICON,
              width: 20,
              height: 20,
              color: C.navy,
              marginTop: '3px',
            }}
          >
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
            <path d="M12 8v4M12 16h.01" />
          </svg>
          <p
            style={{
              margin: 0,
              fontSize: '18px',
              fontWeight: 800,
              color: C.navy,
              letterSpacing: '-.02em',
              lineHeight: 1.45,
              textWrap: 'pretty',
            }}
          >
            {notice}
          </p>
        </div>
        <p
          style={{
            margin: 0,
            fontSize: '16.5px',
            lineHeight: 1.62,
            color: C.body,
            textWrap: 'pretty',
          }}
        >
          {t('chat.refusal.emergency', lang)}
        </p>
        <FollowupButtons
          lang={lang}
          showReshelter={showReshelter}
          showAskMore={showAskMore}
          onReshelter={onReshelter}
          onAskMore={onAskMore}
        />
      </div>
    )
  }
  // Answer branch. Render the answer + sources, then the follow-up affordance.
  return (
    <div
      role="status"
      style={{
        marginTop: '13px',
        padding: '20px',
        background: C.tealBg,
        borderRadius: '18px',
      }}
    >
      <p
        style={{
          margin: 0,
          fontSize: '17px',
          fontWeight: 600,
          lineHeight: 1.64,
          letterSpacing: '-.015em',
          color: C.navy,
          textWrap: 'pretty',
        }}
      >
        {reply.answer}
      </p>
      {/* 근거 인용. 각주가 아니라 이 서비스의 핵심이다 — 좌측 틸 바가
          "우리가 쓴 문장이 아니라 인용"이라는 표시다. */}
      {reply.sources.length > 0 && (
        <ul
          style={{
            listStyle: 'none',
            margin: '14px 0 0',
            padding: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: '9px',
          }}
        >
          {reply.sources.map((s, i) => (
            <li
              key={i}
              style={{
                background: C.white,
                borderLeft: `4px solid ${C.tealText}`,
                borderRadius: '0 12px 12px 0',
                padding: '13px 15px',
              }}
            >
              <div
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: '11.5px',
                  fontWeight: 600,
                  letterSpacing: '.06em',
                  color: C.tealText,
                  marginBottom: '6px',
                }}
              >
                {s.title}
              </div>
              <div
                style={{
                  fontSize: '15.5px',
                  lineHeight: 1.6,
                  letterSpacing: '-.012em',
                  color: C.navy,
                  textWrap: 'pretty',
                }}
              >
                {s.quote}
              </div>
            </li>
          ))}
        </ul>
      )}
      <FollowupButtons
        lang={lang}
        showReshelter={showReshelter}
        showAskMore={showAskMore}
        onReshelter={onReshelter}
        onAskMore={onAskMore}
      />
    </div>
  )
}

interface FollowupButtonsProps {
  lang: Language
  showReshelter: boolean
  showAskMore: boolean
  onReshelter: () => void
  onAskMore: () => void
}

// Follow-up buttons rendered under a reply. Each button is a real action —
// there are no inert buttons. Min height 52px, keyboard-operable <button>.
//
// 위계: 대피소 다시 보기는 «안전 행동»이라 초록 채움이고, 다른 것도
// 물어볼래요는 탐색이라 틸 아우트라인이다. 거절 화면에서는 전자만 나오는데,
// 그때 그 버튼이 화면의 유일한 다음 행동이다.
function FollowupButtons({
  lang,
  showReshelter,
  showAskMore,
  onReshelter,
  onAskMore,
}: FollowupButtonsProps) {
  if (!showReshelter && !showAskMore) return null
  const base: CSSProperties = {
    width: '100%',
    minHeight: '52px',
    padding: '14px 16px',
    fontFamily: 'inherit',
    fontSize: '16.5px',
    fontWeight: 800,
    letterSpacing: '-.015em',
    borderRadius: '13px',
    cursor: 'pointer',
  }
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '9px',
        marginTop: '16px',
      }}
    >
      {showReshelter && (
        <button
          type="button"
          onClick={onReshelter}
          style={{
            ...base,
            background: C.safe,
            color: C.white,
            border: `2px solid ${C.safe}`,
          }}
        >
          {t('chat.followup.reshelter', lang)}
        </button>
      )}
      {showAskMore && (
        <button
          type="button"
          onClick={onAskMore}
          style={{
            ...base,
            background: C.white,
            color: C.tealText,
            border: `2px solid ${C.tealText}`,
          }}
        >
          {t('chat.followup.askMore', lang)}
        </button>
      )}
    </div>
  )
}
