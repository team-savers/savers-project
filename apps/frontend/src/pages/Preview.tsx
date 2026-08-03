// Preview (/preview?t=). Experimental staged evacuation flow — NOT wired into
// the production alert landing (Landing.tsx). This page exists so the team
// can open it, tap through, and decide whether to adopt it before it
// replaces anything in Landing.tsx. Nothing here is a contract change.
//
// Origin: a design mockup shared 2026-08-03 (경고 → 도움/혼자 갈림길 →
// 행동권고 카드 → 경로 확인 → 도착). Two things from that mockup are
// deliberately NOT implemented as shown:
//
//   1. "도움이 필요해요" in the mockup claims automatic location-sharing to
//      rescue personnel. The team decided the same day (2026-08-03 회의 3.5)
//      that 119 연계는 예선 범위에서 제외하고 자동 통보를 하지 않는다 —
//      무응답은 위험의 증거가 아니고, 오탐 비용이 비대칭이라는 이유였다.
//      So this screen offers real tel: links (119, registered guardian) that
//      the PERSON dials themselves — nothing is auto-sent.
//   2. The mockup's route screen shows fabricated turn-by-turn steps
//      ("우회전 80m"). No routing API is wired anywhere in this repo
//      (VITE_TMAP_APP_KEY is an unused placeholder — see .env.example).
//      Inventing directions here would be exactly the kind of
//      client-authored, unevidenced instruction the rest of this app is
//      built to refuse. This screen shows the real map (ShelterMap, actual
//      Kakao SDK) plus the real straight-line distance/bearing already in
//      the contract — no fake steps.
//
// Data: real session + real shelter search, same api client as Landing.tsx.
// No new contract fields, no new endpoints.
//
// 비상 도구: 화면 꺼짐 방지(Wake Lock), 진동, 손전등(화면 전체 백색),
// 경보음, 위치 공유는 전부 브라우저 표준 API로만 구현했다(useWakeLock,
// lib/emergencyTools.ts, EmergencyToolbar) — 백엔드에 새 엔드포인트나
// 데이터가 필요 없는 순수 클라이언트 기능이라 여기 없다. 화면 밝기를
// 최대로 강제하는 것은 웹에 그런 API가 없어(iOS/Android 모두 네이티브
// 셸에서만 가능) 시도하지 않았다.

import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { Profile, SessionResponse, Shelter, ShelterList, Stage as DisasterStage } from '../api/types'
import { EmergencyToolbar } from '../components/EmergencyToolbar'
import { ShelterMap } from '../components/ShelterMap'
import { DoorIcon, PowerIcon, StairsIcon } from '../components/illustrations/ChecklistIcons'
import { Mascot } from '../components/illustrations/Mascot'
import { RainAlertIllustration } from '../components/illustrations/RainAlertIllustration'
import { SafeArrivalIllustration } from '../components/illustrations/SafeArrivalIllustration'
import { useWakeLock } from '../hooks/useWakeLock'
import { vibrateSafe } from '../lib/emergencyTools'
import { bearingLabel, formatDistance } from '../lib/i18n'
import { C, MOBILE_WIDTH, SHADOW_CARD, SHADOW_CTA_TEAL, touchTarget } from '../lib/tokens'

// UI 화면 단계(intro/choice/...). 계약의 재난 심각도 `DisasterStage`(1|2|3,
// api/types.ts `Stage`)와 이름이 겹치므로 import 시 별칭을 준다 — 서로
// 다른 개념이다.
type Stage = 'intro' | 'choice' | 'help' | 'summary' | 'route' | 'arrived'

// ?stage= 로 재난 심각도를 override 한다 — 데모/발표용으로 stage 1과
// 2/3의 화면 침습성 차이를 둘 다 보여주기 위함이다. 실제 세션은 전부
// stage 2로 나온다(api/mock.ts — 지금 mock에 stage 1/3 픽스처가 없다).
// 잘못된 값이 오면 조용히 무시하고 세션의 실제 stage를 쓴다.
function readStageOverride(): DisasterStage | null {
  const raw = new URLSearchParams(window.location.search).get('stage')
  if (raw === '1' || raw === '2' || raw === '3') return Number(raw) as DisasterStage
  return null
}

