// Mockup (/mockup) — 발표용 정적 목업 모음. 팀장 발표 자료용으로 만든
// 화면이며, 실제 API/세션 상태와 전혀 연결되지 않는다(이 파일은 ../api/*
// 를 import 하지 않는다). 모든 데이터는 하드코딩된 예시다 — 발표 중 네트
// 워크 문제로 화면이 깨지는 일이 없도록 의도적으로 그렇게 만들었다.
//
// 포함 화면 3개(2026-08-04 팀장 요청):
//   1. 보호자 현황 대시보드 — 개념안. GuardianStatus 계약 필드 형태를
//      빌렸을 뿐, `/g/{token}` 라우트는 이 저장소 스코프에 없다(App.tsx
//      15행 참고 — 2026-08-03 회의에서 보호자 에스컬레이션 자체를 개인정보
//      수집 부담으로 MVP 제외). 실제로 만들 계획이 확정된 게 아니라는 걸
//      화면 안 배지로 계속 밝힌다 — 발표 자료가 "이미 있는 기능"으로
//      오인되면 안 된다.
//   2. AI 챗봇 Q&A — ChatDock이 실제로 구현한 «근거 없으면 답하지 않는다»
//      원칙(components/ChatDock.tsx 참고)을 스크립트된 대화로 보여준다.
//      입력창은 disabled — 아무 데도 전송하지 않는다.
//   3. 관리자(Ops) 요약 카드 — 지금 Ops.tsx 현황 탭(17열 표)을 카드 4개 +
//      분포 바로 재구성한 시안. 예시 숫자이며 실제 등록 데이터가 아니다.
//   4. 잠금화면 웹 푸시 알림 — 팀 채팅(2026-08-03, YKG/도혁)에서 확정한
//      "네이티브·하이브리드 배제, 웹 푸시로 간다"는 결정과 갤럭시(Android)
//      실기기 테스트 대상을 근거로, 잠금화면에 뜨는 실제 알림 모양을
//      정지 이미지로 보여준다. 제목/본문은 sw.ts의 onBackgroundMessage가
//      그대로 표시하는 형식(data.title/data.body)을 따른다 — 지어낸
//      문구가 아니라 실제 발송 코드가 만드는 결과물의 미리보기다.
//
// 화면 구성 형식(문장 순서 등)은 PR #50 테크리드 리뷰가 정한 원칙 —
// "행동/결론을 먼저, 부연은 뒤에", "다 펼쳐도 레이아웃이 튀지 않게" —
// 을 따르되, 이 페이지 자체는 그 PR의 코드를 재사용하지 않는다(완전히
// 별도의 정적 화면).

import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { C, MOBILE_WIDTH, SHADOW_CARD, touchTarget } from '../lib/tokens'

type MockupScreen = 'guardian' | 'chat' | 'ops' | 'push'

const SCREENS: Array<{ key: MockupScreen; label: string }> = [
  { key: 'push', label: '잠금화면 알림' },
  { key: 'guardian', label: '보호자 현황' },
  { key: 'chat', label: 'AI 챗봇' },
  { key: 'ops', label: '관리자 요약' },
]

export function Mockup() {
  const [screen, setScreen] = useState<MockupScreen>('guardian')
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
      }}
    >
      <div
        style={{
          background: C.navy,
          color: C.white,
          padding: '10px 16px',
          fontSize: '12px',
          fontWeight: 700,
          textAlign: 'center',
        }}
      >
        발표용 목업 · 코드/기능 연동 없음 · 실제 동작 아님
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', padding: '14px 16px 0' }}>
        {SCREENS.map((s) => {
          const active = s.key === screen
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => setScreen(s.key)}
              style={{
                flex: '1 1 42%',
                minHeight: `${touchTarget.minimum}px`,
                padding: '8px',
                fontFamily: 'inherit',
                fontSize: '12.5px',
                fontWeight: 800,
                borderRadius: '10px',
                border: `2px solid ${active ? C.navy : C.border}`,
                background: active ? C.navy : C.white,
                color: active ? C.white : C.body,
                cursor: 'pointer',
              }}
            >
              {s.label}
            </button>
          )
        })}
      </div>

      {screen === 'push' && <LockScreenPushScreen />}
      {screen === 'guardian' && <GuardianConceptScreen />}
      {screen === 'chat' && <ChatMockupScreen />}
      {screen === 'ops' && <OpsSummaryMockupScreen />}
    </main>
  )
}

