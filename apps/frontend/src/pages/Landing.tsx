// Landing (/a?t=). Reads ?t= session token from the URL the FCM notification
// carries.
//
// SAFETY INVARIANTS:
//   - The frontend MUST NOT invent an action instruction when the session
//     failed to load. There is no retrieved 국민행동요령 source behind any
//     client-authored sentence (generation must be evidence-grounded). So on
//     failure we render only an honest status notice plus
//     a retry button — never a self-authored evacuation instruction.
//   - The frontend MUST NOT hardcode an 행정동 code. Without a profile we
//     do not know which dong this person lives in, and showing shelters for
//     a specific dong to an unknown user is wrong-location-during-disaster,
//     which is harm. When no profile is available we pass `undefined` to
//     ShelterGuide and it skips the search entirely.
//   - The screen MUST NOT be blank in any state: what failed and what the
//     user can do (retry) is always visible.
//
// NON-GOAL: this scope does not implement the offline-precache fallback
// path. The honest status notice here is the session-load failure path
// only.
//
// LANGUAGE (i18n): the UI language is read ONCE from Profile.language
// and threaded down to every child (ShelterGuide, ChatDock, SpeakButton).
// The resident never chooses a language — a guardian/employer/welfare
// center did during surrogate registration. We also mirror the language to
// <html lang="..."> at runtime so screen readers pronounce Vietnamese with
// a Vietnamese engine, not Korean rules. The plain-Korean substitution
// (EasyText / substituteAdminTerms) is Korean-only by design; on a
// Vietnamese screen we render the body verbatim and skip the substitution
// UI, which keeps the screen single-language Vietnamese.
//
// VISUAL TREATMENT: the layout is locked to a 402px mobile width (ADR-0004).
// A navy hero holds the alert context — rain/lightning canvas (AlertHeroFx),
// alert status line, and location card — so the resident immediately sees
// that this alert concerns them. The instruction body lives in a separate
// white card below, and failure / suppression / loading states share the
// same card form so the surface stays consistent.
//
// INVARIANT: the hero must NOT carry a client-authored instruction sentence.
// Every string in the hero is either a server field (message.title) or
// profile data (dongName, housing). The instruction appears only in the
// body card, rendered verbatim from message.body.
//
// The body render is owned entirely by EasyText. This component does not
// print the body paragraph itself — EasyText renders message.body as its
// children. The speak button also lives inside EasyText, so it is not
// duplicated here.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Housing, Language, Profile, SessionResponse } from '../api/types'
import { ShelterGuide } from '../components/ShelterGuide'
import { ChatDock } from '../components/ChatDock'
import { EasyText } from '../components/EasyText'
import { AlertHeroFx } from '../components/AlertHeroFx'
import { applyDocumentLanguage, t } from '../lib/i18n'
import { measureReadability } from '../lib/readability'
import { C, FONT_MONO, ICON, MOBILE_WIDTH, SHADOW_CARD } from '../lib/tokens'
import logoLight from '../assets/logo-mark-light.png'

// TODO(i18n): 주거 형태 배지 라벨. 사전에 `housing.*` 키가 없어서 한국어
// 화면에서만 배지를 띄운다. 번역 없는 한국어가 베트남어 화면에 섞이는 것보다
// 배지를 생략하는 편이 낫다 — 이 정보는 본문에 이미 문장으로 들어 있다.
const HOUSING_KO: Record<Housing, string> = {
  banjiha: '반지하',
  lowland: '저지대',
  normal: '일반',
}

// 위험 주거(반지하·저지대)만 붉은 배지로 강조한다. 'normal' 은 강조할 것이
// 없으므로 중성색이다.
function housingBadgeStyle(housing: Housing): React.CSSProperties {
  const risky = housing === 'banjiha' || housing === 'lowland'
  return {
    flex: 'none',
    borderRadius: '8px',
    padding: '5px 9px',
    fontSize: '12.5px',
    fontWeight: 700,
    background: risky ? 'rgba(214,41,62,.24)' : 'rgba(255,255,255,.16)',
    border: `1px solid ${risky ? 'rgba(214,41,62,.5)' : 'rgba(255,255,255,.3)'}`,
    color: risky ? '#FFB3BC' : 'rgba(255,255,255,.85)',
  }
}

