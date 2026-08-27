// Guardian (/guardian) — 보호자 모바일 화면, mock 기반 UI 미리보기 경로.
//
// STATUS: `GuardianStatus` 계약(api/types.ts)은 이미 존재한다. 이 파일이
// mock인 이유는 계약이 없어서가 아니라, 실제 `/g/{guardianToken}` API
// 연동(fetch + 세션 토큰 라우팅)이 아직 이 PR의 스코프가 아니기 때문이다
// — 그래서 이 파일은 계약 *타입*(GuardianStatus/SafetyStatus)은 가져다
// 쓰면서도 ../api/* 의 호출부는 import하지 않고, mocks/guardianStatus.ts의
// 고정 목데이터만 읽는다. `/guardian`은 그 연동 전까지의 UI 미리보기
// 경로이고, 실제 계약 경로인 `/g/{token}`은 이 PR의 스코프가 아니다
// (App.tsx 상단 라우트 표 참고). mock UI도 계약이 정의하는 의미
// (safetyStatus는 'unknown'만 존재, openedAt/lastResponse는 안전 신호가
// 아님 등)를 그대로 따른다 — mock이라고 계약과 다른 의미를 만들지 않는다.
//
// 실제 `/g/{token}` 연동 시 교체할 지점(정확히 이 두 곳):
//   1. App.tsx 의 `/guardian` 라우트를 `/g/{token}` 으로 바꾸고 URL에서
//      토큰을 읽어 이 컴포넌트에 넘긴다(Landing.tsx 의 LandingView 패턴
//      참고 — `?t=` 파싱).
//   2. 아래 `GUARDIAN_MOCK.status`(GuardianStatus 타입) 대신 기존
//      `api.getGuardianStatus(token)` seam(api/types.ts `ApiClient`)의
//      실제 응답을 fetch해 Screen 컴포넌트들에 넘긴다. Screen 컴포넌트의
//      props 타입은 이미 GuardianStatus/QaTurn 계약 타입을 그대로 쓰고
//      있으므로, 실제 fetch 결과를 같은 타입으로 바인딩하는 작업이다.
//   3. AiScreen의 추천 질문 답변은 지금 mocks/guardianStatus.ts에 고정된
//      QaTurn을 실제 `/v1/guardian/{token}/ask` 호출로 바꾼다 —
//      ChatDock.tsx가 쓰는 「근거 없으면 답하지 않는다」 원칙을 그대로
//      따를 것.
//
// 화면 3개는 하위 라우트가 아니라 한 페이지 안의 로컬 state(screen)로
// 전환한다 — 실제 연동 전 지금 단계에서 라우팅을 새로 만들 이유가 없다.

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import './GuardianPushControl.css'
import rain from '../assets/rain.webp'
import type {
  GuardianAnswer,
  GuardianQuestionId,
  GuardianStatus,
  SafetyStatus,
} from '../api/types'
import { api, BackendApiError } from '../api/client'
import { requestPushPermissionForGuardian } from '../lib/push'
import {
  readGuardianFcmToken,
  removeGuardianFcmToken,
  migrateLegacyGuardianFcmToken,
  writeGuardianFcmToken,
} from '../lib/guardianPushStorage'
import { C, ICON, MOBILE_WIDTH, SHADOW_CARD, gutter, radius, touchTarget } from '../lib/tokens'
import { GUARDIAN_MOCK, PERSONA_IMAGE, type QaTurn } from '../mocks/guardianStatus'

// ---------------------------------------------------------------------------
// GUARDIAN COLOR PALETTE — this screen's own brand hue set (the design
// review asked for it on the guardian screens specifically; it does not
// replace the app-wide navy/teal palette other screens still use). The hex
// literals themselves live exactly once, in `C.guardian*` (lib/tokens.ts) —
// `GC` below is only a short local alias so the rest of this file can keep
// reading `GC.primary` etc. instead of the longer `C.guardian…` names; it
// introduces no new colour values of its own.
//
// *Text / *Bg variants are NOT extra colors — each is a tint or a darker
// shade of the ONE base hex the design gave us (primary/accent/danger),
// added only so text and light backgrounds keep AA contrast. This mirrors
// the exact pairing tokens.ts already uses for its own palette (teal vs
// tealText, warn vs warnText — see lib/tokens.ts's contrast-rules comment)
// — same technique, just scoped to this screen's three brand hues instead
// of the global ones.
// ---------------------------------------------------------------------------
const GC = {
  // Main Blue — primary actions, links, the guardian brand accent.
  primary: C.guardianPrimary,
  // Darker blue derivative, TEXT-ONLY (badges, small labels on tint bg).
  primaryText: C.guardianPrimaryText,
  // Light blue tint, background-only (badge/tag fills).
  primaryBg: C.guardianPrimaryBg,

  // Point Orange — caution / warning accents.
  accent: C.guardianAccent,
  // Darker amber derivative, TEXT-ONLY, for AA contrast on light bg.
  accentText: C.guardianAccentText,
  accentBg: C.guardianAccentBg,

  // Danger Red — kept in the palette for a genuinely danger-toned UI element
  // (e.g. a future destructive action), but NOT used to color a safety-level
  // badge/card — FE does not compute or display a caution/safe/danger tier
  // (see SAFETY_STATUS_LABEL below).
  danger: C.guardianDanger,
  dangerText: C.guardianDangerText,
  dangerBg: C.guardianDangerBg,

  // Page Background.
  bg: C.guardianBg,
  // Card.
  surface: C.white,
  // Secondary Background (soft panels/dividers).
  surfaceSoft: C.guardianSurfaceSoft,

  // Primary Text.
  text: C.guardianText,
  // Secondary Text.
  textMuted: C.guardianTextMuted,

  // Neutral card/input border.
  line: C.guardianLine,
} as const