// ---- shared bits ----------------------------------------------------------

const card: CSSProperties = {
  background: C.white,
  borderRadius: '16px',
  padding: '16px',
  boxShadow: SHADOW_CARD,
}

function ConceptBadge({ children }: { children: ReactNode }) {
  return (
    <span
      style={{
        display: 'inline-block',
        fontSize: '11px',
        fontWeight: 700,
        color: C.tealText,
        background: C.tealBg,
        borderRadius: '20px',
        padding: '4px 10px',
      }}
    >
      {children}
    </span>
  )
}

// ---- 1. 보호자 현황 대시보드 (개념안) --------------------------------------

const MOCK_GUARDIAN_STATUS = {
  wardName: '김순자',
  dongName: '서원동',
  openedAt: '09:12',
  respondedAt: '09:14',
  lastResponse: '밖으로 대피 중',
}

function StatusRow({ label, value, tone }: { label: string; value: string; tone?: 'safe' }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '9px 0',
        borderBottom: `1px solid ${C.border}`,
      }}
    >
      <span style={{ fontSize: '13px', color: C.tertiary }}>{label}</span>
      <span style={{ fontSize: '14px', fontWeight: 700, color: tone === 'safe' ? C.safe : C.navy }}>{value}</span>
    </div>
  )
}

function GuardianConceptScreen() {
  const g = MOCK_GUARDIAN_STATUS
  return (
    <div style={{ padding: '20px' }}>
      <ConceptBadge>개념안 · 이번 MVP 범위 아님</ConceptBadge>
      <p style={{ fontSize: '13px', color: C.tertiary, margin: '14px 0 4px' }}>보호자 화면</p>
      <h1 style={{ fontSize: '22px', fontWeight: 800, color: C.navy, margin: '0 0 16px' }}>
        {g.wardName}님 대피 현황
      </h1>

      <div style={card}>
        <StatusRow label="거주 동" value={g.dongName} />
        <StatusRow label="알림 확인" value={`확인함 (${g.openedAt})`} tone="safe" />
        <StatusRow label="응답" value={g.lastResponse} tone="safe" />
        <StatusRow label="마지막 응답 시각" value={g.respondedAt} />
      </div>

      <div style={{ ...card, marginTop: '14px', background: C.warnBg, border: `1px solid ${C.warn}` }}>
        <p style={{ fontSize: '13px', color: C.warnText, margin: 0, lineHeight: 1.6 }}>
          ⚠ 실제로는 이 화면(/g/token)이 구현돼 있지 않습니다. 2026-08-03 회의에서
          개인정보(보호자 연락처 등) 수집 부담 때문에 30분 무응답 에스컬레이션과 함께
          MVP 범위에서 제외됐습니다 — 발표용 개념 시안입니다.
        </p>
      </div>
    </div>
  )
}

// ---- 2. AI 챗봇 Q&A (스크립트, 실제 전송 없음) -----------------------------

const MOCK_CHAT_TURNS: Array<{
  q: string
  a: string
  source?: { title: string; quote: string }
}> = [
  {
    q: '반지하인데 지금 뭐부터 해야 돼요?',
    a: '두꺼비집(전기) 차단기부터 내리고, 신발을 신은 채로 큰길 쪽 대피소로 이동하세요. 계단만 쓰고 엘리베이터는 타지 마세요.',
    source: {
      title: '행정안전부 국민행동요령 — 호우 시 국민행동요령',
      quote: '반지하 또는 지하실에 거주하는 사람은 침수 위험이 있으니 즉시 위층 또는 인근 높은 건물로 대피한다.',
    },
  },
  {
    q: '오늘 저녁에 나가도 돼요?',
    a: '죄송하지만 답변드릴 근거가 없어 안내드리기 어렵습니다. 대신 지금 확인된 가장 가까운 대피소를 안내해 드릴게요.',
  },
]

