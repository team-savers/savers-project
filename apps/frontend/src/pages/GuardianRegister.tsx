// GuardianRegister (/r/{registrationToken}) — 보호자 최초 FCM 등록 화면.
//
// 2026-08-26 PM 확인: `/g/{guardianToken}`(pages/Guardian.tsx)과 이 화면은
// 역할이 다르다.
//   - 이 화면(`/r/{registrationToken}`) — 재난 발생 **전**, 보호자 휴대폰에
//     SAVERS 웹 푸시를 최초 1회 등록한다. `registrationToken`(장기·1인
//     고정)을 쓰고, `POST /v1/devices`(role: "guardian")를 호출한다.
//   - `/g/{guardianToken}` — 재난 발생 **후** 보호자가 상황을 확인하는
//     화면. `guardianToken`(세션마다 새로 발급, TTL 짧음)을 쓰고, 이미
//     구독된 기기를 갱신/재등록할 때만 `POST /v1/guardian/{token}/device`를
//     호출한다.
// 이 둘은 토큰 종류도, 호출하는 API도, localStorage 키도 겹치지 않는다 —
// lib/push.ts의 requestPushPermissionForGuardianRegistration(이 화면 전용)과
// requestPushPermissionForGuardian(Guardian.tsx 전용)을 각각 따로 쓴다.
//
// URL 경로는 계약이 스스로 명시한 것을 그대로 썼다 — 새로 지어낸 이름이
// 아니다: packages/contracts/openapi.yaml의 `GET /v1/registration/
// {registrationToken}` 설명이 "대리등록자가 `/r/{registrationToken}` 링크로
// 진입했을 때 호출한다"고 흐름도까지 적어 두고 있다. 이 화면은 그 흐름의
// role:"guardian" 버전이다(계약 자체는 role을 명시하지 않지만, 이번 작업
// 범위가 보호자 등록이라 이 화면은 그 값을 고정한다).
//
// 조사 결과(완료 보고 참고): 이 리포에 registrationToken 기반의 실제 FE
// 흐름은 이번까지 없었다. `/join`(pages/Join.tsx)은 겉보기엔 비슷해 보이지만
// `registrationToken`이 아니라 `userId`로 동작하는 별개의 Firestore 데모
// 채널이고(`api/client.ts`가 재수출하는 `getRegistrationTarget`은 그 채널의
// 함수라 이름만 같다 — 아래에서 반드시 `api.getRegistrationTarget`으로만
// 부른다), `/register`는 대리등록자가 피보호자 프로필을 새로 만드는
// 화면이라 이것과 목적이 다르다. 그래서 기존 route를 억지로 재사용하지
// 않고 이 화면을 새로 만들었다.
//
// 화면 구조는 최소로 유지한다 — 큰 설정 페이지가 아니라 [알림 받기] 버튼
// 하나짜리 화면이 성공/실패 상태만 오간다. 재난 UI(rain.png, 호우 경보
// 문구 등)는 여기 없다 — 평시 화면이기 때문이다.

import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { api, BackendApiError } from '../api/client'
import type { RegistrationTarget } from '../api/types'
import { requestPushPermissionForGuardianRegistration } from '../lib/push'
import { MOBILE_WIDTH, SHADOW_CARD, gutter, radius, touchTarget } from '../lib/tokens'

// Guardian 화면(pages/Guardian.tsx)과 같은 SAVERS 팔레트를 쓴다 — 같은
// "보호자 알림" 기능군이라 색을 맞추는 것이 자연스럽다. 다만 그 파일의
// `GC` 상수를 export해 가져오는 대신 여기 그대로 옮겨 적었다 — Guardian.tsx
// 3화면은 이번 작업에서 수정 대상이 아니므로, 그 파일에 손대지 않고(변경
// 이력에도 안 남기고) 이 화면을 완전히 독립적으로 둔다.
const GC = {
  primary: '#1877F2',
  primaryBg: 'rgba(24,119,242,.12)',
  accentText: '#8A5800',
  accentBg: 'rgba(248,160,8,.14)',
  bg: '#F8F9FA',
  surface: '#FFFFFF',
  surfaceSoft: '#EEF3F7',
  text: '#111111',
  textMuted: '#4B5563',
  line: '#D9E0E7',
} as const

