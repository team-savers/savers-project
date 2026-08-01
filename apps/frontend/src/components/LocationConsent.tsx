// One-time, user-initiated location consent gate.
//
// This component is the ONLY place getCurrentPosition is invoked on the
// "prompt" branch (where the browser has no prior permission decision). The
// other branches (granted / denied / unsupported) are decided upstream in
// ShelterGuide via navigator.permissions.query — that path bypasses this
// component entirely. See ShelterGuide.tsx for the routing logic.
//
// State machine (3 user-facing states). Once a terminal state is reached
// the button is disabled and getCurrentPosition is never re-invoked:
//
//   idle          → user has not yet tapped; [내 위치 확인…] button shown
//   requesting    → getCurrentPosition in flight; spinner text shown
//   done | denied | unavailable → terminal; outcome text + button disabled
//
// HARD RULES (one-time, session-scoped location):
//   - getCurrentPosition is invoked AT MOST ONCE per component lifetime.
//     `startedRef` enforces this even under React StrictMode double-fire.
//   - The position is NEVER persisted — no client-side storage is written
//     at all. The resolved coord is passed to the parent via onResolved
//     and lives only in React state for this session.
//   - The registered 행정동 (dongCode) is always a valid fallback: on denial
//     or failure the parent runs a dongCode-only search, so the user still
//     gets shelter guidance. This component just reports the outcome.
//
// Accessibility:
//   - Primary action button ≥ 64px tall, foreground/background contrast
//     ratio ≥ 4.5:1 in every state (measured ratios in stateColors below).
//   - Each interactive control has an aria-label.
//   - Outcome guidance is a <ul> so screen readers announce item count.
//
// LANGUAGE (i18n): all human-readable strings go through the i18n
// dictionary (`t(key, lang)`). The lang is threaded from ShelterGuide via
// the `lang` prop.
//
// Visual treatment: the primary action button is red (#D6293E) — it is the
// single "press now" call to action on this screen and a disaster-response
// step, so it must read as distinct from the teal辅助 tools (speak, enlarge).
// A white location-pin icon sits on the left; in the idle state a soft ring
// pulses behind it (svPulse 2.8s) so the eye anchors on that one point while
// the rest of the surface stays calm. The button sits ABOVE the explanatory
// bullets because pressing it changes the list below — reading the bullets
// first and then reaching the button is the wrong order.
//
// The idle label is a two-line hierarchy: small "내 위치 확인하고" + large
// "가까운 대피소 찾기". Terminal states use meaning-coded colors: done=safe
// green, requesting=deep red, denied/unavailable=neutral grey.
//
// 광과민성: 펄스는 2.8초 주기(초당 0.36회)로 WCAG 2.3.1 상한(초당 3회)의
// 10분의 1이고, prefers-reduced-motion 에서는 index.css 전역 규칙이 멈춘다.

import { useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Language } from '../api/types'
import { t } from '../lib/i18n'
import { C, ICON } from '../lib/tokens'

// Single option passed to getCurrentPosition. maximumAge: 0 forbids a cached
// fix (we want a fresh one-shot read), timeout is 8s, no high-accuracy drain.
const GEO_OPTIONS: PositionOptions = {
  enableHighAccuracy: false,
  maximumAge: 0,
  timeout: 8000,
}

// The idle label is a two-line hierarchy on Korean screens: a small lead line
// "내 위치 확인하고" above a large main line "가까운 대피소 찾기". The
// dictionary's `consent.button.idle` is the two merged into one sentence, so
// we keep these constants separate instead of splitting the string. Adding
// `consent.button.idle.lead` / `.main` keys with vi translations would let us
// route through t() uniformly.
//
// 비한국어 화면은 지금도 t('consent.button.idle') 한 줄을 그대로 쓴다 —
// 번역 없는 한국어가 베트남어 화면에 섞이는 것보다 한 줄로 나오는 편이 낫다.
const IDLE_LEAD_KO = '내 위치 확인하고'
const IDLE_MAIN_KO = '가까운 대피소 찾기'

type ConsentState = 'idle' | 'requesting' | 'done' | 'denied' | 'unavailable'

interface Props {
  lang: Language
  // Invoked exactly once on a successful fix. The parent uses the coord to
  // refine the shelter search (coordinate basis). Never called on failure.
  onResolved: (lat: number, lng: number) => void
  // Invoked exactly once when the user denied, the API is unavailable, or the
  // request timed out. The parent falls back to a dongCode-only search. The
  // reason string is for display only; the parent does not branch on it.
  onFailed: (reason: 'denied' | 'unavailable' | 'timeout') => void
}

