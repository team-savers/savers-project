// 호우·도시침수 경보 히어로 일러스트 (IntroScreen). MVP 재난 유형이
// 호우·도시침수 단일종이라(openapi.yaml 참고) 재난별 분기 없이 이 한 장면만
// 쓴다. 하자드 옐로/잉크 듀오톤 팔레트를 그대로 따르고, 빨강은 우산 꼭지의
// 점 하나로만 남겨 기존 "레드는 작은 경고 신호 하나만" 원칙을 유지한다.
// 우산 아래엔 세이버스 마스코트(alert 포즈)가 서 있다 — RouteScreen·
// ArrivedScreen에도 같은 캐릭터가 다른 포즈로 등장해 화면이 바뀌어도
// "함께 대피하는 중"이라는 연속성을 준다.
import { C } from '../../lib/tokens'
import { MascotGraphic } from './Mascot'

export function RainAlertIllustration() {
  return (
    <svg viewBox="0 0 240 200" width="100%" height="auto" role="img" aria-label="호우로 물이 차오르는 도시 위에 우산을 쓴 모습">
      {/* 도시 실루엣 */}
      <rect x="8" y="96" width="34" height="70" fill={C.hazardInk} opacity="0.9" />
      <rect x="16" y="106" width="8" height="10" fill={C.hazard} />
      <rect x="16" y="122" width="8" height="10" fill={C.hazard} />
      <rect x="28" y="106" width="8" height="10" fill={C.hazard} />

      <rect x="46" y="76" width="30" height="90" fill={C.hazardInk} />
      <rect x="53" y="88" width="7" height="9" fill={C.hazard} />
      <rect x="53" y="104" width="7" height="9" fill={C.hazard} />
      <rect x="53" y="120" width="7" height="9" fill={C.hazard} />
      <rect x="65" y="88" width="7" height="9" fill={C.hazard} />
      <rect x="65" y="104" width="7" height="9" fill={C.hazard} />

      <rect x="194" y="90" width="32" height="76" fill={C.hazardInk} opacity="0.9" />
      <rect x="202" y="100" width="7" height="9" fill={C.hazard} />
      <rect x="202" y="116" width="7" height="9" fill={C.hazard} />
      <rect x="214" y="100" width="7" height="9" fill={C.hazard} />

      {/* 빗줄기 */}
      {[20, 55, 95, 130, 165, 200].map((x, i) => (
        <line
          key={x}
          x1={x}
          y1={10 + (i % 2) * 8}
          x2={x - 10}
          y2={50 + (i % 2) * 8}
          stroke={C.hazardInk}
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.55"
        />
      ))}

      {/* 차오른 물 */}
      <path d="M0 172 Q30 164 60 172 T120 172 T180 172 T240 172 V200 H0 Z" fill={C.hazardInk} opacity="0.9" />
      <path d="M0 178 Q30 172 60 178 T120 178 T180 178 T240 178 V200 H0 Z" fill={C.hazardInk} />

      {/* 우산 */}
      <path d="M70 150 Q120 96 170 150 Z" fill={C.hazardInk} />
      <path d="M78 148 Q120 112 162 148" stroke={C.hazard} strokeWidth="4" fill="none" strokeLinecap="round" />
      {/* 유일한 레드 포인트 — 우산 꼭지 */}
      <circle cx="120" cy="94" r="6" fill={C.alert} />

      {/* 마스코트 — 우산 아래 서 있는 모습. 발끝이 물에 살짝 닿는 높이로
          맞춘다(우산 안쪽 곡선과 침수선 사이 공간에 맞춰 축소). */}
      <g transform="translate(104 132) scale(0.3)">
        <MascotGraphic pose="alert" />
      </g>
    </svg>
  )
}