// ---------------------------------------------------------------------------
// SafetyStatus → label. FE does NOT judge safety — it only restates the
// contract's `safetyStatus` value as-is. The union has exactly one member
// today (`'unknown'`), so this map has exactly one entry; adding a
// 'safe'/'caution'/'danger' branch here would be FE inventing a severity the
// contract does not send (see AGENTS.md guardian-RAG constraint: the
// chatbot/status screen restates the log, it does not judge safety). If the
// contract ever adds a real value, `SafetyStatus` stops compiling here and
// this map is the one place to extend — not a place to add FE-derived tiers.
// ---------------------------------------------------------------------------
const SAFETY_STATUS_LABEL: Record<SafetyStatus, string> = {
  unknown: '확인되지 않음',
}

// Presentational facts read off `GuardianStatus` for the "현재 상태" card —
// derived strictly from openedAt/respondedAt/lastResponse, no inference:
//   - openedAt is a link-open timestamp, not a safety signal.
//   - lastResponse ('home'/'outside'/'none') is a button-press record, not a
//     survival signal — restated as "버튼 응답", never as "집에 있음"/
//     "안전함".
function guardianStatusFacts(status: GuardianStatus): string[] {
  const lines: string[] = []
  lines.push(status.openedAt ? `알림 열람 ${formatKstMinute(status.openedAt)}` : '알림 열람 기록 없음')
  if (status.lastResponse === 'none' || status.respondedAt === null) {
    // Narrowed from "응답 기록 없음": lastResponse:'none' means no
    // [집이에요]/[밖이에요] button press was recorded — it says nothing about
    // whether the session's SessionEvent action log (Q&A 화면의 근거) is
    // empty, so a bare "응답 기록 없음" would misread as "no activity at all".
    lines.push('집/밖 버튼 응답 기록 없음')
  } else {
    const buttonLabel = status.lastResponse === 'home' ? '[집이에요]' : '[밖이에요]'
    lines.push(`${buttonLabel} 버튼 응답 ${formatKstMinute(status.respondedAt)}`)
  }
  return lines
}

// Formats a contract ISO instant (openedAt/respondedAt, or a mock Q&A
// evidence timestamp) as a KST 24-hour "HH:MM" string, display-only —
// mirrors the "KST 기준 분 단위 24시간제" rule applied to Q&A answers too.
function formatKstMinute(iso: string): string {
  if (Number.isNaN(Date.parse(iso))) return '시간 확인 불가'
  const parts = new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(iso))
  const hh = parts.find((p) => p.type === 'hour')?.value ?? '00'
  const mm = parts.find((p) => p.type === 'minute')?.value ?? '00'
  return `${hh}:${mm}`
}

type GuardianScreen = 'alert' | 'status' | 'ai'

// height:'100dvh' pins the shell to the mobile viewport instead of letting it
// grow with content (dvh tracks the *actual* visible viewport, so a mobile
// browser's collapsing address bar doesn't clip the bottom) — a scrollable
// interior (AiScreen's turn list) can then grow without stretching the whole
// document. No minHeight:'100vh' alongside it — on a mobile browser 100vh can
// resolve larger than 100dvh (it includes the area the collapsing address bar
// covers), and a minHeight there would win over height:'100dvh' and defeat
// the whole point of using dvh. overflowY:'auto' is a safety net, not the
// intended scroll path — AlertScreen and StatusScreen are unchanged and
// expected to fit one viewport; AiScreen's own turn list (flex:1,
// minHeight:0, overflowY:'auto') is the real scroll container. This only
// engages if a screen's content is ever taller than the fixed shell height,
// so it degrades gracefully instead of clipping content.
const SHELL: CSSProperties = {
  width: '100%',
  maxWidth: MOBILE_WIDTH,
  margin: '0 auto',
  height: '100dvh',
  overflowY: 'auto',
  background: GC.bg,
  display: 'flex',
  flexDirection: 'column',
}

// Logo group — the shared public SAVERS mark (`/logo.png`, blue shield +
// orange heart, optimized in PR #173) + a hand-set "SAVERS" wordmark next to
// it (there is no combined logo+wordmark asset in the project, so the two
// are composed here rather than as one image). Home/Landing/Join still use
// the separate `logo-mark-light.png` asset for their own headers — this
// screen switches to the shared `/logo.png` (§11 of the guardian UI review)
// instead of that asset, but does not touch or remove it since those other
// screens still depend on it.
//
// Fixed size (24px logo / 18px text / 7px gap), not parameterized: every
// SAVERS brand area on this screen (첫 화면, 상태 화면 헤더) renders at the
// same size, matching the alert-landing header's logo size.
function LogoMark() {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px' }}>
      <img src="/logo.png" alt="" style={{ width: '24px', height: '24px', display: 'block', objectFit: 'contain' }} />
      <strong
        style={{
          fontSize: '18px',
          fontWeight: 800,
          color: GC.primary,
          letterSpacing: '-0.01em',
          lineHeight: 1,
        }}
      >
        SAVERS
      </strong>
    </div>
  )
}