// Straight-line-to-walking-time estimate. Deliberately conservative (67 m/min
// ≈ 4km/h general adult pace) and always labeled as an estimate — this is
// NOT a routed ETA, just distance/speed. See file header: no fabricated
// turn-by-turn exists here, only this one disclosed arithmetic estimate.
const WALK_M_PER_MIN = 67

function estimateMinutes(distanceM: number): number {
  return Math.max(1, Math.round(distanceM / WALK_M_PER_MIN))
}

// Generic, non-personalized safety checklist. Explicitly NOT attributed to
// 국민행동요령 or any retrieved source — labeled "일반 안전수칙" in the UI so
// it reads as a standard habit reminder, never as AI-generated or
// evidence-grounded guidance. This is the honest alternative to the mockup's
// unsourced "두꺼비집 전기 차단" checklist.
const SAFETY_CHECKLIST: Array<{ icon: React.ComponentType; text: string }> = [
  { icon: PowerIcon, text: '두꺼비집(전기) 차단' },
  { icon: DoorIcon, text: '현관문 미리 열어두기' },
  { icon: StairsIcon, text: '계단 이용, 엘리베이터 금지' },
]

interface Props {
  token: string
}

export function Preview({ token }: Props) {
  const [stage, setStage] = useState<Stage>('intro')
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [shelterList, setShelterList] = useState<ShelterList | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getSession(token)
      .then((s) => {
        if (cancelled) return
        setSession(s)
        return api.searchShelters({ sessionToken: token, dongCode: s.profile.dongCode })
      })
      .then((list) => {
        if (cancelled || list === undefined) return
        setShelterList(list)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [token])

  const profile: Profile | null = session?.profile ?? null
  const nearest: Shelter | null = shelterList?.items[0] ?? null
  const locationConfirmed = shelterList?.basis === 'coordinate'

  // 재난 심각도. Google 지진조기경보의 "Be Aware(약함) / Take Action(강함)"
  // 2단계 침습성 구분을 참고했다 — stage 1(예비특보)은 화면 전체를
  // 하자드 옐로로 덮지 않는 가벼운 배너로, stage 2/3(경보 이상)은 기존
  // 전체화면 인트로를 그대로 쓴다.
  const disasterStage: DisasterStage = readStageOverride() ?? session?.stage ?? 2

  useWakeLock(session !== null && stage !== 'arrived')

  useEffect(() => {
    if (stage === 'intro') vibrateSafe(disasterStage === 1 ? 120 : [200, 100, 200])
    if (stage === 'arrived') vibrateSafe(400)
  }, [stage, disasterStage])

  const displayTitle = useMemo(() => {
    const t = session?.message.title
    if (t === undefined || t === null) return '긴급 재난 경보'
    const stripped = t.replace(/^\[[^\]]*\]\s*/, '')
    return stripped.length > 0 ? stripped : t
  }, [session])

  if (error !== null) {
    return (
      <Frame>
        <div style={{ padding: '24px' }}>
          <p style={{ ...cardText, color: C.alertText }}>불러오지 못했습니다: {error}</p>
        </div>
      </Frame>
    )
  }

  if (session === null) {
    return (
      <Frame>
        <div style={{ padding: '24px' }}>
          <p style={cardText}>준비하고 있습니다…</p>
        </div>
      </Frame>
    )
  }

  const showToolbar = stage === 'choice' || stage === 'help' || stage === 'summary' || stage === 'route'

  return (
    <Frame>
      {showToolbar && <EmergencyToolbar nearest={nearest} />}
      {stage === 'intro' && (
        <IntroScreen title={displayTitle} disasterStage={disasterStage} onNext={() => setStage('choice')} />
      )}
      {stage === 'choice' && (
        <ChoiceScreen
          title={displayTitle}
          onBack={() => setStage('intro')}
          onHelp={() => setStage('help')}
          onAlone={() => setStage('summary')}
        />
      )}
      {stage === 'help' && (
        <HelpScreen guardian={profile?.guardian ?? null} onBack={() => setStage('choice')} />
      )}
      {stage === 'summary' && (
        <SummaryScreen
          nearest={nearest}
          locationConfirmed={locationConfirmed}
          onBack={() => setStage('choice')}
          onRoute={() => setStage('route')}
        />
      )}
      {stage === 'route' && (
        <RouteScreen nearest={nearest} onBack={() => setStage('summary')} onArrived={() => setStage('arrived')} />
      )}
      {stage === 'arrived' && <ArrivedScreen onRestart={() => setStage('intro')} />}
    </Frame>
  )
}