function ChatMockupScreen() {
  return (
    <div style={{ padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <ConceptBadge>스크립트 예시 · 실제 전송 없음</ConceptBadge>

      {MOCK_CHAT_TURNS.map((turn) => (
        <div key={turn.q} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div
            style={{
              alignSelf: 'flex-end',
              maxWidth: '82%',
              background: C.navy,
              color: C.white,
              borderRadius: '16px 16px 4px 16px',
              padding: '10px 14px',
              fontSize: '15px',
            }}
          >
            {turn.q}
          </div>
          <div
            style={{
              alignSelf: 'flex-start',
              maxWidth: '92%',
              background: C.white,
              boxShadow: SHADOW_CARD,
              borderRadius: '4px 18px 18px 18px',
              padding: '14px 16px',
            }}
          >
            <p style={{ margin: 0, fontSize: '15px', lineHeight: 1.6, color: C.body }}>{turn.a}</p>
            {turn.source !== undefined && (
              <div
                style={{
                  marginTop: '10px',
                  background: C.tealBg,
                  borderLeft: `4px solid ${C.tealText}`,
                  borderRadius: '0 10px 10px 0',
                  padding: '10px 12px',
                }}
              >
                <div style={{ fontSize: '12px', fontWeight: 700, color: C.tealText, marginBottom: '4px' }}>
                  {turn.source.title}
                </div>
                <div style={{ fontSize: '13px', color: C.navy, lineHeight: 1.5 }}>{turn.source.quote}</div>
              </div>
            )}
            {turn.source === undefined && (
              <p style={{ margin: '8px 0 0', fontSize: '12px', color: C.tertiary }}>
                근거 없는 답변은 만들지 않습니다 — 대신 대피소 안내로 이어집니다.
              </p>
            )}
          </div>
        </div>
      ))}

      <input
        disabled
        placeholder="질문을 입력하세요 (목업 — 전송 안 됨)"
        style={{
          minHeight: `${touchTarget.minimum}px`,
          borderRadius: '12px',
          border: `2px solid ${C.border}`,
          padding: '0 14px',
          fontSize: '14px',
          background: C.greyBg,
          color: C.tertiary,
        }}
      />
    </div>
  )
}

// ---- 3. 관리자(Ops) 대시보드 카드형 요약 ------------------------------------

const MOCK_OPS_STATS = {
  total: 24,
  sent: 21,
  responded: 15,
  noResponse: 6,
  byType: [
    { label: '거동 불편', count: 9 },
    { label: '시각 저하', count: 4 },
    { label: '독거', count: 11 },
  ],
}

function StatCard({ label, value, tone }: { label: string; value: string; tone?: 'safe' | 'teal' | 'warn' }) {
  const color = tone === 'safe' ? C.safe : tone === 'teal' ? C.tealText : tone === 'warn' ? C.warnText : C.navy
  return (
    <div style={{ ...card, textAlign: 'center' }}>
      <p style={{ fontSize: '12px', color: C.tertiary, margin: '0 0 6px' }}>{label}</p>
      <p style={{ fontSize: '22px', fontWeight: 800, color, margin: 0 }}>{value}</p>
    </div>
  )
}

function OpsSummaryMockupScreen() {
  const s = MOCK_OPS_STATS
  const sentRate = Math.round((s.sent / s.total) * 100)
  const respondRate = Math.round((s.responded / s.total) * 100)
  return (
    <div style={{ padding: '16px' }}>
      <ConceptBadge>Ops.tsx 현황 탭 재구성 시안 · 예시 숫자</ConceptBadge>
      <p style={{ fontSize: '13px', color: C.tertiary, margin: '14px 0 10px' }}>오늘의 발송 현황</p>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '14px' }}>
        <StatCard label="총 등록" value={`${s.total}명`} />
        <StatCard label="발송 완료" value={`${sentRate}%`} tone="safe" />
        <StatCard label="응답 완료" value={`${respondRate}%`} tone="teal" />
        <StatCard label="미응답" value={`${s.noResponse}명`} tone="warn" />
      </div>

      <div style={card}>
        <p style={{ fontSize: '14px', fontWeight: 700, color: C.body, margin: '0 0 10px' }}>취약 유형 분포</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {s.byType.map((t) => (
            <div key={t.label} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ width: '64px', fontSize: '13px', color: C.body, flex: 'none' }}>{t.label}</span>
              <div style={{ flex: 1, height: '8px', borderRadius: '4px', background: C.greyBg, overflow: 'hidden' }}>
                <div style={{ width: `${(t.count / s.total) * 100}%`, height: '100%', background: C.tealText }} />
              </div>
              <span style={{ fontSize: '13px', color: C.tertiary, flex: 'none' }}>{t.count}명</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ---- 4. 잠금화면 웹 푸시 알림 -----------------------------------------------

// sw.ts의 onBackgroundMessage가 실제로 표시하는 제목/본문 형식(data.title /
// data.body)과 같은 문구. 이 화면이 지어낸 카피가 아니라 실제 발송 코드가
// 만드는 결과물의 미리보기라는 걸 유지하기 위해 mock.ts의 예시 문구를 그대로
// 옮겼다(api/mock.ts 참고).
const MOCK_PUSH = {
  time: '09:12',
  date: '2026년 8월 4일 화요일',
  title: '[세이버스] 서원동 호우경보',
  body: '김순자님, 지금 신발을 신고 이동 준비를 하세요.',
}

function LockScreenPushScreen() {
  const p = MOCK_PUSH
  return (
    <div style={{ padding: '16px' }}>
      <ConceptBadge>실기기 배치 참고용 · 실제 알림 아님</ConceptBadge>
      <p style={{ fontSize: '13px', color: C.tertiary, margin: '14px 0 10px', lineHeight: 1.6 }}>
        갤럭시(Android) 잠금화면 웹 푸시 예시 — 팀 채팅(2026-08-03)에서 네이티브·하이브리드
        대신 웹 푸시로 확정.
      </p>

      <div
        style={{
          borderRadius: '28px',
          background: 'linear-gradient(180deg, #14293f 0%, #0a1626 100%)',
          padding: '36px 18px 24px',
          minHeight: '480px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          boxShadow: SHADOW_CARD,
        }}
      >
        <p style={{ color: 'rgba(255,255,255,.55)', fontSize: '13px', margin: '0 0 4px' }}>{p.date}</p>
        <p style={{ color: C.white, fontSize: '52px', fontWeight: 200, margin: '0 0 28px', letterSpacing: '-0.02em' }}>
          {p.time}
        </p>

        <div
          style={{
            width: '100%',
            background: 'rgba(255,255,255,.95)',
            borderRadius: '18px',
            padding: '14px 16px',
            boxShadow: '0 10px 30px -12px rgba(0,0,0,.5)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <span
              aria-hidden="true"
              style={{
                width: '20px',
                height: '20px',
                borderRadius: '6px',
                background: C.hazardInk,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none',
              }}
            >
              <span style={{ color: C.hazard, fontSize: '12px', fontWeight: 800, lineHeight: 1 }}>!</span>
            </span>
            <span style={{ fontSize: '12px', fontWeight: 700, color: '#555' }}>SAVERS</span>
            <span style={{ fontSize: '11px', color: '#999', marginLeft: 'auto' }}>지금</span>
          </div>
          <p style={{ fontSize: '15px', fontWeight: 800, color: '#111', margin: '0 0 3px', lineHeight: 1.35 }}>
            {p.title}
          </p>
          <p style={{ fontSize: '13.5px', color: '#333', margin: 0, lineHeight: 1.4 }}>{p.body}</p>
        </div>

        <p style={{ color: 'rgba(255,255,255,.4)', fontSize: '12px', marginTop: 'auto', paddingTop: '36px', textAlign: 'center' }}>
          탭하면 잠금 해제 후 대피 안내 화면으로 이동합니다
        </p>
      </div>
    </div>
  )
}