interface GuardianProps {
  token?: string
}

export function Guardian({ token }: GuardianProps) {
  const [screen, setScreen] = useState<GuardianScreen>('alert')
  const { protectedPerson, alert } = GUARDIAN_MOCK
  const [status, setStatus] = useState<GuardianStatus | null>(
    token === undefined ? GUARDIAN_MOCK.status : null,
  )
  const [loadError, setLoadError] = useState(false)

  async function reloadStatus(): Promise<void> {
    if (token === undefined) return
    const isInitialLoad = status === null
    setLoadError(false)
    try {
      const next = await api.getGuardianStatus(token)
      setStatus(next)
    } catch (error) {
      if (isInitialLoad) setLoadError(true)
      throw error
    }
  }

  useEffect(() => {
    if (token === undefined) {
      setStatus(GUARDIAN_MOCK.status)
      return
    }
    let cancelled = false
    setStatus(null)
    setLoadError(false)
    api.getGuardianStatus(token).then(
      (next) => {
        if (!cancelled) setStatus(next)
      },
      () => {
        if (!cancelled) setLoadError(true)
      },
    )
    return () => {
      cancelled = true
    }
  }, [token])

  if (loadError) {
    return (
      <main style={{ ...SHELL, padding: gutter }}>
        <p>보호자 상태를 불러오지 못했습니다.</p>
        <button type="button" onClick={() => void reloadStatus().catch(() => {})}>
          다시 시도
        </button>
      </main>
    )
  }
  if (status === null) {
    return <main style={{ ...SHELL, padding: gutter }}>보호자 상태를 확인하는 중입니다.</main>
  }

  return (
    <div style={SHELL}>
      {screen === 'alert' && (
        <AlertScreen
          district={token === undefined ? alert.district : (status.dongName ?? '')}
          disaster={token === undefined ? alert.disaster : null}
          personName={token === undefined ? protectedPerson.name : status.wardName}
          sentAt={token === undefined ? alert.sentAt : null}
          preview={token === undefined}
          onConfirm={() => setScreen('status')}
        />
      )}
      {screen === 'status' && (
        <StatusScreen
          status={status}
          guardianToken={token}
          preview={token === undefined}
          onStatusReload={reloadStatus}
          onBack={() => setScreen('alert')}
          onOpenAi={() => setScreen('ai')}
        />
      )}
      {screen === 'ai' && (
        <AiScreen
          token={token}
          personName={token === undefined ? protectedPerson.name : status.wardName}
          onBack={() => setScreen('status')}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Shared header bar — grid(1fr auto 1fr) so the center content stays truly
// centered regardless of what (if anything) sits in the side slots (back
// button + brand + optional right-side action).
// ---------------------------------------------------------------------------

const HEADER_BAR: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr auto 1fr',
  alignItems: 'center',
  minHeight: '56px',
  padding: `0 8px`,
  borderBottom: `1px solid ${GC.line}`,
  flex: 'none',
}

const ICON_BTN: CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  minWidth: `${touchTarget.minimum}px`,
  minHeight: `${touchTarget.minimum}px`,
  border: 'none',
  background: 'transparent',
  color: GC.text,
  cursor: 'pointer',
  padding: 0,
  flex: 'none',
}

function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <div style={{ justifySelf: 'start' }}>
      <button type="button" style={ICON_BTN} onClick={onClick} aria-label="이전 화면">
        <svg viewBox="0 0 24 24" style={{ ...ICON, width: 24, height: 24 }}>
          <path d="m15 18-6-6 6-6" />
        </svg>
      </button>
    </div>
  )
}

function HeaderBar({
  onBack,
  center,
  right,
}: {
  onBack: () => void
  center: ReactNode
  right?: ReactNode
}) {
  return (
    <header style={HEADER_BAR}>
      <BackButton onClick={onBack} />
      <div style={{ justifySelf: 'center', display: 'flex', alignItems: 'center', gap: '8px' }}>
        {center}
      </div>
      <div style={{ justifySelf: 'end' }}>{right ?? null}</div>
    </header>
  )
}

// ---------------------------------------------------------------------------
// Screen 1 — 첫 진입 경보 화면
// ---------------------------------------------------------------------------

interface AlertScreenProps {
  district: string
  disaster: string | null
  personName: string
  sentAt: string | null
  preview: boolean
  onConfirm: () => void
}