const SHELL: CSSProperties = {
  width: '100%',
  maxWidth: MOBILE_WIDTH,
  margin: '0 auto',
  minHeight: '100vh',
  background: GC.bg,
  display: 'flex',
  flexDirection: 'column',
}

const card: CSSProperties = {
  background: GC.surface,
  border: `1px solid ${GC.line}`,
  borderRadius: `${radius.card}px`,
  padding: '20px 16px',
  boxShadow: SHADOW_CARD,
}

function guardianRegisterStorageKey(registrationToken: string): string {
  // "guardianRegister" — /g/{guardianToken}용 키(savers.guardianPush.
  // subscribed.*)와 이름부터 다르게 둔다. 절대 같은 네임스페이스를 쓰지
  // 않는다(PM 지침 7).
  return `savers.guardianRegister.subscribed.${registrationToken}`
}

function readLocallyRegistered(registrationToken: string): boolean {
  if (typeof window === 'undefined' || typeof Notification === 'undefined') {
    return false
  }
  let flag = false
  try {
    flag = window.localStorage.getItem(guardianRegisterStorageKey(registrationToken)) === '1'
  } catch {
    flag = false
  }
  return flag && Notification.permission === 'granted'
}

function writeLocallyRegistered(registrationToken: string, registered: boolean): void {
  if (typeof window === 'undefined') return
  try {
    if (registered) {
      window.localStorage.setItem(guardianRegisterStorageKey(registrationToken), '1')
    } else {
      window.localStorage.removeItem(guardianRegisterStorageKey(registrationToken))
    }
  } catch {
    // 최선 노력만 — API 호출은 이미 끝났으므로 false-success가 아니다.
  }
}

type TargetFetch =
  | { phase: 'loading' }
  | { phase: 'ready'; target: RegistrationTarget }
  | { phase: 'invalid' }

function useRegistrationTarget(registrationToken: string): TargetFetch {
  const [state, setState] = useState<TargetFetch>({ phase: 'loading' })
  useEffect(() => {
    if (registrationToken === '') {
      setState({ phase: 'invalid' })
      return
    }
    let cancelled = false
    setState({ phase: 'loading' })
    api
      .getRegistrationTarget(registrationToken)
      .then((target) => {
        if (!cancelled) setState({ phase: 'ready', target })
      })
      .catch(() => {
        if (!cancelled) setState({ phase: 'invalid' })
      })
    return () => {
      cancelled = true
    }
  }, [registrationToken])
  return state
}

type SubscribeState =
  | 'idle'
  | 'subscribing'
  | 'subscribed'
  | 'denied'
  | 'unavailable'
  | 'error'

interface Props {
  registrationToken: string
}

