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
//   5. 우리 동네 위험도 — 개념안(2026-08-04, uibowl.io "AMOU" 지역별
//      수치 버블 + 운세 앱 스타일 오늘의 점수/추이 참고). 실제 기상청
//      강수량 API는 연동돼 있지 않다 — Home.tsx 푸터의 "기상청 특보 API"
//      는 데이터 출처 표기일 뿐, 지역별 실시간 강수량을 끌어오는
//      코드는 이 저장소 어디에도 없다. 그래서 지역명·mm·위험도 점수 전부
//      예시 숫자이며, 배지로 계속 밝힌다.
//
// 화면 구성 형식(문장 순서 등)은 PR #50 테크리드 리뷰가 정한 원칙 —
// "행동/결론을 먼저, 부연은 뒤에", "다 펼쳐도 레이아웃이 튀지 않게" —
// 을 따르되, 이 페이지 자체는 그 PR의 코드를 재사용하지 않는다(완전히
// 별도의 정적 화면).

import { useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { C, MOBILE_WIDTH, SHADOW_CARD, touchTarget } from '../lib/tokens'

type MockupScreen = 'guardian' | 'chat' | 'ops' | 'push' | 'rainfall'
// 'all' — 4개 화면을 세로로 쭉 이어 붙여 스크롤 한 번으로 전부 비교해서
// 본다(팀장 피드백 — 탭으로 하나씩 넘기면 직관적으로 비교하기 힘들다).
// 'single' — 기존 탭 전환 방식. 발표 중 한 화면씩 짚어가며 설명할 때 쓴다.
type ViewMode = 'all' | 'single'

const SCREENS: Array<{ key: MockupScreen; label: string; render: () => ReactNode }> = [
  { key: 'push', label: '잠금화면 알림', render: () => <LockScreenPushScreen /> },
  { key: 'rainfall', label: '동네 위험도', render: () => <RainfallRiskMockupScreen /> },
  { key: 'guardian', label: '보호자 현황', render: () => <GuardianConceptScreen /> },
  { key: 'chat', label: 'AI 챗봇', render: () => <ChatMockupScreen /> },
  { key: 'ops', label: '관리자 요약', render: () => <OpsSummaryMockupScreen /> },
]

export function Mockup() {
  // 기본값을 'all'로 둔다 — "직관적으로 보기 너무 힘들다"는 피드백이 탭
  // 전환 방식(하나씩만 보임) 때문이었으므로, 처음 열었을 때부터 전체가
  // 한 번에 보이는 쪽을 기본으로 한다.
  const [viewMode, setViewMode] = useState<ViewMode>('all')
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

      <div style={{ display: 'flex', gap: '8px', padding: '14px 16px 0' }}>
        <ModeButton label="전체 보기" active={viewMode === 'all'} onClick={() => setViewMode('all')} />
        <ModeButton label="한 화면씩 보기" active={viewMode === 'single'} onClick={() => setViewMode('single')} />
      </div>

      {viewMode === 'single' && (
        <>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', padding: '10px 16px 0' }}>
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
          {SCREENS.find((s) => s.key === screen)?.render()}
        </>
      )}

      {viewMode === 'all' && (
        <div>
          {SCREENS.map((s, i) => (
            <section key={s.key}>
              <div
                style={{
                  position: 'sticky',
                  top: 0,
                  zIndex: 5,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  padding: '10px 16px',
                  marginTop: i === 0 ? '10px' : '20px',
                  background: C.tealDeep,
                  color: C.white,
                }}
              >
                <span
                  style={{
                    fontSize: '11px',
                    fontWeight: 800,
                    background: 'rgba(255,255,255,.2)',
                    borderRadius: '10px',
                    padding: '2px 8px',
                  }}
                >
                  {i + 1}/{SCREENS.length}
                </span>
                <span style={{ fontSize: '14px', fontWeight: 800 }}>{s.label}</span>
              </div>
              {s.render()}
            </section>
          ))}
        </div>
      )}
    </main>
  )
}

function ModeButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        flex: 1,
        minHeight: `${touchTarget.minimum}px`,
        padding: '8px',
        fontFamily: 'inherit',
        fontSize: '13px',
        fontWeight: 800,
        borderRadius: '10px',
        border: `2px solid ${active ? C.tealText : C.border}`,
        background: active ? C.tealText : C.white,
        color: active ? C.white : C.body,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
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

// 최근 알림 이력 — wwit.design "알림" 패턴(아이콘 + 카테고리 라벨 + 제목 +
// 상대시간)을 참고했다. GuardianStatus 계약 필드(openedAt/respondedAt/
// lastResponse)로 실제 나올 수 있는 이벤트만 나열한다 — 지어낸 알림 종류는
// 없다.
const MOCK_NOTIFICATION_HISTORY: Array<{ icon: string; category: string; title: string; time: string }> = [
  { icon: '🌧️', category: '재난 경보', title: '서원동 호우경보 발령', time: '09:10' },
  { icon: '📍', category: '열람', title: '안내 링크를 열어 확인함', time: '09:12' },
  { icon: '✅', category: '응답', title: '"밖으로 대피 중" 응답', time: '09:14' },
]

function NotificationHistoryList({ items }: { items: typeof MOCK_NOTIFICATION_HISTORY }) {
  return (
    <div style={card}>
      <p style={{ fontSize: '14px', fontWeight: 700, color: C.body, margin: '0 0 12px' }}>최근 알림 이력</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {items.map((item, i) => (
          <div
            key={item.title}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
              padding: '8px 0',
              borderBottom: i < items.length - 1 ? `1px solid ${C.border}` : 'none',
            }}
          >
            <span
              aria-hidden="true"
              style={{
                width: '32px',
                height: '32px',
                borderRadius: '10px',
                background: C.tealBg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '15px',
                flex: 'none',
              }}
            >
              {item.icon}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: '11px', fontWeight: 700, color: C.tealText, margin: '0 0 2px' }}>
                {item.category}
              </p>
              <p style={{ fontSize: '13.5px', color: C.navy, margin: 0 }}>{item.title}</p>
            </div>
            <span style={{ fontSize: '12px', color: C.tertiary, flex: 'none' }}>{item.time}</span>
          </div>
        ))}
      </div>
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

      <div style={{ marginTop: '14px' }}>
        <NotificationHistoryList items={MOCK_NOTIFICATION_HISTORY} />
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

// 도넛차트 색상 3개 — 관리자(비긴급) 화면이라 하자드/알럿 톤을 쓰지 않고
// 차분한 틸·네이비 계열로만 구성한다(wwit.design "알림" 패턴에서 참고한
// 소비 리포트 카드의 도넛+인사이트 조합).
const DISTRIBUTION_COLORS = [C.tealText, C.navy, C.mint]

function DonutChart({
  segments,
  size = 116,
  strokeWidth = 20,
}: {
  segments: Array<{ label: string; count: number; color: string }>
  size?: number
  strokeWidth?: number
}) {
  const total = segments.reduce((sum, seg) => sum + seg.count, 0)
  const radius = (size - strokeWidth) / 2
  const circumference = 2 * Math.PI * radius
  let offset = 0
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} style={{ transform: 'rotate(-90deg)', flex: 'none' }}>
      <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={C.greyBg} strokeWidth={strokeWidth} />
      {segments.map((seg) => {
        const frac = total > 0 ? seg.count / total : 0
        const dash = frac * circumference
        const dashOffset = -offset
        offset += dash
        return (
          <circle
            key={seg.label}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={seg.color}
            strokeWidth={strokeWidth}
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeDashoffset={dashOffset}
          />
        )
      })}
    </svg>
  )
}