// ---- shared shell -------------------------------------------------------

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <main
      style={{
        width: '100%',
        maxWidth: MOBILE_WIDTH,
        margin: '0 auto',
        minHeight: '100vh',
        background: C.bg,
        fontFamily: "'Pretendard', system-ui, sans-serif",
        wordBreak: 'keep-all',
        overflowWrap: 'break-word',
      }}
    >
      {children}
    </main>
  )
}

const cardText: React.CSSProperties = {
  fontSize: '17px',
  lineHeight: 1.6,
  color: C.body,
  margin: 0,
}

function BackHeader({ onBack, dark }: { onBack: () => void; dark?: boolean }) {
  return (
    <div
      style={{
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}
    >
      <button
        type="button"
        onClick={onBack}
        style={{
          background: 'transparent',
          border: 'none',
          padding: 0,
          fontSize: '16px',
          fontWeight: 700,
          color: dark === true ? 'rgba(255,255,255,.85)' : C.hazardInk,
          cursor: 'pointer',
        }}
      >
        ← 뒤로
      </button>
      <span
        style={{
          fontSize: '13px',
          fontWeight: 700,
          letterSpacing: '.08em',
          color: dark === true ? 'rgba(255,255,255,.6)' : C.tertiary,
        }}
      >
        SAVERS
      </span>
    </div>
  )
}

function PrimaryButton({
  children,
  onClick,
  tone = 'hazard',
}: {
  children: React.ReactNode
  onClick: () => void
  tone?: 'hazard' | 'teal' | 'navy'
}) {
  // 'hazard' (검정 바탕 + 노랑 글자) is the default primary action tone —
  // directive, not alarming. Red (`C.alert`) is never used as a button fill
  // here; see the `hazard` token comment in tokens.ts for why.
  const bg = tone === 'hazard' ? C.hazardInk : tone === 'teal' ? C.tealText : C.navy
  const fg = tone === 'hazard' ? C.hazard : C.white
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: '100%',
        minHeight: `${touchTarget.ctaMin}px`,
        padding: '16px',
        fontFamily: 'inherit',
        fontSize: '17px',
        fontWeight: 800,
        letterSpacing: '-.015em',
        color: fg,
        background: bg,
        border: 'none',
        borderRadius: '14px',
        cursor: 'pointer',
        boxShadow: tone === 'teal' ? SHADOW_CTA_TEAL : '0 10px 24px -12px rgba(0,0,0,.45)',
      }}
    >
      {children}
    </button>
  )
}

