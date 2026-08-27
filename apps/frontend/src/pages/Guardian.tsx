// Guardian (/guardian) — 보호자 모바일 화면, UI 선작업.
//
// STATUS: #122 GuardianStatus API/FCM 계약이 아직 main에 머지되지 않은
// 상태에서 만든 화면이다. 실제 `/g/{guardianToken}` 계약이 완성된 것처럼
// 구현하지 않는다 — 이 파일은 ../api/* 를 import 하지 않고, mocks/
// guardianStatus.ts 의 고정 목데이터만 읽는다. `/guardian` 은 그 계약이
// 확정되기 전까지의 임시 UI 미리보기 경로이고, 실제 계약 경로인
// `/g/{token}` 은 이 PR의 스코프가 아니다(App.tsx 상단 라우트 표 참고).
//
// #122 계약 머지 후 교체할 지점(정확히 이 두 곳):
//   1. App.tsx 의 `/guardian` 라우트를 `/g/{token}` 으로 바꾸고 URL에서
//      토큰을 읽어 이 컴포넌트에 넘긴다(Landing.tsx 의 LandingView 패턴
//      참고 — `?t=` 파싱).
//   2. 아래 `GUARDIAN_MOCK` 대신 실제 GuardianStatus 응답을 fetch해
//      Screen 컴포넌트들에 넘긴다. Screen 컴포넌트의 props 타입
//      (ProtectedPerson/AlertInfo/StatusInfo/QaTurn)은 mocks/
//      guardianStatus.ts 의 타입과 이미 API 응답 형태를 염두에 두고
//      맞춰뒀으므로, mock 객체 자리에 실제 응답 객체를 넣기만 하면 된다.
//   3. AiScreen의 추천 질문 답변은 지금 mocks/guardianStatus.ts에 고정된
//      QaTurn을 실제 보호자 응답 정확도 RAG(로그 기반) 호출로 바꾼다 —
//      ChatDock.tsx가 쓰는 「근거 없으면 답하지 않는다」 원칙을 그대로
//      따를 것.
//
// 화면 3개는 하위 라우트가 아니라 한 페이지 안의 로컬 state(screen)로
// 전환한다 — 계약이 없는 지금 단계에서 라우팅을 새로 만들 이유가 없다.

import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import rain from '../assets/rain.png'
import logoLight from '../assets/logo-mark-light.png'
import { C, ICON, MOBILE_WIDTH, SHADOW_CARD, gutter, radius, touchTarget } from '../lib/tokens'
import {
  GUARDIAN_MOCK,
  PERSONA_IMAGE,
  type QaTurn,
  type StatusLevel,
} from '../mocks/guardianStatus'

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

  // Danger Red — reserved for an actual danger state (not used by today's
  // mock data, which only exercises 'caution', but the badge/card branch
  // exists for when it is).
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
// STATUS → COLOR mapping. Single place both the family badge and the
// "현재 상태" card read, so the emphasis colour always follows the SAME
// `StatusLevel` value (mocks/guardianStatus.ts today; a future GuardianStatus
// API field 1:1 with it) rather than being re-decided per component. This
// file does NOT compute a severity — it only maps the level value it's
// given onto the SAVERS palette. 'caution' is the only branch the current
// mock data exercises; 'safe'/'danger' exist because the type already does,
// not because FE is inventing new states.
// ---------------------------------------------------------------------------
interface StatusStyle {
  // Icon fill (warning glyph circle).
  iconBg: string
  // Badge (family card "주의" chip).
  badgeBg: string
  badgeText: string
  badgeBorder: string
  // "현재 상태" card's own light tint — kept as a background tint only
  // (never a border-only or full-saturation fill) so the card reads as
  // "주의 상태를 한눈에 알 수 있는 정도", not a solid-orange alert block.
  cardTint: string
}