function OpsSummaryMockupScreen() {
  const s = MOCK_OPS_STATS
  const sentRate = Math.round((s.sent / s.total) * 100)
  const respondRate = Math.round((s.responded / s.total) * 100)

  const byTypeWithColor = s.byType.map((t, i) => ({ ...t, color: DISTRIBUTION_COLORS[i % DISTRIBUTION_COLORS.length] }))
  const top = byTypeWithColor.reduce((max, t) => (t.count > max.count ? t : max), byTypeWithColor[0])
  const topPct = Math.round((top.count / s.total) * 100)

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
        <p style={{ fontSize: '14px', fontWeight: 700, color: C.body, margin: '0 0 4px' }}>취약 유형 분포</p>
        {/* 인사이트 한 줄 — wwit.design 소비 리포트의 "가장 많은 돈을 쓴 곳은
            운동이네요" 문장 패턴. 계산값 그대로 문장화한 것이라 지어낸
            분석이 아니다. */}
        <p style={{ fontSize: '13px', color: C.tealDeep, margin: '0 0 14px', lineHeight: 1.5 }}>
          가장 큰 비중은 <strong>{top.label}</strong>이에요 ({topPct}%)
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <DonutChart segments={byTypeWithColor} />
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {byTypeWithColor.map((t) => (
              <div key={t.label} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span
                  aria-hidden="true"
                  style={{ width: '10px', height: '10px', borderRadius: '50%', background: t.color, flex: 'none' }}
                />
                <span style={{ fontSize: '13px', color: C.body, flex: 1 }}>{t.label}</span>
                <span style={{ fontSize: '13px', fontWeight: 700, color: C.navy }}>
                  {Math.round((t.count / s.total) * 100)}%
                </span>
              </div>
            ))}
          </div>
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

// ---- 5. 우리 동네 위험도 (개념안) -------------------------------------------
//
// uibowl.io의 지역별 수치 버블 지도(부동산 매물 수 표시 패턴)와 운세 앱의
// "오늘의 점수 + 요일 탭 + 추이" 포맷을 참고했다(2026-08-04). 실제
// 좌표 기반 지도가 아니라 버블을 흩뿌린 개념 레이아웃이다 — 실제 기상청
// 강수량 API 연동이 없으므로 가짜 지도를 진짜처럼 보이게 만들지 않는다.

type RainfallSeverity = 'high' | 'mid' | 'low'

const MOCK_RAINFALL_AREAS: Array<{ name: string; mm: number; severity: RainfallSeverity; x: number; y: number }> = [
  { name: '서원동', mm: 92, severity: 'mid', x: 46, y: 40 },
  { name: '신림동', mm: 195, severity: 'high', x: 20, y: 22 },
  { name: '봉천동', mm: 43, severity: 'low', x: 72, y: 18 },
  { name: '조원동', mm: 149, severity: 'high', x: 62, y: 58 },
  { name: '난곡동', mm: 12, severity: 'low', x: 30, y: 66 },
  { name: '신대방동', mm: 57, severity: 'mid', x: 82, y: 44 },
]

function severityStyle(s: RainfallSeverity): { bg: string; border: string; text: string } {
  if (s === 'high') return { bg: C.alertBg, border: C.alertBorder, text: C.alertText }
  if (s === 'mid') return { bg: C.warnBg, border: C.warn, text: C.warnText }
  return { bg: C.tealBg, border: C.tealText, text: C.tealDeep }
}

function RainfallBubble({ name, mm, severity }: { name: string; mm: number; severity: RainfallSeverity }) {
  const tone = severityStyle(severity)
  // 버블 지름을 mm값에 비례해 살짝만 키운다 — 과장하면 오독 위험이 있어
  // 40~68px 범위로만 눌러둔다.
  const size = 40 + Math.min(28, Math.round(mm / 8))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '6px' }}>
      <div
        style={{
          width: `${size}px`,
          height: `${size}px`,
          borderRadius: '50%',
          background: tone.bg,
          border: `2px solid ${tone.border}`,
          color: tone.text,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '14px',
          fontWeight: 800,
        }}
      >
        {mm}
      </div>
      <span style={{ fontSize: '11.5px', color: C.tertiary }}>{name}</span>
    </div>
  )
}