export function LocationConsent({ lang, onResolved, onFailed }: Props) {
  const [state, setState] = useState<ConsentState>('idle')
  // Guards getCurrentPosition against StrictMode double-fire and against the
  // user mashing the button while a request is in flight.
  const startedRef = useRef<boolean>(false)

  function handleRequest(): void {
    if (startedRef.current) {
      return
    }
    startedRef.current = true
    setState('requesting')

    // Non-browser or unsupported environment → terminal 'unavailable'.
    if (typeof navigator === 'undefined' || navigator.geolocation == null) {
      setState('unavailable')
      onFailed('unavailable')
      return
    }

    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setState('done')
        onResolved(pos.coords.latitude, pos.coords.longitude)
      },
      (err) => {
        // err.code: 1 = PERMISSION_DENIED, 2 = POSITION_UNAVAILABLE,
        // 3 = TIMEOUT. We collapse 2 and 3 into 'unavailable'/'timeout' but
        // both surface the same dongCode fallback to the user; only the
        // displayed reason differs.
        if (err.code === err.PERMISSION_DENIED) {
          setState('denied')
          onFailed('denied')
        } else if (err.code === err.TIMEOUT) {
          setState('unavailable')
          onFailed('timeout')
        } else {
          setState('unavailable')
          onFailed('unavailable')
        }
      },
      GEO_OPTIONS,
    )
  }

  const isIdle = state === 'idle'
  // 종료/진행 상태의 한 줄 라벨. idle 은 아래에서 2줄로 따로 그린다.
  const busyLabel =
    state === 'requesting'
      ? t('consent.button.requesting', lang)
      : state === 'done'
        ? t('consent.button.done', lang)
        : state === 'denied'
          ? t('consent.button.denied', lang)
          : t('consent.button.unavailable', lang)

  return (
    <section
      aria-label={t('consent.sectionLabel', lang)}
      style={{
        background: C.white,
        border: '1.5px solid #9DC9C4',
        borderRadius: '18px',
        padding: '19px',
      }}
    >
      {/* 버튼이 안내문 «위»에 있다. 누르면 아래 대피소 목록이 바뀌므로,
          설명을 다 읽은 뒤에 버튼이 나오는 것은 순서가 거꾸로다. */}
      <button
        type="button"
        onClick={handleRequest}
        disabled={!isIdle}
        aria-label={t('consent.aria.button', lang)}
        aria-busy={state === 'requesting'}
        style={primaryButton(state)}
      >
        {/* 면 안쪽 상하 그라디언트. 버튼이 평면 색 블록이 아니라 물체처럼
            보이게 한다. 정적이다 — 움직이지 않는다. */}
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            inset: 0,
            background:
              'linear-gradient(180deg,rgba(255,255,255,.2),rgba(255,255,255,0) 55%,rgba(0,0,0,.13))',
            pointerEvents: 'none',
          }}
        />

        {/* 위치핀 아이콘 + 퍼지는 링. 움직이는 것은 이 한 점뿐이다. */}
        <span
          aria-hidden="true"
          style={{
            position: 'relative',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '38px',
            height: '38px',
            flex: 'none',
          }}
        >
          {isIdle && (
            <span
              style={{
                position: 'absolute',
                inset: 0,
                borderRadius: '50%',
                background: 'rgba(255,255,255,.55)',
                animation: 'savers-pulse 2.8s ease-out infinite',
              }}
            />
          )}
          <span
            style={{
              position: 'relative',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '38px',
              height: '38px',
              borderRadius: '50%',
              background: 'rgba(255,255,255,.2)',
            }}
          >
            <svg
              viewBox="0 0 24 24"
              style={{
                ...ICON,
                width: 21,
                height: 21,
                strokeWidth: 2.2,
                color: C.white,
              }}
            >
              <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
              <circle cx="12" cy="10" r="3" />
            </svg>
          </span>
        </span>

        <span style={{ position: 'relative', flex: 1 }}>
          {isIdle ? (
            lang === 'ko' ? (
              // 2줄 위계. 한 줄로 흘리면 주 문구를 21px 로 키울 수 없다.
              <>
                <span
                  style={{
                    display: 'block',
                    fontSize: '15.5px',
                    fontWeight: 600,
                    letterSpacing: '-.015em',
                    lineHeight: 1.3,
                  }}
                >
                  {IDLE_LEAD_KO}
                </span>
                <span
                  style={{
                    display: 'block',
                    fontSize: '21px',
                    fontWeight: 800,
                    letterSpacing: '-.025em',
                    lineHeight: 1.3,
                    marginTop: '3px',
                  }}
                >
                  {IDLE_MAIN_KO}
                </span>
              </>
            ) : (
              // 비한국어 화면은 사전 문장을 한 줄로. 번역 없는 한국어가
              // 섞이는 것보다 낫다.
              <span
                style={{
                  display: 'block',
                  fontSize: '18px',
                  fontWeight: 800,
                  letterSpacing: '-.02em',
                  lineHeight: 1.35,
                }}
              >
                {t('consent.button.idle', lang)}
              </span>
            )
          ) : (
            <span
              style={{
                display: 'block',
                fontSize: '18px',
                fontWeight: 800,
                letterSpacing: '-.02em',
                lineHeight: 1.35,
              }}
            >
              {busyLabel}
            </span>
          )}
        </span>
      </button>

      <p
        style={{
          margin: '16px 0 11px',
          fontSize: '16px',
          fontWeight: 700,
          color: C.navy,
          letterSpacing: '-.015em',
          lineHeight: 1.55,
          textWrap: 'pretty',
        }}
      >
        {t('consent.intro', lang)}
      </p>

      {/* <ul> 유지 — 화면낭독기가 항목 수를 알려준다. 마커는 직접 그린다
          (기본 disc 는 16px 본문에서 시각적으로 너무 작다). */}
      <ul
        style={{
          listStyle: 'none',
          margin: 0,
          padding: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
        }}
      >
        {[
          t('consent.bullet.once', lang),
          t('consent.bullet.session', lang),
          t('consent.bullet.fallback', lang),
        ].map((line, i) => (
          <li
            key={i}
            style={{
              display: 'flex',
              gap: '9px',
              fontSize: '16px',
              lineHeight: 1.6,
              letterSpacing: '-.012em',
              color: C.body,
              textWrap: 'pretty',
            }}
          >
            <span aria-hidden="true" style={{ color: C.tealText, flex: 'none' }}>
              ·
            </span>
            <span>{line}</span>
          </li>
        ))}
      </ul>

      {state === 'denied' && (
        <p role="status" style={noteStyle}>
          {t('consent.note.denied', lang)}
        </p>
      )}
      {state === 'unavailable' && (
        <p role="status" style={noteStyle}>
          {t('consent.note.unavailable', lang)}
        </p>
      )}
    </section>
  )
}

