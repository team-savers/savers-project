// 호우·도시침수 경보 히어로 일러스트 (IntroScreen). MVP 재난 유형이
// 호우·도시침수 단일종이라(openapi.yaml 참고) 재난별 분기 없이 이 한 장면만
// 쓴다. 하자드 옐로/잉크 듀오톤 팔레트를 그대로 따르고, 빨강은 우산 꼭지의
// 점 하나로만 남겨 기존 "레드는 작은 경고 신호 하나만" 원칙을 유지한다.
// 우산 아래엔 세이버스 마스코트(alert 포즈)가 서 있다 — RouteScreen·
// ArrivedScreen에도 같은 캐릭터가 다른 포즈로 등장해 화면이 바뀌어도
// "함께 대피하는 중"이라는 연속성을 준다.
//
// 2026-08-04 리디자인: 첫 버전이 "휑하다"는 피드백을 받아 디테일을
// 채웠다 — 건물 6채(높이·창문 랜덤 배치), 빗줄기에 살짝 떨어지는
// 애니메이션(prefers-reduced-motion 존중), 마스코트 발밑 물웅덩이
// 반사, 물결에 하이라이트 레이어. 화려함은 늘렸지만 팔레트·레드 규칙은
// 그대로다.
import { C } from '../../lib/tokens'
import { MascotGraphic } from './Mascot'

// 건물 하나: x, 폭, 지붕 y(꼭대기), 창문 배치(행×열 중 켜진 자리).
const BUILDINGS: Array<{ x: number; w: number; top: number; lit: Array<[number, number]> }> = [
  { x: 4, w: 30, top: 108, lit: [[0, 0], [1, 0], [0, 1]] },
  { x: 40, w: 26, top: 130, lit: [[0, 0], [1, 1]] },
  { x: 70, w: 34, top: 82, lit: [[0, 0], [0, 1], [1, 0], [1, 1], [0, 2]] },
  { x: 148, w: 28, top: 118, lit: [[0, 0], [1, 1]] },
  { x: 180, w: 32, top: 90, lit: [[0, 0], [1, 0], [0, 1], [1, 2]] },
  { x: 214, w: 24, top: 138, lit: [[0, 0]] },
]
const GROUND_Y = 172
const WINDOW = 6.5

function Building({ x, w, top, lit }: (typeof BUILDINGS)[number]) {
  return (
    <g>
      <rect x={x} y={top} width={w} height={GROUND_Y - top} fill={C.hazardInk} />
      {lit.map(([col, row]) => (
        <rect
          key={`${col}-${row}`}
          x={x + 6 + col * (WINDOW + 5)}
          y={top + 10 + row * (WINDOW + 6)}
          width={WINDOW}
          height={WINDOW}
          fill={C.hazard}
        />
      ))}
    </g>
  )
}

// 빗줄기: 길이·기울기·불투명도를 조금씩 다르게 섞어서 손으로 그린 듯한
// 밀도를 준다. CSS 애니메이션으로 아주 살짝 떨어지는 느낌만 더하고,
// prefers-reduced-motion이면 정지 이미지로 남는다(<style> 미디어쿼리).
const RAIN: Array<{ x: number; len: number; opacity: number; delay: number }> = [
  { x: 14, len: 34, opacity: 0.5, delay: 0 },
  { x: 34, len: 26, opacity: 0.35, delay: 0.3 },
  { x: 58, len: 40, opacity: 0.55, delay: 0.6 },
  { x: 82, len: 30, opacity: 0.4, delay: 0.15 },
  { x: 106, len: 36, opacity: 0.5, delay: 0.45 },
  { x: 130, len: 24, opacity: 0.35, delay: 0.75 },
  { x: 154, len: 38, opacity: 0.55, delay: 0.2 },
  { x: 178, len: 28, opacity: 0.4, delay: 0.5 },
  { x: 202, len: 34, opacity: 0.5, delay: 0.05 },
  { x: 222, len: 22, opacity: 0.35, delay: 0.65 },
]

export function RainAlertIllustration() {
  return (
    <svg viewBox="0 0 240 210" width="100%" height="auto" role="img" aria-label="호우로 물이 차오르는 도시 위에 우산을 쓴 모습">
      <style>{`
        @keyframes savers-rain-fall { 0% { transform: translateY(-4px); } 100% { transform: translateY(6px); } }
        .savers-rain-drop { animation: savers-rain-fall 0.9s ease-in-out infinite alternate; }
        @media (prefers-reduced-motion: reduce) { .savers-rain-drop { animation: none; } }
      `}</style>

      {/* 배경은 투명 — 화면(IntroScreenTakeAction)의 그라데이션 위에 바로
          얹혀서 일러스트 사각형 테두리가 도드라지지 않게 한다. */}

      {/* 도시 실루엣 — 건물 6채, 높이·창문을 다르게 */}
      {BUILDINGS.map((b) => (
        <Building key={b.x} {...b} />
      ))}

      {/* 빗줄기 */}
      {RAIN.map((r) => (
        <line
          key={r.x}
          className="savers-rain-drop"
          x1={r.x}
          y1={4}
          x2={r.x - 9}
          y2={4 + r.len}
          stroke={C.hazardInk}
          strokeWidth="2.6"
          strokeLinecap="round"
          opacity={r.opacity}
          style={{ animationDelay: `${r.delay}s`, transformOrigin: `${r.x}px 4px` }}
        />
      ))}

      {/* 차오른 물 — 두 겹 물결 + 하이라이트 라인으로 표면 질감을 준다 */}
      <path d="M0 172 Q30 164 60 172 T120 172 T180 172 T240 172 V210 H0 Z" fill={C.hazardInk} opacity="0.85" />
      <path d="M0 180 Q30 174 60 180 T120 180 T180 180 T240 180 V210 H0 Z" fill={C.hazardInk} />
      <path
        d="M4 173 Q30 166 60 173 T120 173 T180 173 T236 173"
        stroke={C.hazard}
        strokeWidth="1.5"
        fill="none"
        opacity="0.25"
      />

      {/* 마스코트 발밑 물웅덩이 반사 — 땅에 붙어 있는 느낌을 준다 */}
      <ellipse cx="120" cy="181" rx="26" ry="5" fill={C.hazardInk} opacity="0.35" />

      {/* 우산 */}
      <path d="M68 152 Q120 94 172 152 Z" fill={C.hazardInk} />
      <path d="M77 150 Q120 114 163 150" stroke={C.hazard} strokeWidth="4" fill="none" strokeLinecap="round" />
      {/* 유일한 레드 포인트 — 우산 꼭지 */}
      <circle cx="120" cy="92" r="6" fill={C.alert} />

      {/* 마스코트 — 우산 아래 서 있는 모습. 발끝이 물에 살짝 닿는 높이로
          맞춘다(우산 안쪽 곡선과 침수선 사이 공간에 맞춰 축소). */}
      <g transform="translate(102 130) scale(0.33)">
        <MascotGraphic pose="alert" />
      </g>
    </svg>
  )
}