function statusStyle(level: StatusLevel): StatusStyle {
  if (level === 'danger') {
    return { iconBg: GC.danger, badgeBg: GC.dangerBg, badgeText: GC.dangerText, badgeBorder: GC.danger, cardTint: GC.dangerBg }
  }
  if (level === 'safe') {
    // 이 팔레트엔 별도 success(초록) 계열이 없다 — 위험(red)·주의(orange)와
    // 구분되는 차분한 상태로 Main Blue를 재사용한다.
    return { iconBg: GC.primary, badgeBg: GC.primaryBg, badgeText: GC.primaryText, badgeBorder: GC.primary, cardTint: GC.primaryBg }
  }
  return { iconBg: GC.accent, badgeBg: GC.accentBg, badgeText: GC.accentText, badgeBorder: GC.accent, cardTint: GC.accentBg }
}

type GuardianScreen = 'alert' | 'status' | 'ai'

const SHELL: CSSProperties = {
  width: '100%',
  maxWidth: MOBILE_WIDTH,
  margin: '0 auto',
  minHeight: '100vh',
  background: GC.bg,
  display: 'flex',
  flexDirection: 'column',
}

// Logo group — logo-mark-light.png (shield only) + a hand-set "SAVERS"
// wordmark next to it, same asset Home/Landing/Join already import as
// `logoLight` (there is no combined logo+wordmark asset in the project, so
// the two are composed here rather than as one image). This screen
// previously referenced a public `/logo.png` that does not exist in this
// branch, which silently rendered as a broken image with only the text
// visible — using the existing shared asset fixes that.
//
// Fixed size (24px logo / 18px text / 7px gap), not parameterized: every
// SAVERS brand area on this screen (첫 화면, 상태 화면 헤더) renders at the
// same size, matching the alert-landing header's logo size.
function LogoMark() {
  return (
    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '7px' }}>
      <img src={logoLight} alt="" style={{ width: '24px', height: '24px', display: 'block', objectFit: 'contain' }} />
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

export function Guardian() {
  const [screen, setScreen] = useState<GuardianScreen>('alert')
  const { protectedPerson, alert } = GUARDIAN_MOCK

  return (
    <div style={SHELL}>
      {screen === 'alert' && (
        <AlertScreen
          district={alert.district}
          disaster={alert.disaster}
          personName={protectedPerson.name}
          sentAt={alert.sentAt}
          onConfirm={() => setScreen('status')}
        />
      )}
      {screen === 'status' && (
        <StatusScreen
          onBack={() => setScreen('alert')}
          onOpenAi={() => setScreen('ai')}
        />
      )}
      {screen === 'ai' && <AiScreen onBack={() => setScreen('status')} />}
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
  disaster: string
  personName: string
  sentAt: string
  onConfirm: () => void
}

function AlertScreen({ district, disaster, personName, sentAt, onConfirm }: AlertScreenProps) {
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
          {district} 지역에 {disaster} 발령 안내가 있어
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
            <p style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: GC.text }}>안내 메시지 발송 완료</p>
            <p style={{ margin: '2px 0 0', fontSize: '14px', color: GC.textMuted }}>{sentAt}</p>
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