function SecondaryButton({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: '100%',
        minHeight: `${touchTarget.ctaMin}px`,
        padding: '16px',
        fontFamily: 'inherit',
        fontSize: '17px',
        fontWeight: 800,
        letterSpacing: '-.015em',
        color: C.navy,
        background: C.white,
        border: `2px solid ${C.border}`,
        borderRadius: '14px',
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}

// ---- ① 경고 인트로 -------------------------------------------------------
//
// 심각도에 따라 두 화면으로 나눈다(Google 지진조기경보의 "Be Aware /
// Take Action" 2단계 침습성 구분 참고, 2026-08-04 리서치):
//   stage 1(예비특보) — IntroScreenAware. 화면을 하자드 옐로로 덮지 않는
//     가벼운 배너 카드. 아직 "지금 당장 움직이라"는 신호가 아니다.
//   stage 2/3(경보·위험 실현) — IntroScreenTakeAction(기존 화면 그대로).
//     전체화면 하자드 옐로 + 강한 진동으로 "지금 봐야 한다"를 전달.

function IntroScreen({
  title,
  disasterStage,
  onNext,
}: {
  title: string
  disasterStage: DisasterStage
  onNext: () => void
}) {
  if (disasterStage === 1) {
    return <IntroScreenAware title={title} onNext={onNext} />
  }
  return <IntroScreenTakeAction title={title} onNext={onNext} />
}

// stage 1 — 예비특보. 아직 지켜보는 단계라는 걸 색으로도 드러낸다: 배경은
// 평상시 톤(C.bg)을 유지하고, 하자드 옐로는 작은 배너 카드 안에서만 쓴다.
function IntroScreenAware({ title, onNext }: { title: string; onNext: () => void }) {
  return (
    <div style={{ minHeight: '100vh', background: C.bg, display: 'flex', flexDirection: 'column' }}>
      <BackHeader onBack={() => window.history.back()} />
      <div style={{ padding: '0 20px' }}>
        <div
          style={{
            background: C.warnBg,
            border: `1px solid ${C.warn}`,
            borderRadius: '16px',
            padding: '16px',
            display: 'flex',
            gap: '12px',
            alignItems: 'flex-start',
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '50%',
              background: C.hazard,
              color: C.hazardInk,
              flex: 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 800,
              fontSize: '15px',
            }}
          >
            !
          </span>
          <div>
            <p style={{ fontSize: '12px', fontWeight: 800, color: C.warnText, letterSpacing: '.04em', margin: '0 0 4px' }}>
              예비특보 · 아직 지켜볼 단계
            </p>
            <p style={{ fontSize: '17px', fontWeight: 800, color: C.navy, margin: 0, lineHeight: 1.4 }}>{title}</p>
          </div>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 28px' }}>
        <div style={{ width: '150px', margin: '0 auto 18px', opacity: 0.85 }}>
          <RainAlertIllustration />
        </div>
        <p style={{ fontSize: '15px', color: C.body, textAlign: 'center', lineHeight: 1.6 }}>
          아직 대피할 단계는 아니에요. 상황이 바뀌면 다시 알려드릴게요.
        </p>
      </div>
      <div style={{ padding: '20px' }}>
        <SecondaryButton onClick={onNext}>자세히 보기</SecondaryButton>
      </div>
    </div>
  )
}

// stage 2/3 — 경보·위험 실현. 기존 전체화면 하자드 옐로 인트로(변경 없음).
function IntroScreenTakeAction({ title, onNext }: { title: string; onNext: () => void }) {
  // 배경은 하자드 옐로(과속방지턱 톤) — 완전 단색이면 납작해 보인다는
  // 피드백(2026-08-04)이 있어 아주 은은한 세로 그라데이션으로 깊이를
  // 준다. 빨강은 여전히 일러스트 안 점 하나로만 남긴다 — "꼭 확인해야
  // 하는 신호"라는 의미는 유지하되, 화면 전체가 사이렌처럼 보이지 않게
  // 한다.
  return (
    <div
      style={{
        minHeight: '100vh',
        background: `linear-gradient(180deg, ${C.hazard} 0%, ${C.hazard} 55%, #E6A800 100%)`,
        color: C.hazardInk,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <BackHeader onBack={() => window.history.back()} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '0 24px' }}>
        {/* 호우·도시침수 히어로 일러스트 — MVP 재난 유형이 이 하나뿐이라
            분기 없이 고정 장면 하나를 쓴다. 유일한 레드 포인트는
            일러스트 안 우산 꼭지 점 하나(RainAlertIllustration 참고).
            첫 버전(188px)이 "휑하다"는 피드백을 받아 화면을 훨씬 더
            채우도록 키웠다. */}
        <div style={{ width: '272px', margin: '0 auto 22px' }}>
          <RainAlertIllustration />
        </div>
        <span
          style={{
            display: 'inline-flex',
            alignSelf: 'center',
            fontSize: '12.5px',
            fontWeight: 800,
            letterSpacing: '.08em',
            color: C.hazard,
            background: C.hazardInk,
            borderRadius: '20px',
            padding: '6px 14px',
            marginBottom: '12px',
          }}
        >
          긴급 재난 경보
        </span>
        <p
          style={{
            fontSize: '30px',
            fontWeight: 800,
            lineHeight: 1.3,
            letterSpacing: '-.025em',
            margin: 0,
            textAlign: 'center',
            textWrap: 'pretty',
          }}
        >
          {title}
        </p>
      </div>
      <div style={{ padding: '20px' }}>
        {/* 미세한 펄스 — 게임 QTE 디자인 리서치의 "지금 눌러야 할 것을
            시각적으로 놓치지 않게" 원칙. 사이렌·흔들림 같은 자극적인
            연출은 피하고(같은 리서치의 반면교사), 크기 1.5%만 오가는
            느린 펄스로 "여기가 지금 할 행동"이라는 신호만 준다.
            prefers-reduced-motion이면 애니메이션 자체를 끈다. */}
        <style>{`
          @keyframes savers-cta-pulse { 0%, 100% { transform: scale(1); } 50% { transform: scale(1.015); } }
          .savers-cta-pulse { animation: savers-cta-pulse 2.2s ease-in-out infinite; }
          @media (prefers-reduced-motion: reduce) { .savers-cta-pulse { animation: none; } }
        `}</style>
        <button
          type="button"
          onClick={onNext}
          className="savers-cta-pulse"
          style={{
            width: '100%',
            minHeight: `${touchTarget.ctaMin}px`,
            padding: '16px',
            fontFamily: 'inherit',
            fontSize: '18px',
            fontWeight: 800,
            color: C.hazard,
            background: C.hazardInk,
            border: 'none',
            borderRadius: '14px',
            cursor: 'pointer',
          }}
        >
          대피하기
        </button>
        <p style={{ margin: '14px 0 0', fontSize: '13px', textAlign: 'center', opacity: 0.65 }}>
          상황은 변할 수 있습니다. 재난문자와 공식 채널을 함께 확인하세요
        </p>
      </div>
    </div>
  )
}

// ---- ② 갈림길 -------------------------------------------------------------

function ChoiceScreen({
  title,
  onBack,
  onHelp,
  onAlone,
}: {
  title: string
  onBack: () => void
  onHelp: () => void
  onAlone: () => void
}) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <BackHeader onBack={onBack} />
      <div style={{ background: C.hazardInk, color: C.hazard, padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
        <span
          aria-hidden="true"
          style={{ width: '10px', height: '10px', borderRadius: '50%', background: C.alert, flex: 'none' }}
        />
        <div>
          <p style={{ fontSize: '12px', fontWeight: 700, letterSpacing: '.06em', opacity: 0.75, margin: '0 0 4px' }}>
            긴급 재난 경보
          </p>
          <p style={{ fontSize: '20px', fontWeight: 800, margin: 0, lineHeight: 1.35, color: C.white }}>{title}</p>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: '12px', padding: '24px' }}>
        <PrimaryButton tone="navy" onClick={onHelp}>
          도움이 필요해요
        </PrimaryButton>
        <SecondaryButton onClick={onAlone}>혼자서 대피할게요</SecondaryButton>
      </div>
    </div>
  )
}