export function GuardianRegister({ registrationToken }: Props) {
  const targetFetch = useRegistrationTarget(registrationToken)
  const [state, setState] = useState<SubscribeState>(() =>
    readLocallyRegistered(registrationToken) ? 'subscribed' : 'idle',
  )
  const [notice, setNotice] = useState<string | null>(null)

  async function handleSubscribe(): Promise<void> {
    if (state === 'subscribing') return // 중복 클릭 방지
    setState('subscribing')
    setNotice(null)

    const result = await requestPushPermissionForGuardianRegistration(registrationToken)

    if (result.status === 'granted') {
      writeLocallyRegistered(registrationToken, true)
      setState('subscribed')
      return
    }
    if (result.status === 'denied') {
      setState('denied')
      return
    }
    if (result.status === 'unavailable') {
      setState('unavailable')
      return
    }
    // apiError — 성공 화면으로 절대 넘어가지 않는다. Guardian.tsx의
    // PushSubscribeSection과 같은 이유로 status까지 함께 확인한다 — 이
    // 백엔드는 "보호자 없음"과 FastAPI 자체 검증 실패(422) 모두 같은 code
    // (INVALID_REQUEST)를 쓰지만 status가 다르다(apps/backend/src/api/
    // routes/devices.py의 GuardianNotRegisteredError 분기는 400).
    const isNoGuardian =
      result.error instanceof BackendApiError &&
      result.error.status === 400 &&
      result.error.code === 'INVALID_REQUEST'
    setNotice(
      isNoGuardian
        ? '이 대상자에게는 등록된 보호자가 없어 등록할 수 없어요.'
        : '알림 등록에 실패했습니다. 잠시 뒤 다시 시도해 주세요.',
    )
    setState('error')
  }

  return (
    <div style={SHELL}>
      <div style={{ display: 'flex', justifyContent: 'center', padding: '20px 0 8px' }} role="img" aria-label="SAVERS 로고">
        <img src="/logo.png" alt="" style={{ height: '32px', display: 'block', objectFit: 'contain' }} />
      </div>

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: `${gutter}px` }}>
        {targetFetch.phase === 'invalid' && (
          <div style={{ ...card, textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: GC.text }}>
              등록 링크를 확인할 수 없어요
            </p>
            <p style={{ margin: '8px 0 0', fontSize: '14px', color: GC.textMuted, lineHeight: 1.5 }}>
              링크가 만료됐거나 잘못됐을 수 있어요. 전달받은 링크를 다시 확인해 주세요.
            </p>
          </div>
        )}

        {targetFetch.phase === 'loading' && (
          <div style={{ ...card, textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: '14px', color: GC.textMuted }}>확인하는 중...</p>
          </div>
        )}

        {targetFetch.phase === 'ready' && state === 'subscribed' && (
          <div style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <span
                aria-hidden="true"
                style={{
                  flex: 'none',
                  width: '28px',
                  height: '28px',
                  borderRadius: '50%',
                  background: GC.primary,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke={GC.surface} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 6 9 17l-5-5" />
                </svg>
              </span>
              <p style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: GC.text }}>알림 설정이 완료됐어요</p>
            </div>
            <p style={{ margin: '14px 0 0', fontSize: '14px', color: GC.textMuted, lineHeight: 1.6 }}>
              현재 진행 중인 재난 알림이 없습니다.
              <br />
              재난 상황이 발생하면 이 휴대폰으로 알려드릴게요.
            </p>
          </div>
        )}

        {targetFetch.phase === 'ready' && state !== 'subscribed' && (
          <div style={card}>
            {/* GET /v1/registration/{registrationToken}의 목적 그대로 —
                "지금 누구를 등록하려는가"를 실제 조회값으로 확인시킨다. */}
            <p style={{ margin: '0 0 10px', fontSize: '12.5px', fontWeight: 700, color: GC.accentText, background: GC.accentBg, display: 'inline-block', borderRadius: `${radius.chip}px`, padding: '3px 10px' }}>
              {targetFetch.target.wardName}님의 보호자로 등록
            </p>
            <p style={{ margin: 0, fontSize: '19px', fontWeight: 800, color: GC.text, lineHeight: 1.4 }}>
              이 휴대폰에서 보호자 알림을 받아보세요
            </p>
            <p style={{ margin: '8px 0 0', fontSize: '14px', color: GC.textMuted, lineHeight: 1.6 }}>
              재난 상황이 발생하면 가족의 상황을 이 휴대폰으로 알려드릴게요.
            </p>

            {(state === 'denied' || state === 'unavailable' || state === 'error') && (
              <p role="status" aria-live="polite" style={{ margin: '12px 0 0', fontSize: '13px', color: GC.textMuted, lineHeight: 1.5 }}>
                {state === 'denied'
                  ? '브라우저 알림 권한이 거부됐어요. 브라우저 설정에서 알림을 허용한 뒤 다시 시도해 주세요.'
                  : state === 'unavailable'
                    ? '알림을 준비하지 못했어요. 잠시 뒤 다시 시도해 주세요.'
                    : notice}
              </p>
            )}

            <button
              type="button"
              onClick={() => void handleSubscribe()}
              disabled={state === 'subscribing'}
              style={{
                width: '100%',
                marginTop: '16px',
                minHeight: `${touchTarget.ctaMin}px`,
                border: 'none',
                borderRadius: `${radius.button}px`,
                background: GC.primary,
                color: GC.surface,
                fontFamily: 'inherit',
                fontSize: '16px',
                fontWeight: 800,
                cursor: state === 'subscribing' ? 'default' : 'pointer',
                opacity: state === 'subscribing' ? 0.7 : 1,
              }}
            >
              {state === 'subscribing' ? '확인 중...' : state === 'idle' ? '알림 받기' : '다시 시도'}
            </button>
          </div>
        )}
      </main>
    </div>
  )
}