function StatusScreen({ onBack, onOpenAi }: { onBack: () => void; onOpenAi: () => void }) {
  const { protectedPerson, status } = GUARDIAN_MOCK
  const emphasis = statusStyle(status.level)

  return (
    <>
      <HeaderBar
        onBack={onBack}
        center={<LogoMark />}
        right={
          // 더보기 메뉴는 아직 아무 기능도 없다 — 이번 UI 선작업 범위 밖.
          // 실제 메뉴(알림 설정 등)가 생기면 이 버튼에 onClick을 채운다.
          <button type="button" style={ICON_BTN} aria-label="더보기" onClick={() => {}}>
            <svg viewBox="0 0 24 24" style={{ ...ICON, width: 22, height: 22 }}>
              <circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
              <circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none" />
            </svg>
          </button>
        }
      />

      <main style={{ flex: 1, padding: `18px ${gutter}px ${gutter}px`, display: 'flex', flexDirection: 'column', gap: '22px' }}>
        <section>
          <h1 style={{ ...sectionTitle, fontSize: '16px' }}>등록된 가족</h1>
          <FamilyCard
            name={protectedPerson.name}
            relation={protectedPerson.relation}
            age={protectedPerson.age}
            persona={protectedPerson.persona}
            statusLevel={status.level}
          />
        </section>

        <section>
          <h2 style={sectionTitle}>현재 상태</h2>
          {/* 상태별 강조색은 statusStyle(status.level) 하나로만 결정한다 —
              여기서 위험도를 새로 계산하지 않고, mock/향후 서버 응답의
              StatusLevel 값을 SAVERS 팔레트에 매핑만 한다. 카드를 top(연한
              tint 배경의 headline/설명) / bottom(중립 배경의 마지막 반응)
              두 블록으로 나눠, "한눈에 알 수 있는 정도"로만 강조되고 카드
              전체가 강조색으로 뒤덮이지 않게 한다. */}
          <div style={{ ...card, padding: 0, overflow: 'hidden' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '10px',
                background: emphasis.cardTint,
                padding: '16px',
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  flex: 'none',
                  width: '28px',
                  height: '28px',
                  borderRadius: '50%',
                  background: emphasis.iconBg,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                <svg viewBox="0 0 24 24" style={{ ...ICON, width: 16, height: 16, stroke: GC.surface }}>
                  <path d="M12 8v5M12 16.5h.01" />
                  <circle cx="12" cy="12" r="9" />
                </svg>
              </span>
              <div style={{ minWidth: 0 }}>
                <p style={{ margin: 0, fontSize: '16px', fontWeight: 800, color: GC.text }}>{status.headline}</p>
                {status.detailLines.map((line, i) => (
                  <p key={`${line}-${i}`} style={{ margin: '4px 0 0', fontSize: '14.5px', color: GC.text, lineHeight: 1.5 }}>
                    {line}
                  </p>
                ))}
              </div>
            </div>
            <div
              style={{
                padding: '10px 16px',
                borderTop: `1px solid ${GC.line}`,
                background: GC.surface,
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                color: GC.textMuted,
                fontSize: '14px',
              }}
            >
              <svg viewBox="0 0 24 24" style={{ ...ICON, width: 15, height: 15 }}>
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 3" />
              </svg>
              <span>마지막 반응 {status.lastResponseAt}</span>
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
      </main>
    </>
  )
}

function FamilyCard({
  name,
  relation,
  age,
  persona,
  statusLevel,
}: {
  name: string
  relation: string
  age: number
  persona: keyof typeof PERSONA_IMAGE
  statusLevel: StatusLevel
}) {
  // 배지 색은 statusStyle() 하나로만 결정한다 — "현재 상태" 카드와 같은
  // 매핑을 공유해, 이 카드에서 위험도를 별도로 다시 계산하지 않는다. 라벨
  // 문구만 이 컴포넌트 로컬로 둔다(statusStyle은 색만 안다).
  const emphasis = statusStyle(statusLevel)
  const badgeLabel = statusLevel === 'danger' ? '위험' : statusLevel === 'safe' ? '안전' : '주의'

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
            color: emphasis.badgeText,
            background: emphasis.badgeBg,
            border: `1px solid ${emphasis.badgeBorder}`,
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
// Screen 3 — 안전 확인 AI (mock Q&A)
// ---------------------------------------------------------------------------

function AiScreen({ onBack }: { onBack: () => void }) {
  const { protectedPerson, recommendedQuestions, freeformFallback } = GUARDIAN_MOCK
  const [turns, setTurns] = useState<QaTurn[]>([])
  const [draft, setDraft] = useState('')
  // Which recommended-question button is currently pressed, for the
  // momentary orange-border press feedback below — NOT a persisted
  // "selected" state (it always clears on release/leave/cancel).
  const [pressedQuestion, setPressedQuestion] = useState<string | null>(null)
  const clearPressed = () => setPressedQuestion(null)

  // Each recommended question already carries its own answer (QaTurn) —
  // just append it. No string-key lookup that could silently miss.
  function askRecommended(turn: QaTurn): void {
    setTurns((prev) => [...prev, turn])
  }

  function askFreeform(): void {
    const question = draft.trim()
    if (question === '') return
    // 목업 범위: 자유 입력은 항상 거절형 fallback 답변을 보여준다 — 실제
    // 로그 매칭 없이 그럴듯한 답을 지어내지 않기 위해서다(표현 원칙 참고).
    setTurns((prev) => [...prev, { ...freeformFallback, question }])
    setDraft('')
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
            {protectedPerson.name}님의 행동 기록을 기반으로 답변드려요.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {recommendedQuestions.map((turn) => (
              <button
                key={turn.question}
                type="button"
                onClick={() => askRecommended(turn)}
                // 눌린 동안만 border를 orange로 — 배경/모양은 그대로 두고
                // border-color만 바꾸는 짧은 pressed 피드백. pointer 계열
                // 이벤트라 마우스·터치 모두 같은 핸들러로 처리되고, up/leave/
                // cancel 어느 쪽으로 끝나든 눌림 상태가 남지 않는다.
                onPointerDown={() => setPressedQuestion(turn.question)}
                onPointerUp={clearPressed}
                onPointerLeave={clearPressed}
                onPointerCancel={clearPressed}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  minHeight: `${touchTarget.minimum}px`,
                  padding: '12px 14px',
                  border: `1px solid ${pressedQuestion === turn.question ? GC.accent : GC.line}`,
                  borderRadius: `${radius.button}px`,
                  background: GC.surface,
                  color: GC.text,
                  fontFamily: 'inherit',
                  fontSize: '15.5px',
                  fontWeight: 600,
                  cursor: 'pointer',
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

        <div
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: `16px ${gutter}px`,
            display: 'flex',
            flexDirection: 'column',
            gap: '14px',
          }}
        >
          {turns.map((turn, i) => (
            <div key={`${turn.question}-${i}`} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
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
                <p style={{ margin: 0, fontSize: '15.5px', lineHeight: 1.55, color: GC.text, fontWeight: 700 }}>{turn.answer}</p>
                {turn.note !== undefined && (
                  <p style={{ margin: '6px 0 0', fontSize: '14px', lineHeight: 1.5, color: GC.textMuted }}>{turn.note}</p>
                )}
              </div>
            </div>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault()
            askFreeform()
          }}
          style={{
            flex: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: `10px ${gutter}px calc(10px + env(safe-area-inset-bottom, 0px))`,
            borderTop: `1px solid ${GC.line}`,
          }}
        >
          <input
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="다른 질문을 입력하세요..."
            aria-label="질문 입력"
            style={{
              flex: 1,
              minHeight: `${touchTarget.minimum}px`,
              minWidth: 0,
              border: `1px solid ${GC.line}`,
              borderRadius: `${radius.button}px`,
              padding: '0 14px',
              fontSize: '15.5px',
              fontFamily: 'inherit',
              color: GC.text,
              background: GC.bg,
            }}
          />
          <button
            type="submit"
            aria-label="질문 보내기"
            style={{
              flex: 'none',
              width: `${touchTarget.minimum}px`,
              height: `${touchTarget.minimum}px`,
              borderRadius: '50%',
              border: 'none',
              background: GC.accent,
              color: GC.surface,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
            }}
          >
            <svg viewBox="0 0 24 24" style={{ ...ICON, width: 18, height: 18, stroke: GC.surface }}>
              <path d="M22 2 11 13" />
              <path d="m22 2-7 20-4-9-9-4Z" />
            </svg>
          </button>
        </form>
      </main>
    </>
  )
}
