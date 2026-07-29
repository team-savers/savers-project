// /join?u=<userId> — ward-phone onboarding screen.
//
// OPENED BY: the QR code that /ops shows after a surrogate registration.
// The welfare worker's tablet registers the ward; the ward's OWN phone opens
// this URL via QR scan. This screen confirms the ward's identity (name only)
// and attaches the ward's FCM token to the cross-device store so the operator
// tablet can dispatch to it.
//
// WHO SEES THIS: the ward themselves (어르신 / foreign worker). So: large
// text, one button, plain Korean, no jargon. Touch targets >= 48px.
//
// VERIFICATION: name only. Phone, address, disability status, and the FCM
// device token are NEVER shown here — minimal-collection principle. The ward
// sees only "○○○님, 맞으신가요?" This screen returns only the three fields the
// contract's RegistrationTarget carries (wardName, dongName, registeredBy).
//
// LIMITATION (honest): the underlying store adapter downloads the whole
// stored document over the wire to this device and projects to the three
// fields in JavaScript before rendering. So nothing sensitive is DISPLAYED,
// but phone and deviceToken do reach this device inside the SDK response
// payload and stay in SDK memory until garbage-collected. Closing that gap
// needs a backend endpoint that reads three fields server-side; out of
// scope for the interim browser-direct bridge.
//
// DENIAL PATH: browsers only let you ask for notification permission once.
// After a denial the prompt never re-appears, so the user MUST re-enable it
// in browser settings. That recovery instruction is rendered plainly.
//
// CONFLICT PATH: if a DIFFERENT device already holds the FCM slot for this
// user, the ward is asked — in plain Korean — whether to replace it. Only
// [바꾸기] triggers the overwrite (requestPushPermission with replace:true);
// [그만두기] leaves the existing device in place. No silent swap.
//
// TIMEOUT PATH: if the cross-device store is unreachable, the attach attempt
// rejects after the deadline and the screen shows what failed with a retry
// button — never an infinite spinner.
//
// STORE DISABLED (default, no VITE_FS_*): getRegistrationTarget returns null, so
// the screen shows "등록 정보를 찾을 수 없습니다." This is correct — without
// the store there is no cross-device record to look up, and the single-device
// demo flow doesn't use /join.
//
// LANGUAGE (i18n): the RegistrationTarget contract returns only wardName,
// dongName, and registeredBy — there is no language field. The Join screen
// is therefore rendered in Korean (lang = 'ko') by default. All strings are
// still routed through the dictionary so adding a language probe later is a
// one-line change (swap the lang source).
//
// VISUAL TREATMENT: the palette comes from SAVERS tokens (lib/tokens.ts).
// Every phase carries the shared brand hero so it is always clear which
// screen the user is on. Phase-tinted status cards code the outcome by
// meaning: done=safe green, kept=teal (no change), conflict=warn yellow,
// denied/not_found/error=alert red. Touch targets stay at or above 48px
// (primary CTA 64px). The iOS home-screen notice reads as a calm "one
// more step" (teal) rather than a warning.

import { useEffect, useState } from 'react'
import type { CSSProperties, ReactElement } from 'react'
import { getRegistrationTarget } from '../api/client'
import { requestPushPermissionForJoin } from '../lib/push'
import { t } from '../lib/i18n'
import { C, FONT_MONO, ICON, MOBILE_WIDTH, SHADOW_CARD, SHADOW_CTA_TEAL } from '../lib/tokens'
import logoLight from '../assets/logo-mark-light.png'

// The Join screen has no language signal in the registration contract. Korean
// is the correct default: the ward's own phone opens this URL, and without a
// Profile to read .language from we must not guess. When the contract grows
// a language field on RegistrationTarget, this becomes that field's value.
const lang = 'ko' as const

// TODO(i18n): 아래 세 문구는 사전(lib/i18n.ts)에 아직 없는 신규 UI 문자열이다.
// `join.brand.*` 키로 옮기고 t() 로 바꾸는 것이 맞다. 지금 하드코딩해 두는
// 이유는 이 변경이 스타일 전용이고, 사전 수정은 vi 번역까지 함께 채워야
// 하기 때문이다.
const BRAND_TITLE = '세이버스 알림 등록'
const BRAND_SUB = 'QR로 열린 화면입니다'
const PRIVACY_FOOTER =
  '이 화면에서는 이름만 확인합니다. 연락처와 주소는 보여드리지 않아요.'