// ---- 도움이 필요해요 — 정직한 버전 (자동 위치공유·자동신고 없음) -----------

function HelpScreen({ guardian, onBack }: { guardian: Profile['guardian']; onBack: () => void }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <BackHeader onBack={onBack} />
      <div style={{ flex: 1, padding: '8px 24px 24px', display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
        <p style={{ fontSize: '13px', fontWeight: 700, color: C.tertiary, margin: '0 0 8px' }}>도움 요청</p>
        <p style={{ fontSize: '24px', fontWeight: 800, color: C.navy, margin: '0 0 12px', lineHeight: 1.35 }}>
          아래 번호로 직접 전화하세요
        </p>
        <p style={{ ...cardText, margin: '0 0 24px' }}>
          자동으로 신고되거나 위치가 공유되지 않습니다. 전화를 걸면 상대가 직접 받습니다.
        </p>

        <a
          href="tel:119"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            width: '100%',
            minHeight: `${touchTarget.ctaMin}px`,
            fontSize: '18px',
            fontWeight: 800,
            color: C.white,
            background: C.hazardInk,
            borderRadius: '14px',
            textDecoration: 'none',
            marginBottom: '12px',
          }}
        >
          {/* 작은 레드 점 하나 — 이 버튼이 유일하게 "긴급" 신호를 남겨야 하는
              자리라서, 버튼 전체가 아니라 이 점 하나로만 표시한다. */}
          <span aria-hidden="true" style={{ width: '9px', height: '9px', borderRadius: '50%', background: C.alert }} />
          119 전화하기
        </a>

        {guardian !== null && (
          <a
            href={`tel:${guardian.phone}`}
            style={{
              display: 'block',
              textAlign: 'center',
              width: '100%',
              minHeight: `${touchTarget.ctaMin}px`,
              lineHeight: `${touchTarget.ctaMin}px`,
              fontSize: '17px',
              fontWeight: 800,
              color: C.navy,
              background: C.white,
              border: `2px solid ${C.border}`,
              borderRadius: '14px',
              textDecoration: 'none',
            }}
          >
            보호자({guardian.relation}) 전화하기
          </a>
        )}
      </div>
    </div>
  )
}

// ---- ③ 행동권고 카드 (요약) -----------------------------------------------