function AlertScreen({ district, disaster, personName, sentAt, preview, onConfirm }: AlertScreenProps) {
  return (
    <main
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        padding: `${gutter}px`,
      }}
    >
      {/* 로고 그룹(아이콘+SAVERS)은 화면 좌우에 다른 요소 없이 가로 기준
          정확히 중앙에 위치한다 — grid 스페이서 트릭을 쓰지 않고 그냥
          justify-content:center로 둔다. */}
      <div style={{ display: 'flex', justifyContent: 'center', padding: '12px 0 8px' }} role="img" aria-label="SAVERS 로고">
        <LogoMark />
      </div>

      {/* alignItems intentionally left at the flex default (stretch), NOT
          'center' — a 'center' cross-axis on an auto-sized flex parent lets
          children (esp. the width:'100%' status card below) resolve their
          percentage width against an unbounded fit-content box and overflow
          the 375px viewport. Stretching this container to main's full width
          first, then centering each child individually (margin auto / text-
          align), keeps every child's percentage width bounded correctly. */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '28px' }}>
        {/* 시안 대비 시각적 중심감을 키우기 위해 폭을 72%→84%(최대
            260px→300px)로 한 단계 확대. 원본 비율 그대로(height:'auto'),
            crop/왜곡 없음 — 이 컨테이너가 이미 flex:1로 남는 세로 공간을
            모두 가져가므로 커져도 아래 문구/카드/CTA를 밀어내지 않는다. */}
        <img
          src={rain}
          alt="호우 경보를 나타내는 삽화"
          style={{ width: '84%', maxWidth: '300px', height: 'auto', display: 'block', margin: '0 auto' }}
        />

        <h1
          style={{
            margin: 0,
            textAlign: 'center',
            fontSize: '24px',
            fontWeight: 800,
            lineHeight: 1.45,
            letterSpacing: '-0.02em',
            color: GC.text,
          }}
        >
          보호자님,
          <br />
          {preview
            ? `${district} 지역에 ${disaster ?? ''} 발령 안내가 있어`
            : `${district !== '' ? `${district} 지역에 ` : ''}재난 안내가 있어`}
          <br />
          {personName}님께 안내 메시지를
          <br />
          발송했어요.
        </h1>

        <div
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            background: GC.surface,
            border: `1px solid ${GC.line}`,
            borderRadius: `${radius.card}px`,
            padding: '14px 16px',
            boxShadow: SHADOW_CARD,
          }}
        >
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
            <svg viewBox="0 0 24 24" style={{ ...ICON, width: 16, height: 16, stroke: GC.surface }}>
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </span>
          <div style={{ minWidth: 0 }}>
            <p style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: GC.text }}>
              {preview ? '안내 메시지 발송 완료' : '재난 안내 전달 완료'}
            </p>
            {preview && sentAt !== null && (
              <p style={{ margin: '2px 0 0', fontSize: '14px', color: GC.textMuted }}>{sentAt}</p>
            )}
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={onConfirm}
        style={{
          width: '100%',
          minHeight: `${touchTarget.ctaMin}px`,
          marginTop: '16px',
          border: 'none',
          borderRadius: `${radius.button}px`,
          background: GC.primary,
          color: GC.surface,
          fontFamily: 'inherit',
          fontSize: '18px',
          fontWeight: 800,
          letterSpacing: '-0.01em',
          cursor: 'pointer',
        }}
      >
        상황 확인하기
      </button>
    </main>
  )
}

// ---------------------------------------------------------------------------
// Screen 2 — 가족 현황
// ---------------------------------------------------------------------------

const card: CSSProperties = {
  background: GC.surface,
  border: `1px solid ${GC.line}`,
  borderRadius: `${radius.card}px`,
  padding: '16px',
  boxShadow: SHADOW_CARD,
}

const sectionTitle: CSSProperties = {
  margin: '0 0 10px',
  fontSize: '15px',
  fontWeight: 800,
  color: GC.textMuted,
}