interface Props {
  userId: string
}

// iOS Safari only supports web push (and thus notification permission) when
// the page has been added to the home screen and is running as a standalone
// PWA. In plain Safari the permission prompt never appears, so a registration
// that looks successful here silently never delivers alerts. This detects that
// broken state so we can show the home-screen instruction BEFORE the user
// taps the accept button.
//
// Detection strategy — err on the side of false positives (showing the notice
// where it does not apply costs only a glance; missing it on a real iPhone
// costs the user all disaster alerts):
//   1. Standalone check first — if already running as a home-screen app, the
//      notice is pointless. iOS Safari exposes navigator.standalone; the
//      display-mode CSS media query covers Chrome/Android and PWA builders.
//   2. iOS-family signal from the UA string (iPhone / iPad / iPod).
//   3. iPadOS masquerade: since iOS 13, iPad reports a Macintosh UA. Catch
//      this by also treating "Macintosh" + a touch screen as iOS-class.
//   4. maxTouchPoints as the touch supporting signal — more reliable than
//      ontouchstart on browsers that have deprecated it.
function isStandaloneHomeApp(): boolean {
  if (typeof navigator === 'undefined') return false
  // iOS Safari sets navigator.standalone only when launched from the icon.
  if ((navigator as Navigator & { standalone?: boolean }).standalone === true) {
    return true
  }
  if (typeof window === 'undefined') return false
  // Standard PWA display-mode check (works for non-iOS browsers too).
  return window.matchMedia('(display-mode: standalone)').matches
}

function needsIosHomeScreenHint(): boolean {
  if (typeof navigator === 'undefined') return false
  if (isStandaloneHomeApp()) return false
  const ua = navigator.userAgent || ''
  const platform = navigator.platform || ''
  const touchPoints =
    (navigator as Navigator & { maxTouchPoints?: number }).maxTouchPoints ?? 0
  // Explicit iOS device strings.
  const isIosUa =
    /iPad|iPhone|iPod/i.test(ua) || /iPad|iPhone|iPod/i.test(platform)
  // iPadOS desktop masquerade: a Mac UA on a multitouch device is treated as
  // iOS-class. Real macOS desktops rarely report maxTouchPoints > 0.
  const isIpadosMasquerade =
    /Macintosh/i.test(ua) && !isIosUa && touchPoints > 0
  return isIosUa || isIpadosMasquerade
}

// `error` phase carries an `origin` so the retry button knows WHAT to retry.
// A lookup failure must re-run the lookup (bumping retryCount re-runs the
// lookup effect). An attach failure (handleAccept) may legitimately retry
// the attach. Without this distinction, a failed lookup retried via
// handleAccept, which skipped the lookup and registered a nameless
// half-document.
type Phase =
  | { kind: 'loading' }
  | { kind: 'not_found' }
  | { kind: 'confirm'; name: string }
  | { kind: 'working' }
  | { kind: 'conflict'; name: string }
  | { kind: 'done' }
  | { kind: 'kept' }
  | { kind: 'denied' }
  | {
      kind: 'error'
      msg: string
      retryable: boolean
      origin: 'lookup' | 'attach'
    }

// ---------------------------------------------------------------------------
// 표현 조각
// ---------------------------------------------------------------------------

const SHELL: CSSProperties = {
  width: '100%',
  maxWidth: MOBILE_WIDTH,
  margin: '0 auto',
  minHeight: '100vh',
  background: C.bg,
  fontFamily: "'Pretendard', system-ui, sans-serif",
  // 한글은 단어 중간에서 끊지 않는다. 없으면 "저장하지 않습니 / 다." 처럼
  // 잘린다.
  wordBreak: 'keep-all',
  overflowWrap: 'break-word',
}

const BODY: CSSProperties = { padding: '22px 20px 30px' }

const PRIMARY_BTN: CSSProperties = {
  width: '100%',
  minHeight: '64px',
  background: C.tealText,
  color: C.white,
  border: 'none',
  borderRadius: '16px',
  padding: '19px',
  fontFamily: 'inherit',
  fontSize: '21px',
  fontWeight: 800,
  letterSpacing: '-.02em',
  cursor: 'pointer',
  boxShadow: SHADOW_CTA_TEAL,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: '10px',
}