// 상태별 배경과 흰 글자의 실측 대비. 전부 WCAG AA(4.5:1) 이상이다.
//   idle        #D6293E → 4.94:1   재난 대응 행동
//   requesting  #B3182B → 6.80:1   처리 중
//   done        #0B7A5C → 5.30:1   안전 확인 초록
//   denied      #4E5968 → 7.03:1   중성 회색 (실패지만 치명적이지 않다 —
//   unavailable                    등록 행정동 기준 안내가 계속된다)
//
// 종료 상태를 하나의 회색으로 뭉개지 않는 이유: 성공(done)과 실패(denied)가
// 같은 색이면 결과를 문구로만 판단해야 한다. 이 화면 사용자는 저시력일 수
// 있고 재난 상황에서 문구를 정독하지 않는다.
//
// 그림자는 정적이다. 이전에 후광이 숨쉬는(펄스) 버전이 있었는데, 아이콘
// 펄스와 겹쳐 면 전체가 들썩였다 — 검토에서 폐기됐다.
function stateColors(state: ConsentState): { bg: string; shadow: string } {
  if (state === 'done') {
    return { bg: C.safe, shadow: '0 8px 20px -10px rgba(11,122,92,.45)' }
  }
  if (state === 'requesting') {
    return { bg: C.alertDeep, shadow: '0 8px 20px -10px rgba(179,24,43,.4)' }
  }
  if (state === 'denied' || state === 'unavailable') {
    return { bg: C.body, shadow: 'none' }
  }
  return { bg: C.alert, shadow: '0 12px 28px -10px rgba(214,41,62,.5)' }
}

function primaryButton(state: ConsentState): CSSProperties {
  const disabled = state !== 'idle'
  const { bg, shadow } = stateColors(state)
  return {
    position: 'relative',
    overflow: 'hidden',
    width: '100%',
    minHeight: '64px',
    padding: '17px 18px',
    fontFamily: 'inherit',
    color: C.white,
    background: bg,
    border: 'none',
    borderRadius: '14px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    boxShadow: shadow,
    display: 'flex',
    alignItems: 'center',
    gap: '13px',
    textAlign: 'left',
  }
}

const noteStyle: CSSProperties = {
  margin: '14px 0 0',
  background: C.alertBg,
  border: `1px solid ${C.alertBorder}`,
  borderRadius: '12px',
  padding: '13px 15px',
  fontSize: '15.5px',
  lineHeight: 1.6,
  letterSpacing: '-.012em',
  color: C.alertText,
  textWrap: 'pretty',
}