function SummaryScreen({
  nearest,
  locationConfirmed,
  onBack,
  onRoute,
}: {
  nearest: Shelter | null
  locationConfirmed: boolean | undefined
  onBack: () => void
  onRoute: () => void
}) {
  const minutes = nearest !== null ? estimateMinutes(nearest.distanceM) : null
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px' }}>
        <button
          type="button"
          onClick={onBack}
          style={{ background: 'transparent', border: 'none', padding: 0, fontSize: '16px', fontWeight: 700, color: C.alert, cursor: 'pointer' }}
        >
          ← 뒤로
        </button>
        {locationConfirmed !== true && (
          <span
            style={{
              fontSize: '12px',
              fontWeight: 700,
              color: C.warnText,
              background: C.warnBg,
              border: `1px solid ${C.warn}`,
              borderRadius: '20px',
              padding: '4px 10px',
            }}
          >
            위치 미확인 · 등록 동 기준
          </span>
        )}
      </div>

      <div style={{ padding: '4px 24px 24px', flex: 1 }}>
        <p style={{ fontSize: '13px', fontWeight: 700, color: C.tertiary, margin: '0 0 6px' }}>행동 권고</p>
        <p style={{ fontSize: '28px', fontWeight: 800, color: C.navy, margin: '0 0 20px', letterSpacing: '-.02em' }}>
          지금 출발하세요
        </p>

        {nearest !== null && minutes !== null && (
          <div
            style={{
              background: C.white,
              borderRadius: '18px',
              padding: '20px',
              boxShadow: SHADOW_CARD,
              marginBottom: '16px',
            }}
          >
            <p style={{ fontSize: '13px', color: C.tertiary, margin: '0 0 4px' }}>대피소까지 이동(추정)</p>
            <p style={{ fontSize: '38px', fontWeight: 800, color: C.navy, margin: '0 0 2px' }}>{minutes}분</p>
            <p style={{ fontSize: '13px', color: C.tertiary, margin: 0 }}>
              직선거리 {formatDistance(nearest.distanceM, 'ko')} 기준 추정치입니다
            </p>
          </div>
        )}

        <div style={{ background: C.greyBg, borderRadius: '16px', padding: '18px', marginBottom: '16px' }}>
          <p style={{ fontSize: '14px', fontWeight: 700, color: C.body, margin: '0 0 10px' }}>나가기 전 일반 안전수칙</p>
          {/* 번호(1→2→3) — 항공기 안전카드가 텍스트 없이도 순서를 전달하는
              방식(화살표/번호 시퀀스)을 참고했다. 순서대로 하나씩 하면
              된다는 걸 숫자로도 확인시킨다. */}
          <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {SAFETY_CHECKLIST.map(({ icon: Icon, text }, i) => (
              <li key={text} style={{ fontSize: '15.5px', color: C.body, display: 'flex', alignItems: 'center', gap: '10px' }}>
                <span
                  aria-hidden="true"
                  style={{
                    width: '18px',
                    height: '18px',
                    borderRadius: '50%',
                    background: C.mandatory,
                    color: C.white,
                    fontSize: '11px',
                    fontWeight: 800,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flex: 'none',
                  }}
                >
                  {i + 1}
                </span>
                <Icon />
                {text}
              </li>
            ))}
          </ul>
        </div>

        {nearest !== null && (
          <div style={{ background: C.white, borderRadius: '16px', padding: '18px', boxShadow: SHADOW_CARD }}>
            <p style={{ fontSize: '12px', fontWeight: 700, color: C.tealText, margin: '0 0 6px' }}>가장 가까운 대피소</p>
            <p style={{ fontSize: '18px', fontWeight: 800, color: C.navy, margin: '0 0 2px' }}>{nearest.name}</p>
            <p style={{ fontSize: '14px', color: C.tertiary, margin: 0 }}>
              {formatDistance(nearest.distanceM, 'ko')}
              {nearest.bearing != null ? ` · ${bearingLabel(nearest.bearing, 'ko')}쪽` : ''}
              {nearest.hasStairs ? ' · 계단 있음' : ''}
            </p>
          </div>
        )}
      </div>

      <div style={{ padding: '0 24px 24px' }}>
        <PrimaryButton onClick={onRoute}>경로 확인하기</PrimaryButton>
      </div>
    </div>
  )
}

// ---- ④ 경로 확인 (실제 지도 + 실측 거리/방향, 가짜 턴바이턴 없음) --------