// 대비되는 2차 버튼. [그만두기]가 실행 버튼으로 오인되지 않아야 한다.
const SECONDARY_BTN: CSSProperties = {
  width: '100%',
  minHeight: '62px',
  background: C.white,
  color: C.body,
  border: `2px solid ${C.border}`,
  borderRadius: '16px',
  padding: '18px',
  fontFamily: 'inherit',
  fontSize: '19px',
  fontWeight: 700,
  letterSpacing: '-.02em',
  cursor: 'pointer',
}

/** 브랜드 히어로. 모든 phase 위에 공통으로 얹힌다. */
function Hero(): ReactElement {
  return (
    <div
      style={{
        background: C.navy,
        color: C.white,
        padding: '26px 22px 24px',
        borderRadius: '0 0 26px 26px',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          right: '-56px',
          top: '-70px',
          width: '200px',
          height: '200px',
          borderRadius: '50%',
          background: C.mint,
          opacity: 0.16,
          filter: 'blur(46px)',
        }}
      />
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '11px',
          position: 'relative',
        }}
      >
        <img
          src={logoLight}
          alt=""
          style={{
            width: '42px',
            height: '42px',
            display: 'block',
            objectFit: 'contain',
            flex: 'none',
          }}
        />
        <div>
          <div
            style={{
              fontSize: '19px',
              fontWeight: 800,
              letterSpacing: '-.015em',
            }}
          >
            {BRAND_TITLE}
          </div>
          <div
            style={{ fontSize: '14px', color: C.mintPale, marginTop: '2px' }}
          >
            {BRAND_SUB}
          </div>
        </div>
      </div>
    </div>
  )
}

/** 화면 하단 최소수집 고지. 모든 phase 에 공통. */
function PrivacyFooter(): ReactElement {
  return (
    <div
      style={{
        fontSize: '14.5px',
        lineHeight: 1.7,
        color: C.tertiary,
        marginTop: '22px',
        textAlign: 'center',
        textWrap: 'pretty',
      }}
    >
      {PRIVACY_FOOTER}
    </div>
  )
}

type Tone = 'alert' | 'warn' | 'safe' | 'info'

const TONE: Record<Tone, { bg: string; border: string; icon: string }> = {
  alert: { bg: C.white, border: C.alertBorder, icon: C.alertDeep },
  warn: { bg: C.white, border: C.warn, icon: '#8A6300' },
  safe: { bg: C.white, border: C.safe, icon: C.safe },
  info: { bg: C.white, border: C.border, icon: C.tealText },
}

/** 제목 + 아이콘을 가진 상태 카드. */
function StateCard({
  tone,
  role,
  icon,
  title,
  children,
}: {
  tone: Tone
  role: 'alert' | 'status'
  icon: ReactElement
  title: string
  children?: React.ReactNode
}): ReactElement {
  const s = TONE[tone]
  return (
    <section
      role={role}
      style={{
        background: s.bg,
        border: `2px solid ${s.border}`,
        borderRadius: '20px',
        padding: '24px 22px',
        boxShadow: SHADOW_CARD,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '14px',
        }}
      >
        <span style={{ color: s.icon, display: 'flex', flex: 'none' }}>
          {icon}
        </span>
        <h1
          style={{
            fontSize: '20px',
            fontWeight: 800,
            color: C.navy,
            letterSpacing: '-.02em',
            lineHeight: 1.4,
            margin: 0,
            textWrap: 'pretty',
          }}
        >
          {title}
        </h1>
      </div>
      {children}
    </section>
  )
}

const P: CSSProperties = {
  fontSize: '17px',
  lineHeight: 1.62,
  color: C.body,
  margin: '0 0 12px',
  textWrap: 'pretty',
}

const P_LAST: CSSProperties = { ...P, margin: 0 }

/** 스피너. @keyframes 는 index.css 에 있어야 한다 (README 참조). */
function Spinner(): ReactElement {
  return (
    <div
      aria-hidden="true"
      style={{
        width: '52px',
        height: '52px',
        borderRadius: '50%',
        border: `5px solid ${C.tealBg}`,
        borderTopColor: C.tealText,
        margin: '0 auto 22px',
        animation: 'savers-spin 1s linear infinite',
      }}
    />
  )
}

// ---------------------------------------------------------------------------