function StatusScreen({
  status,
  guardianToken,
  preview,
  onStatusReload,
  onBack,
  onOpenAi,
}: {
  status: GuardianStatus
  guardianToken?: string
  preview: boolean
  onStatusReload: () => Promise<void>
  onBack: () => void
  onOpenAi: () => void
}) {
  const facts = guardianStatusFacts(status)

  return (
    <>
      {/* HeaderBar의 right 슬롯은 비워 둔다 — 이전에 있던 "더보기" 버튼은
          onClick={() => {}}인 채로 아무 기능이 없어 제거했다. 실제 메뉴(알림
          설정 등)가 생기면 그때 right에 새로 채운다; 지금 disabled 버튼이나
          자리표시자를 넣지 않는다. */}
      <HeaderBar onBack={onBack} center={<LogoMark />} />

      <main style={{ flex: 1, padding: `18px ${gutter}px ${gutter}px`, display: 'flex', flexDirection: 'column', gap: '22px' }}>
        <section>
          <h1 style={{ ...sectionTitle, fontSize: '16px' }}>등록된 가족</h1>
          {preview ? (
            <FamilyCard
              name={GUARDIAN_MOCK.protectedPerson.name}
              relation={GUARDIAN_MOCK.protectedPerson.relation}
              age={GUARDIAN_MOCK.protectedPerson.age}
              persona={GUARDIAN_MOCK.protectedPerson.persona}
              safetyStatus={status.safetyStatus}
            />
          ) : (
            <div style={card}>
              <p style={{ margin: 0, fontSize: '19px', fontWeight: 800, color: GC.text }}>
                {status.wardName}
              </p>
              {status.dongName !== undefined && (
                <p style={{ margin: '6px 0 0', fontSize: '14.5px', color: GC.textMuted }}>
                  {status.dongName}
                </p>
              )}
              <span
                style={{
                  display: 'inline-block',
                  marginTop: '8px',
                  fontSize: '13px',
                  fontWeight: 700,
                  color: GC.textMuted,
                  background: GC.surfaceSoft,
                  border: `1px solid ${GC.line}`,
                  borderRadius: `${radius.chip}px`,
                  padding: '4px 12px',
                }}
              >
                {SAFETY_STATUS_LABEL[status.safetyStatus]}
              </span>
            </div>
          )}
        </section>

        <section>
          <h2 style={sectionTitle}>현재 상태</h2>
          {/* 판정 카드가 아니라 사실 카드다 — 배경/아이콘 모두 중립색
              하나뿐이고, status.safetyStatus/lastResponse로 강조색을
              고르지 않는다. 제목은 "현재 확인된 기록"으로 고정하고, 본문은
              guardianStatusFacts()가 openedAt/respondedAt/lastResponse에서
              그대로 뽑아낸 사실 문장만 나열한다(안전 여부를 담은 headline은
              쓰지 않는다). */}
          <div style={{ ...card, display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
            <span
              aria-hidden="true"
              style={{
                flex: 'none',
                width: '28px',
                height: '28px',
                borderRadius: '50%',
                background: GC.surfaceSoft,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {/* 중립 "정보(i)" 아이콘 — 점이 위, 선이 아래. 이전에는 선이
                  위/점이 아래인 경고(!) 아이콘이었다(주의 상태를 표시하던
                  시절의 잔재). */}
              <svg viewBox="0 0 24 24" style={{ ...ICON, width: 16, height: 16, stroke: GC.textMuted }}>
                <path d="M12 8h.01M12 11v5" />
                <circle cx="12" cy="12" r="9" />
              </svg>
            </span>
            <div style={{ minWidth: 0 }}>
              <p style={{ margin: 0, fontSize: '16px', fontWeight: 800, color: GC.text }}>현재 확인된 기록</p>
              {facts.map((line, i) => (
                <p key={`${line}-${i}`} style={{ margin: '4px 0 0', fontSize: '14.5px', color: GC.text, lineHeight: 1.5 }}>
                  {line}
                </p>
              ))}
            </div>
          </div>

          {/* 상태 카드 바로 아래, section 리듬에 맞춘 14px 간격 —
              이전에는 marginTop:'auto'로 화면 맨 아래에 고정돼 있었다. */}
          <button
            type="button"
            onClick={onOpenAi}
            style={{
              width: '100%',
              marginTop: '14px',
              minHeight: `${touchTarget.ctaMin}px`,
              border: 'none',
              borderRadius: `${radius.button}px`,
              background: GC.primary,
              color: GC.surface,
              fontFamily: 'inherit',
              fontSize: '18px',
              fontWeight: 800,
              letterSpacing: '-0.01em',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '8px',
            }}
          >
            <span aria-hidden="true">✨</span>
            안전 확인 AI
          </button>
        </section>
        {guardianToken !== undefined && (
          <GuardianPushControl
            token={guardianToken}
            serverPushEnabled={status.pushEnabled}
            onStatusReload={onStatusReload}
          />
        )}
      </main>
    </>
  )
}

function isThisBrowserSubscribed(token: string): boolean {
  const storedToken = migrateLegacyGuardianFcmToken(token)
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return false
  return storedToken !== null
}

function GuardianPushControl({
  token,
  serverPushEnabled,
  onStatusReload,
}: {
  token: string
  serverPushEnabled: boolean
  onStatusReload: () => Promise<void>
}) {
  const [subscribed, setSubscribed] = useState(() => isThisBrowserSubscribed(token))
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  async function subscribe(): Promise<void> {
    setPending(true)
    setNotice(null)
    const result = await requestPushPermissionForGuardian(token)
    setPending(false)
    if (result.status !== 'granted') {
      const isNoGuardian =
        result.status === 'apiError' &&
        result.error instanceof BackendApiError &&
        result.error.status === 400 &&
        result.error.code === 'INVALID_REQUEST'
      setNotice(
        isNoGuardian
          ? '이 대상자에게는 등록된 보호자가 없어 등록할 수 없어요.'
          : '알림 등록에 실패했습니다. 브라우저 권한과 연결 상태를 확인해 주세요.',
      )
      return
    }
    writeGuardianFcmToken(result.token)
    try {
      await onStatusReload()
    } catch {
      setNotice('알림 등록은 완료됐지만 현재 상태를 다시 확인하지 못했습니다.')
    }
    setSubscribed(true)
  }

  async function unsubscribe(): Promise<void> {
    const fcmToken = readGuardianFcmToken()
    if (fcmToken === null) {
      setNotice('이 브라우저의 알림 토큰을 확인할 수 없어 해제하지 못했습니다.')
      return
    }
    setPending(true)
    setNotice(null)
    try {
      await api.unregisterGuardianDevice(token, {
        fcmToken,
        userAgent: typeof navigator === 'undefined' ? null : navigator.userAgent,
      })
      removeGuardianFcmToken()
      try {
        await onStatusReload()
      } catch {
        setNotice('알림 해제는 완료됐지만 현재 상태를 다시 확인하지 못했습니다.')
      }
      setSubscribed(false)
    } catch {
      setNotice('알림 해제에 실패했습니다. 잠시 뒤 다시 시도해 주세요.')
    } finally {
      setPending(false)
    }
  }

  if (subscribed && serverPushEnabled) {
    return (
      <section style={{ ...card, marginTop: '14px' }}>
        <p role="status" style={{ margin: '0 0 12px', fontSize: '14.5px', color: GC.text, lineHeight: 1.5 }}>
          이 휴대폰에서 보호자 알림을 받도록 설정한 기록이 있어요.
        </p>
        <button
          type="button"
          className="guardian-push-btn guardian-push-btn--outline"
          disabled={pending}
          onClick={() => void unsubscribe()}
        >
          {pending ? '해제 중...' : '알림 해제'}
        </button>
        {notice !== null && (
          <p role="status" style={{ margin: '10px 0 0', fontSize: '13.5px', color: GC.textMuted }}>
            {notice}
          </p>
        )}
      </section>
    )
  }
  // 미등록 상태 — 정상 재난 흐름의 메인 CTA(안전 확인 AI)가 아니라, 다른
  // 휴대폰에서 /g/{token} 링크를 열었을 때 쓰는 보조/복구 설정이다. 그래서
  // 제목은 작게, 설명은 secondary 톤으로 낮춰 노출 위계를 지킨다. 이 등록은
  // 기존 guardian device에 추가되는 것이 아니라 현재 휴대폰의 토큰 하나로
  // 교체되는 계약이므로("이 기기도 알림 받기" 아님), 버튼 문구도 "변경"의
  // 의미를 그대로 담는다.
  const localStateMismatch = subscribed && !serverPushEnabled
  const title = localStateMismatch
    ? '알림 설정'
    : serverPushEnabled
      ? '알림 받을 휴대폰 변경'
      : '알림 받을 휴대폰 설정'
  const description = localStateMismatch
    ? '이 휴대폰으로 보호자 알림을 다시 설정할 수 있어요.'
    : serverPushEnabled
      ? '보호자 알림을 받을 휴대폰이 이미 등록되어 있어요. 원하면 이 휴대폰으로 변경할 수 있어요.'
      : '이 휴대폰으로 보호자 알림을 받을 수 있어요.'
  const buttonLabel = localStateMismatch
    ? '이 휴대폰으로 다시 등록'
    : serverPushEnabled
      ? '이 휴대폰으로 변경'
      : '이 휴대폰으로 알림 받기'

  return (
    <section style={{ ...card, marginTop: '14px' }}>
      <p style={{ margin: '0 0 4px', fontSize: '14.5px', fontWeight: 800, color: GC.text }}>
        {title}
      </p>
      <p style={{ margin: '0 0 12px', fontSize: '13.5px', color: GC.textMuted, lineHeight: 1.5 }}>
        {description}
      </p>
      <button
        type="button"
        className="guardian-push-btn guardian-push-btn--secondary"
        disabled={pending}
        onClick={() => void subscribe()}
      >
        {pending ? '등록 중...' : buttonLabel}
      </button>
      {notice !== null && (
        <p role="status" style={{ margin: '10px 0 0', fontSize: '13.5px', color: GC.textMuted }}>
          {notice}
        </p>
      )}
    </section>
  )
}

function FamilyCard({
  name,
  relation,
  age,
  persona,
  safetyStatus,
}: {
  name: string
  relation: string
  age: number
  persona: keyof typeof PERSONA_IMAGE
  safetyStatus: SafetyStatus
}) {
  // 배지 문구는 SAFETY_STATUS_LABEL 하나로만 결정한다 — FE가 위험도를
  // 계산하지 않고, 계약의 safetyStatus 값(현재는 'unknown' 하나뿐)을 그대로
  // 문구로 옮긴다. 색도 중립(neutral) 하나뿐이라 "판정 배지"처럼 보이지
  // 않는다 — 위험/주의/안전 색 분기는 이제 이 컴포넌트에 없다.
  const badgeLabel = SAFETY_STATUS_LABEL[safetyStatus]

  return (
    // 프로필 이미지를 카드 왼쪽에서 확실한 비중으로 키우고(56px→84px→108px,
    // 약 1.3배 추가 확대), 오른쪽 정보는 이름→관계·나이→상태 배지 순서로
    // 세로로 쌓는다(가로로 흩어져 있던 기존 배치 대신 "보호 대상자 대표
    // 프로필" 카드처럼 보이게). 카드 자체는 그대로 flex row 구조 —
    // align-items:center라 이미지가 커지면 카드 높이만 자연스럽게 늘어나고,
    // 오른쪽 텍스트 열은 밀려나거나 잘리지 않는다(375px에서도 여유 있음).
    <div style={{ ...card, display: 'flex', alignItems: 'center', gap: '16px', padding: '18px 16px' }}>
      <img
        src={PERSONA_IMAGE[persona]}
        alt={`${name} 프로필 사진`}
        style={{
          width: '108px',
          height: '108px',
          borderRadius: '50%',
          objectFit: 'cover',
          flex: 'none',
          background: GC.surfaceSoft,
        }}
      />
      <div style={{ minWidth: 0, flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
        <p style={{ margin: 0, fontSize: '19px', fontWeight: 800, color: GC.text }}>{name}</p>
        <p style={{ margin: 0, fontSize: '14.5px', color: GC.textMuted }}>
          {relation} · {age}세
        </p>
        <span
          style={{
            alignSelf: 'flex-start',
            fontSize: '13px',
            fontWeight: 700,
            color: GC.textMuted,
            background: GC.surfaceSoft,
            border: `1px solid ${GC.line}`,
            borderRadius: `${radius.chip}px`,
            padding: '4px 12px',
          }}
        >
          {badgeLabel}
        </span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Screen 3 — 안전 확인 AI Q&A
// ---------------------------------------------------------------------------

type QaDisplayTurn =
  | { kind: 'answer'; questionId: GuardianQuestionId; question: string; answer: string }
  | { kind: 'no_evidence'; questionId: GuardianQuestionId; question: string }
  | { kind: 'unsupported'; questionId: GuardianQuestionId; question: string }
  | { kind: 'error'; questionId: GuardianQuestionId; question: string }
  | { kind: 'malformed'; questionId: GuardianQuestionId; question: string }

function classifyGuardianAnswer(
  result: GuardianAnswer,
): 'delivered' | 'no_evidence' | 'malformed' {
  if (
    result.answer !== null &&
    result.answer.trim() !== '' &&
    result.sources.length > 0 &&
    result.refusalReason === null
  ) {
    return 'delivered'
  }
  if (
    result.answer === null &&
    result.sources.length === 0 &&
    result.refusalReason === 'no_evidence'
  ) {
    return 'no_evidence'
  }
  return 'malformed'
}

function AiScreen({
  token,
  personName,
  onBack,
}: {
  token?: string
  personName: string
  onBack: () => void
}) {
  const { recommendedQuestions } = GUARDIAN_MOCK
  const [turns, setTurns] = useState<(QaTurn | QaDisplayTurn)[]>([])
  const [isAsking, setIsAsking] = useState(false)
  // Which recommended-question button is currently pressed, for the
  // momentary orange-border press feedback below — NOT a persisted
  // "selected" state (it always clears on release/leave/cancel). Keyed by
  // questionId (the contract identity), not the button's label text.
  const [pressedQuestion, setPressedQuestion] = useState<GuardianQuestionId | null>(null)
  const clearPressed = () => setPressedQuestion(null)

  // Scroll-anchor for the turn list: a sentinel div after the last turn that
  // auto-scroll targets. Ref, not state — scrolling is a DOM side effect,
  // not something the render output depends on.
  const turnsEndRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (turns.length === 0) return
    turnsEndRef.current?.scrollIntoView({ block: 'end' })
  }, [turns])

  // Each recommended question already carries its own answer (QaTurn) —
  // just append it. No string-key lookup that could silently miss.
  async function askRecommended(turn: QaTurn): Promise<void> {
    if (token === undefined) {
      setTurns((prev) => [...prev, turn])
      return
    }
    if (isAsking) return
    setIsAsking(true)
    try {
      const result = await api.postGuardianAsk(token, {
        questionId: turn.questionId,
        locale: 'ko',
      })
      const outcome = classifyGuardianAnswer(result)
      if (outcome === 'delivered') {
        setTurns((prev) => [
          ...prev,
          {
            kind: 'answer',
            questionId: turn.questionId,
            question: turn.question,
            answer: result.answer as string,
          },
        ])
      } else {
        setTurns((prev) => [
          ...prev,
          { kind: outcome, questionId: turn.questionId, question: turn.question },
        ])
      }
    } catch (error) {
      const kind =
        error instanceof BackendApiError && error.status === 422
          ? 'unsupported'
          : 'error'
      setTurns((prev) => [
        ...prev,
        { kind, questionId: turn.questionId, question: turn.question },
      ])
    } finally {
      setIsAsking(false)
    }
  }

  return (
    <>
      <HeaderBar
        onBack={onBack}
        center={
          <>
            <span
              aria-hidden="true"
              style={{
                width: '26px',
                height: '26px',
                borderRadius: '8px',
                background: GC.primary,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none',
              }}
            >
              <span style={{ fontSize: '13px', lineHeight: 1 }}>✨</span>
            </span>
            <strong style={{ fontSize: '18px', fontWeight: 800, color: GC.text, letterSpacing: '-0.01em' }}>안전 확인 AI</strong>
          </>
        }
      />

      <main style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ padding: `14px ${gutter}px 0` }}>
          <p style={{ margin: '0 0 14px', fontSize: '14.5px', color: GC.textMuted, lineHeight: 1.5 }}>
            {personName}님의 행동 기록을 기반으로 답변드려요.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {recommendedQuestions.map((turn) => (
              <button
                key={turn.questionId}
                type="button"
                onClick={() => void askRecommended(turn)}
                disabled={isAsking}
                // 눌린 동안만 border를 orange로 — 배경/모양은 그대로 두고
                // border-color만 바꾸는 짧은 pressed 피드백. pointer 계열
                // 이벤트라 마우스·터치 모두 같은 핸들러로 처리되고, up/leave/
                // cancel 어느 쪽으로 끝나든 눌림 상태가 남지 않는다.
                onPointerDown={() => setPressedQuestion(turn.questionId)}
                onPointerUp={clearPressed}
                onPointerLeave={clearPressed}
                onPointerCancel={clearPressed}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  minHeight: `${touchTarget.minimum}px`,
                  padding: '12px 14px',
                  border: `1px solid ${pressedQuestion === turn.questionId ? GC.accent : GC.line}`,
                  borderRadius: `${radius.button}px`,
                  background: GC.surface,
                  color: GC.text,
                  fontFamily: 'inherit',
                  fontSize: '15.5px',
                  fontWeight: 600,
                  cursor: isAsking ? 'default' : 'pointer',
                  opacity: isAsking ? 0.6 : 1,
                  transition: 'border-color 150ms ease',
                  // 모바일 브라우저 기본 tap-highlight(하늘색 사각 flash)를
                  // 이 버튼 범위에서만 끈다 — 전역 스타일은 건드리지 않는다.
                  // 키보드 :focus-visible 아웃라인과는 별개 속성이라 포커스
                  // 표시는 그대로 남는다.
                  WebkitTapHighlightColor: 'transparent',
                }}
              >
                {turn.question}
              </button>
            ))}
          </div>
        </div>

        {/* 대화 목록 — minHeight:0이 있어야 flex:1이 부모(이 main)의 남는
            높이로 실제로 줄어들 수 있고, overflowY:'auto'가 그 안에서 진짜
            스크롤 컨테이너로 동작한다(minHeight:0 없이는 flex 아이템의
            기본 최소 높이가 content 높이라 부모를 밀어내며 커진다 — 이
            화면이 SHELL/main의 고정 높이 안에서 스크롤 대신 전체가
            늘어나던 원인). 자유 입력 폼이 빠졌으므로 이 영역이 main의
            유일한 flex:1 자식이다. */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            overflowY: 'auto',
            padding: `16px ${gutter}px calc(16px + env(safe-area-inset-bottom, 0px))`,
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
          }}
        >
          {turns.map((turn, i) => (
            <div key={`${turn.questionId}-${i}`} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div
                style={{
                  alignSelf: 'flex-end',
                  maxWidth: '85%',
                  background: GC.primary,
                  color: GC.surface,
                  borderRadius: '16px 16px 4px 16px',
                  padding: '10px 14px',
                  fontSize: '15.5px',
                  lineHeight: 1.5,
                }}
              >
                {turn.question}
              </div>
              <div
                style={{
                  alignSelf: 'flex-start',
                  maxWidth: '92%',
                  background: GC.surface,
                  border: `1px solid ${GC.line}`,
                  boxShadow: SHADOW_CARD,
                  borderRadius: '4px 16px 16px 16px',
                  padding: '12px 14px',
                }}
              >
                {!('kind' in turn) && (
                  <>
                    <p style={{ margin: 0, fontSize: '15.5px', lineHeight: 1.55, color: GC.text, fontWeight: 700 }}>{turn.answer}</p>
                    {turn.note !== undefined && (
                      <p style={{ margin: '6px 0 0', fontSize: '14px', lineHeight: 1.5, color: GC.textMuted }}>{turn.note}</p>
                    )}
                  </>
                )}
                {'kind' in turn && turn.kind === 'answer' && (
                  <p style={{ margin: 0, fontSize: '15.5px', lineHeight: 1.55, color: GC.text, fontWeight: 700 }}>{turn.answer}</p>
                )}
                {'kind' in turn && turn.kind === 'no_evidence' && (
                  <>
                    <p style={{ margin: 0, fontSize: '15.5px', lineHeight: 1.55, color: GC.text, fontWeight: 700 }}>
                      확인할 수 있는 기록이 없습니다
                    </p>
                    <a
                      href="tel:119"
                      style={{
                        marginTop: '10px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        width: '100%',
                        minHeight: `${touchTarget.minimum}px`,
                        borderRadius: `${radius.button}px`,
                        background: GC.danger,
                        color: GC.surface,
                        fontWeight: 800,
                        textDecoration: 'none',
                      }}
                    >
                      119 신고하기
                    </a>
                  </>
                )}
                {'kind' in turn && turn.kind === 'unsupported' && (
                  <p style={{ margin: 0, color: GC.textMuted }}>지원하지 않는 질문입니다.</p>
                )}
                {'kind' in turn && turn.kind === 'error' && (
                  <p style={{ margin: 0, color: GC.textMuted }}>답변을 가져오지 못했습니다. 잠시 뒤 다시 시도해 주세요.</p>
                )}
                {'kind' in turn && turn.kind === 'malformed' && (
                  <p style={{ margin: 0, color: GC.textMuted }}>답변 형식을 확인할 수 없습니다. 잠시 뒤 다시 시도해 주세요.</p>
                )}
              </div>
            </div>
          ))}
          {/* 스크롤 앵커 — 새 turn이 추가될 때마다 useEffect가 이 sentinel로
              scrollIntoView해 최신 답변이 보이게 한다. 화면에는 아무것도
              그리지 않는다(높이 0). */}
          <div ref={turnsEndRef} />
        </div>
      </main>
    </>
  )
}