// 8방위 → 회전각(도). 화살표 아이콘을 이 각만큼 돌려 "저쪽으로"를 시각화한다.
// 실제 도보 경로 각도가 아니라 직선 방위각이라는 한계는 화면 하단 문구로
// 계속 밝힌다 — 여기서는 표시 방식만 바꾼다.
const BEARING_DEG: Record<string, number> = {
  N: 0,
  NE: 45,
  E: 90,
  SE: 135,
  S: 180,
  SW: 225,
  W: 270,
  NW: 315,
}

function DirectionArrow({ degrees }: { degrees: number }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="40"
      height="40"
      style={{ transform: `rotate(${degrees}deg)`, transition: 'transform .3s ease' }}
    >
      <path d="M12 2 L19 21 L12 16.5 L5 21 Z" fill={C.white} />
    </svg>
  )
}

function RouteScreen({
  nearest,
  onBack,
  onArrived,
}: {
  nearest: Shelter | null
  onBack: () => void
  onArrived: () => void
}) {
  const degrees = nearest?.bearing != null ? (BEARING_DEG[nearest.bearing] ?? 0) : 0
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Apple Maps 턴바이턴 헤더를 참고한 방향 바. 실제 턴 안내(우회전 등)는
          없으므로 "OO쪽으로 OOm" 하나만 크게 보여준다 — 없는 정보를 지어내지
          않는다. */}
      <div style={{ background: C.navy, color: C.white, padding: '18px 20px', display: 'flex', alignItems: 'center', gap: '14px' }}>
        <button
          type="button"
          onClick={onBack}
          style={{ background: 'transparent', border: 'none', padding: 0, color: 'rgba(255,255,255,.8)', fontSize: '15px', flex: 'none' }}
        >
          ← 뒤로
        </button>
        {nearest !== null && (
          <>
            <DirectionArrow degrees={degrees} />
            <div>
              <p style={{ fontSize: '26px', fontWeight: 800, margin: 0, letterSpacing: '-.02em' }}>
                {formatDistance(nearest.distanceM, 'ko')}
              </p>
              <p style={{ fontSize: '13px', opacity: 0.75, margin: '2px 0 0' }}>
                {nearest.bearing != null ? `${bearingLabel(nearest.bearing, 'ko')}쪽 방향` : '방향 정보 없음'} · 직선거리 기준
              </p>
            </div>
            {/* 이동 중인 마스코트 — 인트로의 alert 포즈가 여기선 moving으로 이어진다. */}
            <div style={{ marginLeft: 'auto' }}>
              <Mascot pose="moving" width={44} />
            </div>
          </>
        )}
      </div>
      <div style={{ padding: '16px 20px 0', flex: 1 }}>
        {nearest !== null && nearest.lat !== undefined && nearest.lng !== undefined ? (
          <ShelterMap shelters={[nearest]} userCoord={null} lang="ko" />
        ) : (
          <div
            style={{
              background: C.greyBg,
              borderRadius: '16px',
              padding: '40px 20px',
              textAlign: 'center',
              color: C.tertiary,
            }}
          >
            지도를 표시할 좌표가 없습니다
          </div>
        )}
      </div>
      <div style={{ background: C.white, borderTop: `1px solid ${C.border}`, padding: '20px' }}>
        <p style={{ fontSize: '12px', color: C.tertiary, margin: '0 0 4px' }}>목적지</p>
        <p style={{ fontSize: '19px', fontWeight: 800, color: C.navy, margin: '0 0 16px' }}>{nearest?.name ?? '대피소'}</p>
        <PrimaryButton tone="teal" onClick={onArrived}>
          도착했어요
        </PrimaryButton>
      </div>
    </div>
  )
}

// ---- ⑤ 도착 --------------------------------------------------------------

function ArrivedScreen({ onRestart }: { onRestart: () => void }) {
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', justifyContent: 'center', padding: '28px' }}>
      <div style={{ width: '176px', margin: '0 0 18px' }}>
        <SafeArrivalIllustration />
      </div>
      <p style={{ fontSize: '13px', fontWeight: 700, color: C.tertiary, margin: '0 0 6px' }}>도착</p>
      <p style={{ fontSize: '24px', fontWeight: 800, color: C.navy, margin: '0 0 24px' }}>대피소에 도착했습니다</p>
      <SecondaryButton onClick={onRestart}>처음으로</SecondaryButton>
    </div>
  )
}