const RETRY_BTN: React.CSSProperties = {
  width: '100%',
  minHeight: '56px',
  marginTop: '16px',
  padding: '16px',
  fontFamily: 'inherit',
  fontSize: '17px',
  fontWeight: 800,
  letterSpacing: '-.02em',
  color: C.white,
  background: C.alert,
  border: 'none',
  borderRadius: '14px',
  cursor: 'pointer',
}

const ALERT_CARD: React.CSSProperties = {
  background: C.white,
  border: `2px solid ${C.alertBorder}`,
  borderRadius: '18px',
  padding: '20px',
  boxShadow: SHADOW_CARD,
}

interface Props {
  token: string
}

export function Landing({ token }: Props) {
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [loading, setLoading] = useState<boolean>(true)
  const [error, setError] = useState<string | null>(null)
  // Bumped by the retry button so the load effect re-runs on demand. The
  // effect lists this as a dep, so a tap re-attempts getSession without
  // remounting the page.
  const [retryCount, setRetryCount] = useState<number>(0)
  // 글자 크기 확대 토글 상태. "크게 보기" 버튼은 EasyText 안에 있지만, 버튼이
  // 커져야 하는 것은 사용자가 실제로 읽는 본문(원문)이다. 본문은 EasyText 가
  // 렌더하며 large 값을 props 로 받아 같은 크기로 맞춘다. 클릭을
  // onToggleLarge 로 알려 상위 상태를 바꾼다. 영속 저장소에는 넣지 않는다.
  const [large, setLarge] = useState<boolean>(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api
      .getSession(token)
      .then((s) => {
        if (cancelled) return
        setSession(s)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (cancelled) return
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token, retryCount])

  const profile: Profile | null = session?.profile ?? null
  // The single UI language source. Read once here, threaded down. Unknown
  // / missing → ko. The contract lists ko, vi, zh, en; only vi has full UI
  // translations today. zh/en profiles resolve to Korean at the `t()` layer
  // (with a dev-mode console.warn so the fallback is not silent).
  const lang: Language = profile?.language ?? 'ko'

  // Mirror the active UI language to <html lang="..."> so screen readers
  // pick the right pronunciation engine. Idempotent. Runs on every render
  // but only writes when the value actually changes.
  useEffect(() => {
    applyDocumentLanguage(lang)
  }, [lang])

  // No hardcoded 행정동 fallback. When the profile is unavailable the
  // matching key is genuinely unknown and ShelterGuide must NOT search.
  const fallbackDongCode: string | undefined = profile?.dongCode
  const fallbackDongName = profile?.dongName ?? t('landing.addressUnknown', lang)

  const messageBody = session?.message.body ?? null
  const messageTitle = session?.message.title ?? null
  // 화면용 제목. message.title 은 "[세이버스] 서원동 호우경보" 처럼 알림 목록에서
  // 앱을 구분하려고 붙은 접두사까지 들어온다. 화면 안에서는 이 서비스이고, 바로
  // 위에 로고와 이름이 또 있어 세 번 반복된다. 표시할 때만 맨 앞 대괄호 묶음
  // 하나를 뗀다 — 알림으로 나가는 원본 제목은 그대로여야 한다. 맨 앞에 대괄호가
  // 없거나 떼고 났더니 빈 문자열이면 원본을 그대로 쓴다. 문자열 중간의 대괄호는
  // 건드리지 않는다.
  const displayTitle = (() => {
    if (messageTitle === null) return null
    const stripped = messageTitle.replace(/^\[[^\]]*\]\s*/, '')
    return stripped.length > 0 ? stripped : messageTitle
  })()
  // Memoized so dependent useMemos (sourceQuotes, readability) get a stable
  // reference across renders instead of a fresh []/array each render.
  const messageSources = useMemo(() => session?.message.sources ?? [], [session])
  const sessionFailed = error !== null && session === null

  // CONTRACT INVARIANT — evidence-grounded generation.
  //   AlertMessage.messageMode === 'grounded' with an empty sources array is
  //   a hallucination: the body claims to be backed by retrieved official
  //   text but carries no citation. Rendering that body as an action
  //   instruction would put an unevidenced evacuation sentence on screen.
  //   When the invariant is violated we hide the instruction body entirely
  //   and surface an explicit safety refusal instead. The title is kept (it
  //   is the alert headline, not an instruction); only the body — the part
  //   that tells the resident what to DO — is suppressed.
  const messageMode = session?.message.messageMode ?? null
  const bodyIsHallucination =
    session !== null && messageMode === 'grounded' && messageSources.length === 0

  // Readability is measured only when an actual grounded body exists. We
  // deliberately do NOT measure an invented fallback string — no
  // unevidenced instruction may be shown.
  //
  // The plain-Korean substitution applies to any screen rendering Korean
  // text. Korean is rendered not only for ko profiles but also for zh/en
  // (which fall back to Korean). Vietnamese bodies are skipped — the Korean
  // dictionary would not match and the metric would be meaningless.
  //
  // The result is bound to `readability` (NOT voided) so the metric is
  // observable: in dev builds we expose it on `window.__SAVERS_READABILITY__`
  // for runtime inspection; in production builds the binding still exists
  // (the useMemo ran) but no extra UI or cost is added. The measurement
  // itself already logs via console.info inside measureReadability.
  const sourceQuotes = useMemo(
    () => messageSources.map((s) => s.quote),
    [messageSources],
  )
  const readability = useMemo(
    () =>
      messageBody !== null && lang !== 'vi'
        ? measureReadability(messageBody, sourceQuotes)
        : null,
    [messageBody, sourceQuotes, lang],
  )
  // Dev-only exposure for runtime inspection. `import.meta.env.DEV` is a
  // Vite compile-time flag — this branch is stripped from production
  // bundles entirely, so there is zero runtime cost in prod.
  if (import.meta.env.DEV && readability !== null) {
    ;(window as unknown as Record<string, unknown>).__SAVERS_READABILITY__ =
      readability
  }

  const showNormalHeader =
    messageBody !== null && messageTitle !== null && !bodyIsHallucination

  return (
    <main
      style={{
        width: '100%',
        maxWidth: MOBILE_WIDTH,
        margin: '0 auto',
        minHeight: '100vh',
        background: C.bg,
        fontFamily: "'Pretendard', system-ui, sans-serif",
        // 한글은 단어 중간에서 끊지 않는다. 없으면 "저장하지 않습니 / 다."
        // 처럼 잘린다.
        wordBreak: 'keep-all',
        overflowWrap: 'break-word',
      }}
    >
      {/* ===================== 히어로 =====================
          상황을 알리는 영역이다. 여기에 «지침»은 오지 않는다 — 지침은 아래
          본문 카드에서 message.body 원문으로만 나온다(파일 상단 주석 참조).
          세션이 없을 때도 브랜드 락업은 렌더한다: 어떤 상태로 열려도 무슨
          화면인지는 보여야 한다. */}
      <div
        style={{
          background: C.navy,
          color: C.white,
          padding: '26px 22px 24px',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        <AlertHeroFx />

        {/* 붉은 발광. 경보 상태를 색으로 먼저 전달한다. 정적이다 —
            비·번개만 움직이고 이 면은 가만히 있다. */}
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            right: '-40px',
            top: '-54px',
            width: '190px',
            height: '190px',
            borderRadius: '50%',
            background: 'rgba(214,41,62,.36)',
            filter: 'blur(52px)',
            pointerEvents: 'none',
          }}
        />

        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            gap: '9px',
            marginBottom: messageTitle !== null ? '16px' : 0,
          }}
        >
          <img
            src={logoLight}
            alt=""
            style={{
              width: '24px',
              height: '24px',
              display: 'block',
              objectFit: 'contain',
              flex: 'none',
            }}
          />
          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: '13px',
              fontWeight: 600,
              letterSpacing: '.08em',
              color: 'rgba(255,255,255,.72)',
            }}
          >
            SAVERS
          </span>
        </div>

        {/* 경보 상태줄. message.title 원본은 "[세이버스] 서원동 호우경보" 처럼
            앱 구분 접두사까지 들어온다. 표시할 때만 맨 앞 대괄호 묶음을 뗀
            displayTitle 을 보여준다 — 알림으로 나가는 원본 제목은 그대로다. */}
        {messageTitle !== null && (
          <div
            style={{
              position: 'relative',
              display: 'flex',
              alignItems: 'flex-start',
              gap: '10px',
              marginBottom: profile !== null ? '18px' : 0,
            }}
          >
            <span
              aria-hidden="true"
              style={{
                position: 'relative',
                display: 'inline-flex',
                width: '10px',
                height: '10px',
                flex: 'none',
                marginTop: '7px',
              }}
            >
              <span
                style={{
                  position: 'absolute',
                  inset: 0,
                  borderRadius: '50%',
                  background: C.alert,
                  animation: 'savers-pulse 2.4s ease-out infinite',
                }}
              />
              <span
                style={{
                  position: 'relative',
                  width: '10px',
                  height: '10px',
                  borderRadius: '50%',
                  background: C.alert,
                }}
              />
            </span>
            <span
              style={{
                fontSize: '28px',
                fontWeight: 800,
                letterSpacing: '-.025em',
                lineHeight: 1.32,
                textWrap: 'pretty',
              }}
            >
              {displayTitle}
            </span>
          </div>
        )}

        {/* 위치 카드. dongName·housing 은 프로필 데이터다 — 클라이언트가
            지어낸 문장이 아니다. 사용자가 "이게 내 얘기인지" 확인하는
            지점이라 히어로에 둔다. */}
        {profile !== null && (
          <div
            style={{
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              background: 'rgba(255,255,255,.1)',
              border: '1px solid rgba(255,255,255,.2)',
              borderRadius: '14px',
              padding: '13px 15px',
            }}
          >
            <svg
              viewBox="0 0 24 24"
              style={{ ...ICON, width: 19, height: 19, color: C.mint }}
            >
              <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: '13px',
                  color: 'rgba(255,255,255,.62)',
                  marginBottom: '2px',
                }}
              >
                {t('landing.registeredHomeLabel', lang)}
              </div>
              <div style={{ fontSize: '17px', fontWeight: 700 }}>
                {fallbackDongName}
              </div>
            </div>
            {lang === 'ko' && (
              <span style={housingBadgeStyle(profile.housing)}>
                {HOUSING_KO[profile.housing]}
              </span>
            )}
          </div>
        )}
      </div>

      <div style={{ padding: '20px' }}>
        {showNormalHeader && (
          <header
            style={{
              background: C.white,
              borderRadius: '18px',
              boxShadow: SHADOW_CARD,
              marginBottom: '14px',
            }}
          >
            {/* 제목은 히어로에서 이미 크게 나왔다. 같은 정보가 작은 글씨로
                중복되므로 본문 카드 안에는 넣지 않는다. */}
            {/* 본문은 EasyText 가 유일하게 렌더한다. children 으로
                message.body 원문을 넘기고, 한국어 화면에서는 EasyText 가
                쉬운 우리말 치환본을 보여주며 베트남어 화면에서는 원문을
                그대로 보여준다. 읽어주기·크게 보기·원문 보기 버튼도 이
                카드 안에 있다. 푸시 알림에서 읽은 문장과 화면의 문장이
                같아야 한다. large 상태는 이 컴포넌트가 갖고 있으며, 본문
                글자 크기와 보조 버튼 상태를 같이 맞춘다. */}
            <EasyText
              sources={messageSources}
              large={large}
              onToggleLarge={() => setLarge((v) => !v)}
              lang={lang}
            >
              {messageBody}
            </EasyText>
          </header>
        )}

        {/* CONTRACT INVARIANT VIOLATION — the alert body claimed to be
            evidence-grounded (messageMode 'grounded') but arrived with no
            sources. That is a hallucination. We do NOT render the body as an
            instruction; we hide it and state plainly that the instruction was
            suppressed because its evidence was missing. The title (alert
            headline) is still shown so the resident knows an alert is active.
            Retry, shelter section, and chat remain available below. */}
        {messageBody !== null && messageTitle !== null && bodyIsHallucination && (
          <header style={{ ...ALERT_CARD, marginBottom: '14px' }}>
            <p
              style={{
                margin: '0 0 11px',
                fontSize: '20px',
                fontWeight: 800,
                color: C.navy,
                letterSpacing: '-.02em',
                lineHeight: 1.45,
                textWrap: 'pretty',
              }}
            >
              {t('alert.bodySuppressedTitle', lang)}
            </p>
            <p
              style={{
                margin: 0,
                fontSize: '17px',
                lineHeight: 1.62,
                color: C.body,
                textWrap: 'pretty',
              }}
            >
              {t('alert.bodySuppressed', lang)}
            </p>
            <button
              type="button"
              onClick={() => setRetryCount((n) => n + 1)}
              disabled={loading}
              style={{
                ...RETRY_BTN,
                background: loading ? C.body : C.alert,
                cursor: loading ? 'default' : 'pointer',
              }}
            >
              {loading ? t('alert.retrying', lang) : t('alert.retry', lang)}
            </button>
          </header>
        )}

        {sessionFailed && (
          // Honest failure notice. The frontend does NOT invent an action
          // instruction here — there is no retrieved source behind one. We
          // state that the personalized guidance could not be loaded and
          // offer a retry. The screen is never blank.
          <section role="alert" style={{ ...ALERT_CARD, marginBottom: '14px' }}>
            <p
              style={{
                margin: '0 0 11px',
                fontSize: '20px',
                fontWeight: 800,
                color: C.navy,
                letterSpacing: '-.02em',
                lineHeight: 1.45,
                textWrap: 'pretty',
              }}
            >
              {t('alert.loadFailed', lang)}
            </p>
            <div
              style={{
                background: C.bg,
                borderRadius: '12px',
                padding: '14px 15px',
                fontSize: '17px',
                lineHeight: 1.6,
                color: C.body,
                textWrap: 'pretty',
              }}
            >
              {t('alert.networkErrorPrefix', lang)} {error}
            </div>
            <button
              type="button"
              onClick={() => setRetryCount((n) => n + 1)}
              disabled={loading}
              style={{
                ...RETRY_BTN,
                background: loading ? C.body : C.alert,
                cursor: loading ? 'default' : 'pointer',
              }}
            >
              {loading ? t('alert.retrying', lang) : t('alert.retry', lang)}
            </button>
          </section>
        )}

        {loading && messageBody === null && (
          <p
            role="status"
            aria-live="polite"
            style={{
              margin: '0 0 14px',
              padding: '18px 16px',
              background: C.tealBg,
              borderRadius: '14px',
              fontSize: '17px',
              fontWeight: 700,
              color: C.tealText,
              letterSpacing: '-.015em',
              textAlign: 'center',
            }}
          >
            {t('alert.preparing', lang)}
          </p>
        )}

        {/* 등록 문서에서 만든 세션에서만 표시. 이 세션은 이름·행정동만 진짜
            이고 나머지 프로필 항목은 특기사항 없음의 중립 기본값이다. 데모
            페르소나 화면에는 이 표시가 나오지 않는다 — 그쪽은 프로필이 다
            있다. 담담한 한 줄이며, 경고나 사과가 아니다. */}
        {profile?.fromRegistration === true && !sessionFailed && (
          <p
            style={{
              margin: '0 0 14px',
              padding: '14px 15px',
              fontSize: '17px',
              lineHeight: 1.6,
              color: C.body,
              background: C.greyBg,
              borderRadius: '13px',
              textWrap: 'pretty',
            }}
          >
            {t('landing.registrationOnlyNotice', lang)}
          </p>
        )}

        <ShelterGuide
          profile={profile}
          lang={lang}
          sessionToken={token}
          fallbackDongCode={fallbackDongCode}
          dongName={fallbackDongName}
        />

        {/* The chat layer is mounted only when a real profile is available.
            A session that failed to load (unknown/expired token) yields
            profile === null, and ChatDock must not answer in that state —
            there is no retrieved evidence behind any client-authored
            instruction for an unidentified resident. The guard is on the
            loaded profile, not on the token string. */}
        {profile !== null && <ChatDock token={token} profile={profile} lang={lang} />}
      </div>
    </main>
  )
}