const MOCK_RISK_TREND: Array<{ day: string; score: number }> = [
  { day: '그제', score: 34 },
  { day: '어제', score: 52 },
  { day: '오늘', score: 78 },
  { day: '내일', score: 61 },
  { day: '모레', score: 40 },
]

function riskInsight(score: number): string {
  if (score >= 70) return '위험도가 높아요. 대피 경로를 미리 확인해두세요.'
  if (score >= 40) return '지켜봐야 하는 수준이에요.'
  return '오늘은 비교적 낮은 편이에요.'
}

function RiskTrendChart({ points }: { points: Array<{ day: string; score: number }> }) {
  const w = 280
  const h = 64
  const max = 100
  const step = w / (points.length - 1)
  const coords = points.map((p, i) => [i * step, h - (p.score / max) * h] as const)
  const linePath = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x} ${y}`).join(' ')
  const areaPath = `${linePath} L${w} ${h} L0 ${h} Z`
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none">
      <path d={areaPath} fill={C.tealBg} />
      <path d={linePath} stroke={C.tealText} strokeWidth="2" fill="none" />
      {coords.map(([x, y], i) => (
        <circle key={points[i].day} cx={x} cy={y} r={points[i].day === '오늘' ? 4 : 2.5} fill={C.tealText} />
      ))}
    </svg>
  )
}

function RainfallRiskMockupScreen() {
  const [selectedDay, setSelectedDay] = useState('오늘')
  const selected = MOCK_RISK_TREND.find((p) => p.day === selectedDay) ?? MOCK_RISK_TREND[2]

  return (
    <div style={{ padding: '16px' }}>
      <ConceptBadge>개념안 · 기상청 API 미연동 · 예시 지역·수치</ConceptBadge>

      <p style={{ fontSize: '13px', color: C.tertiary, margin: '14px 0 10px' }}>주변 동네 예상 강수량(mm)</p>
      <div
        style={{
          position: 'relative',
          background: C.greyBg,
          borderRadius: '18px',
          height: '220px',
          overflow: 'hidden',
        }}
      >
        {MOCK_RAINFALL_AREAS.map((a) => (
          <div key={a.name} style={{ position: 'absolute', left: `${a.x}%`, top: `${a.y}%`, transform: 'translate(-50%, -50%)' }}>
            <RainfallBubble name={a.name} mm={a.mm} severity={a.severity} />
          </div>
        ))}
      </div>

      <div style={{ ...card, marginTop: '14px' }}>
        <p style={{ fontSize: '13px', color: C.tertiary, margin: '0 0 4px' }}>오늘의 침수 위험도</p>
        <p style={{ fontSize: '17px', fontWeight: 800, color: C.navy, margin: '0 0 14px' }}>서원동 요약</p>

        <div style={{ display: 'flex', gap: '6px', marginBottom: '18px' }}>
          {MOCK_RISK_TREND.map((p) => {
            const active = p.day === selectedDay
            return (
              <button
                key={p.day}
                type="button"
                onClick={() => setSelectedDay(p.day)}
                style={{
                  flex: 1,
                  padding: '8px 4px',
                  fontSize: '12.5px',
                  fontWeight: active ? 800 : 600,
                  color: active ? C.white : C.tertiary,
                  background: active ? C.tealText : 'transparent',
                  border: 'none',
                  borderRadius: '10px',
                  cursor: 'pointer',
                }}
              >
                {p.day}
              </button>
            )
          })}
        </div>

        <RiskTrendChart points={MOCK_RISK_TREND} />

        <p style={{ fontSize: '44px', fontWeight: 800, color: C.navy, margin: '14px 0 4px', letterSpacing: '-.02em' }}>
          {selected.score}
        </p>
        <p style={{ fontSize: '14px', color: C.body, margin: 0, lineHeight: 1.6 }}>{riskInsight(selected.score)}</p>
      </div>
    </div>
  )
}