export function Join({ userId }: Props): ReactElement {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading' })
  // Bumped by the lookup-failure retry button so the lookup effect re-runs
  // on demand without remounting. Mirrors the Landing retry pattern.
  const [retryCount, setRetryCount] = useState<number>(0)

  // Initial lookup — returns ONLY the RegistrationTarget fields (wardName,
  // dongName, registeredBy) to this screen. The store adapter downloads the
  // whole stored document over the wire and projects to those three fields
  // in JavaScript, so the full document (which carries phone and
  // deviceToken) does reach this device inside the SDK response even though
  // only the three fields are rendered.
  // ?u= empty OR record missing → friendly "not found" notice. Store
  // disabled → also not found (no cross-device record exists in that mode).
  useEffect(() => {
    let cancelled = false
    setPhase({ kind: 'loading' })
    if (userId === '') {
      setPhase({ kind: 'not_found' })
      return
    }
    getRegistrationTarget(userId)
      .then((rec) => {
        if (cancelled) return
        if (rec === null) {
          setPhase({ kind: 'not_found' })
          return
        }
        setPhase({ kind: 'confirm', name: rec.wardName })
      })
      .catch((e) => {
        if (cancelled) return
        setPhase({
          kind: 'error',
          msg: e instanceof Error ? e.message : String(e),
          retryable: true,
          origin: 'lookup',
        })
      })
    return () => {
      cancelled = true
    }
  }, [userId, retryCount])

  // Attempt to attach this phone's FCM token. On conflict, switch to the
  // confirm-replace phase; the user must explicitly tap [바꾸기] before we
  // retry with replace:true. `forceReplace` is only true from that button.
  async function handleAccept(forceReplace: boolean): Promise<void> {
    setPhase({ kind: 'working' })
    try {
      const result = await requestPushPermissionForJoin(
        userId,
        forceReplace ? { replace: true } : undefined,
      )
      if (result.status === 'granted') {
        setPhase({ kind: 'done' })
        return
      }
      if (result.status === 'denied') {
        setPhase({ kind: 'denied' })
        return
      }
      if (result.status === 'conflict') {
        // Preserve the name we already showed so the confirm-replace screen
        // stays personalized. Re-fetch is unnecessary — name doesn't change
        // between attach attempts.
        setPhase((prev) => ({
          kind: 'conflict',
          name:
            prev.kind === 'confirm' || prev.kind === 'conflict'
              ? prev.name
              : '',
        }))
        return
      }
      // result.status === 'unavailable' — transient (no VAPID/SW, or the
      // permission prompt was dismissed without a choice). Retryable.
      setPhase({
        kind: 'error',
        msg: t('join.error.unavailable', lang),
        retryable: true,
        origin: 'attach',
      })
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      // The store-side attach runs under a 10s deadline. A timeout surfaces
      // as a thrown error with "timed out" in the message — offer a retry so
      // the ward is never stuck on a dead spinner.
      const isTimeout = /timed out|timeout/i.test(msg)
      setPhase({
        kind: 'error',
        msg: isTimeout ? t('join.error.timeout', lang) : msg,
        retryable: true,
        origin: 'attach',
      })
    }
  }

  // Retry handler for the error screen. The action depends on WHICH step
  // failed, recorded in `phase.origin`:
  //   - 'lookup' → re-run the lookup (bump retryCount, which re-fires the
  //     lookup effect). This is the fix for the defect where a failed lookup
  //     retried via the attach path, skipping the lookup and creating a
  //     nameless half-document. The lookup path never requests permission,
  //     so the user-gesture requirement for Notification.requestPermission
  //     is preserved on the attach path.
  //   - 'attach' → re-invoke the attach step (handleAccept). Safe because the
  //     lookup already succeeded and the confirm name is in phase.
  function handleRetry(): void {
    if (phase.kind !== 'error') return
    if (phase.origin === 'lookup') {
      setRetryCount((n) => n + 1)
      return
    }
    void handleAccept(false)
  }

  // ─── loading / working ───────────────────────────────────────────────
  if (phase.kind === 'loading' || phase.kind === 'working') {
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <section
            role="status"
            aria-live="polite"
            style={{
              background: C.white,
              borderRadius: '20px',
              padding: '44px 24px',
              boxShadow: SHADOW_CARD,
              textAlign: 'center',
            }}
          >
            <Spinner />
            <p
              style={{
                fontSize: '19px',
                fontWeight: 700,
                color: C.navy,
                letterSpacing: '-.02em',
                lineHeight: 1.5,
                margin: 0,
              }}
            >
              {t(phase.kind === 'loading' ? 'join.loading' : 'join.working', lang)}
            </p>
          </section>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── not_found ───────────────────────────────────────────────────────
  if (phase.kind === 'not_found') {
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <StateCard
            tone="alert"
            role="alert"
            title={t('join.notFound.title', lang)}
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON, width: 22, height: 22 }}>
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3M11 8v3M11 14h.01" />
              </svg>
            }
          >
            <p style={P_LAST}>{t('join.notFound.body', lang)}</p>
          </StateCard>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── confirm ─────────────────────────────────────────────────────────
  if (phase.kind === 'confirm') {
    // Computed once for this render. The hint is intentionally shown ABOVE
    // the accept button so it is read before the user taps [알림 받기] and
    // discovers — too late — that the permission prompt never appears in
    // plain Safari. When this branch is false (Android, desktop, or iOS
    // already running as a home-screen app) the screen is the plain flow.
    const showIosHint = needsIosHomeScreenHint()
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <h1
            style={{
              fontSize: '24px',
              fontWeight: 800,
              color: C.navy,
              letterSpacing: '-.025em',
              lineHeight: 1.4,
              margin: '0 0 18px',
              textWrap: 'pretty',
            }}
          >
            {t('join.confirm.title', lang)}
          </h1>

          {/* 이름만. 연락처·주소·장애 여부는 오지 않는다. QR을 주운 사람이
              볼 수 있기 때문이다. */}
          <section
            style={{
              background: C.white,
              border: `2px solid ${C.tealText}`,
              borderRadius: '20px',
              padding: '26px 22px',
              boxShadow: SHADOW_CARD,
              marginBottom: '14px',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                fontSize: '15px',
                fontWeight: 700,
                color: C.tealText,
                marginBottom: '11px',
              }}
            >
              {t('join.confirm.askAccept', lang)}
            </div>
            <p
              style={{
                margin: 0,
                fontSize: '30px',
                fontWeight: 800,
                color: C.navy,
                letterSpacing: '-.025em',
                lineHeight: 1.35,
              }}
            >
              {t('join.confirm.nameConfirm', lang, { name: phase.name })}
            </p>
          </section>

          {showIosHint ? (
            // 경고가 아니라 준비 안내다. 연틸이라 "한 단계 더"로 읽힌다.
            // 문구는 옆에 있는 대리등록자를 향한다 — 무설치 원칙(어르신이
            // 직접 설치하지 않는다)을 지키기 위해.
            <section
              style={{
                background: C.tealBg,
                borderRadius: '18px',
                padding: '19px 20px',
                marginBottom: '14px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '10px',
                  marginBottom: '11px',
                }}
              >
                <svg
                  viewBox="0 0 24 24"
                  style={{
                    ...ICON,
                    width: 20,
                    height: 20,
                    color: C.tealText,
                    marginTop: '2px',
                  }}
                >
                  <path d="M12 3v12M8 7l4-4 4 4" />
                  <rect x="4" y="15" width="16" height="6" rx="2" />
                </svg>
                <div
                  style={{
                    fontSize: '17px',
                    fontWeight: 800,
                    color: C.navy,
                    letterSpacing: '-.02em',
                    lineHeight: 1.45,
                    textWrap: 'pretty',
                  }}
                >
                  {t('join.iosNotice.title', lang)}
                </div>
              </div>
              <p
                style={{
                  fontSize: '16px',
                  lineHeight: 1.62,
                  color: C.tealDeep,
                  margin: '0 0 13px',
                  textWrap: 'pretty',
                }}
              >
                {t('join.iosNotice.body', lang)}
              </p>
              <div
                style={{
                  background: C.white,
                  borderRadius: '12px',
                  padding: '14px 15px',
                  marginBottom: '11px',
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: '16.5px',
                    fontWeight: 700,
                    color: C.navy,
                    lineHeight: 1.5,
                    textWrap: 'pretty',
                  }}
                >
                  {t('join.iosNotice.steps', lang)}
                </p>
              </div>
              <p
                style={{
                  margin: 0,
                  fontSize: '15.5px',
                  lineHeight: 1.55,
                  color: C.body,
                  textWrap: 'pretty',
                }}
              >
                {t('join.iosNotice.helper', lang)}
              </p>
            </section>
          ) : null}

          <button
            type="button"
            style={PRIMARY_BTN}
            onClick={() => void handleAccept(false)}
          >
            <svg viewBox="0 0 24 24" style={{ ...ICON, width: 22, height: 22 }}>
              <path d="M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
              <path d="M13.7 21a2 2 0 0 1-3.4 0" />
            </svg>
            {t('join.confirm.acceptButton', lang)}
          </button>

          <p
            style={{
              fontSize: '16px',
              lineHeight: 1.62,
              color: C.body,
              margin: '15px 0 0',
              textAlign: 'center',
              textWrap: 'pretty',
            }}
          >
            {t('join.confirm.explainer', lang)}
          </p>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── conflict ────────────────────────────────────────────────────────
  if (phase.kind === 'conflict') {
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <div style={{ marginBottom: '16px' }}>
            <StateCard
              tone="warn"
              role="alert"
              title={t('join.conflict.title', lang)}
              icon={
                <svg viewBox="0 0 24 24" style={{ ...ICON, width: 22, height: 22 }}>
                  <path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z" />
                  <path d="M12 9v4M12 17h.01" />
                </svg>
              }
            >
              <p
                style={{
                  fontSize: '19px',
                  fontWeight: 700,
                  color: C.navy,
                  lineHeight: 1.5,
                  margin: '0 0 12px',
                  textWrap: 'pretty',
                }}
              >
                {t('join.conflict.askReplace', lang)}
              </p>
              <div
                style={{
                  background: C.warnBg,
                  borderRadius: '12px',
                  padding: '14px 15px',
                }}
              >
                <p
                  style={{
                    margin: 0,
                    fontSize: '16px',
                    lineHeight: 1.62,
                    color: C.warnText,
                    textWrap: 'pretty',
                  }}
                >
                  {t('join.conflict.replaceDetail', lang)}
                </p>
              </div>
            </StateCard>
          </div>

          {/* Only [바꾸기] triggers the overwrite (replace:true). [그만두기]
              leaves the existing device in place — no silent swap either way. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '11px' }}>
            <button
              type="button"
              style={{ ...PRIMARY_BTN, minHeight: '62px', fontSize: '20px' }}
              onClick={() => void handleAccept(true)}
            >
              {t('join.conflict.replaceButton', lang)}
            </button>
            <button
              type="button"
              style={SECONDARY_BTN}
              onClick={() => setPhase({ kind: 'kept' })}
            >
              {t('join.conflict.keepButton', lang)}
            </button>
          </div>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── done ────────────────────────────────────────────────────────────
  if (phase.kind === 'done') {
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <section role="status" style={{ textAlign: 'center', padding: '20px 0 0' }}>
            <div
              style={{
                width: '96px',
                height: '96px',
                borderRadius: '50%',
                background: C.safe,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 26px',
                boxShadow: '0 14px 32px -14px rgba(11,122,92,.6)',
              }}
            >
              <svg
                viewBox="0 0 24 24"
                style={{
                  ...ICON,
                  width: 46,
                  height: 46,
                  strokeWidth: 2.6,
                  color: C.white,
                }}
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
            </div>
            <h1
              style={{
                fontSize: '27px',
                fontWeight: 800,
                color: C.navy,
                letterSpacing: '-.025em',
                lineHeight: 1.38,
                margin: '0 0 14px',
                textWrap: 'pretty',
              }}
            >
              {t('join.done.title', lang)}
            </h1>
            <p
              style={{
                fontSize: '18px',
                lineHeight: 1.65,
                color: C.body,
                margin: 0,
                textWrap: 'pretty',
              }}
            >
              {t('join.done.body', lang)}
            </p>
          </section>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── kept ────────────────────────────────────────────────────────────
  if (phase.kind === 'kept') {
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <section role="status" style={{ textAlign: 'center', padding: '20px 0 0' }}>
            <div
              style={{
                width: '88px',
                height: '88px',
                borderRadius: '50%',
                background: C.tealBg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                margin: '0 auto 24px',
              }}
            >
              <svg
                viewBox="0 0 24 24"
                style={{
                  ...ICON,
                  width: 40,
                  height: 40,
                  strokeWidth: 2.2,
                  color: C.tealText,
                }}
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
                <path d="m9 11 2 2 4-4" />
              </svg>
            </div>
            <h1
              style={{
                fontSize: '24px',
                fontWeight: 800,
                color: C.navy,
                letterSpacing: '-.025em',
                lineHeight: 1.4,
                margin: '0 0 14px',
                textWrap: 'pretty',
              }}
            >
              {t('join.kept.title', lang)}
            </h1>
            <p
              style={{
                fontSize: '18px',
                lineHeight: 1.65,
                color: C.body,
                margin: 0,
                textWrap: 'pretty',
              }}
            >
              {t('join.kept.body', lang)}
            </p>
          </section>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── denied ──────────────────────────────────────────────────────────
  if (phase.kind === 'denied') {
    return (
      <main style={SHELL}>
        <Hero />
        <div style={BODY}>
          <StateCard
            tone="alert"
            role="alert"
            title={t('join.denied.title', lang)}
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON, width: 22, height: 22 }}>
                <path d="M18 8a6 6 0 0 0-9.3-5" />
                <path d="M6.3 6.3A6 6 0 0 0 6 8c0 7-3 9-3 9h14" />
                <path d="M13.7 21a2 2 0 0 1-3.4 0" />
                <path d="m2 2 20 20" />
              </svg>
            }
          >
            <p style={{ ...P, marginBottom: '16px' }}>
              {t('join.denied.body', lang)}
            </p>
            {/* 한 번 거부하면 이 화면에서 되돌릴 수 없다. 설정 경로가 유일한
                탈출구이므로 안드로이드·아이폰 둘 다 적는다. */}
            <div
              style={{
                background: C.bg,
                borderRadius: '12px',
                padding: '15px 16px',
                marginBottom: '14px',
              }}
            >
              <div
                style={{
                  fontFamily: FONT_MONO,
                  fontSize: '12px',
                  fontWeight: 600,
                  letterSpacing: '.1em',
                  color: C.tealText,
                  marginBottom: '10px',
                }}
              >
                SETTINGS
              </div>
              <p
                style={{
                  margin: '0 0 10px',
                  fontSize: '15.5px',
                  lineHeight: 1.55,
                  color: C.body,
                  textWrap: 'pretty',
                }}
              >
                {t('join.denied.recoveryAndroid', lang)}
              </p>
              <p
                style={{
                  margin: 0,
                  fontSize: '15.5px',
                  lineHeight: 1.55,
                  color: C.body,
                  textWrap: 'pretty',
                }}
              >
                {t('join.denied.recoveryIos', lang)}
              </p>
            </div>
            <p
              style={{
                margin: 0,
                fontSize: '16.5px',
                fontWeight: 700,
                color: C.navy,
                lineHeight: 1.55,
                textWrap: 'pretty',
              }}
            >
              {t('join.denied.rescan', lang)}
            </p>
          </StateCard>
          <PrivacyFooter />
        </div>
      </main>
    )
  }

  // ─── error ───────────────────────────────────────────────────────────
  return (
    <main style={SHELL}>
      <Hero />
      <div style={BODY}>
        <div style={{ marginBottom: '14px' }}>
          <StateCard
            tone="alert"
            role="alert"
            title={t('join.error.title', lang)}
            icon={
              <svg viewBox="0 0 24 24" style={{ ...ICON, width: 22, height: 22 }}>
                <circle cx="12" cy="12" r="9" />
                <path d="M12 8v4M12 16h.01" />
              </svg>
            }
          >
            <div
              style={{
                background: C.bg,
                borderRadius: '12px',
                padding: '15px 16px',
              }}
            >
              <p
                style={{
                  margin: 0,
                  fontSize: '16.5px',
                  lineHeight: 1.6,
                  color: C.body,
                  textWrap: 'pretty',
                }}
              >
                {phase.msg}
              </p>
            </div>
          </StateCard>
        </div>
        {phase.retryable ? (
          // The retry button delegates to handleRetry, which re-runs the
          // failed step based on phase.origin (lookup re-fetch vs attach
          // re-attempt). A failed lookup no longer jumps to registration.
          <button
            type="button"
            style={{ ...PRIMARY_BTN, minHeight: '62px', fontSize: '20px' }}
            onClick={handleRetry}
          >
            {t('join.error.retry', lang)}
          </button>
        ) : null}
        <PrivacyFooter />
      </div>
    </main>
  )
}
