// 대피소 도착(ArrivedScreen) 일러스트. 위기 화면과 달리 이미 안전해진
// 상태라 하자드 톤 대신 `C.safe`(안전 확인 색) 하나로 차분하게 마무리한다 —
// 여기서도 빨강은 쓰지 않는다(경고가 끝났다는 뜻). 인트로에서 우산을 쓰고
// 있던 마스코트가 여기선 safe 포즈로 건물 옆에 서 있다 — 같은 캐릭터가
// 대피를 마쳤다는 걸 보여준다.
import { C } from '../../lib/tokens'
import { MascotGraphic } from './Mascot'

export function SafeArrivalIllustration() {
  return (
    <svg viewBox="0 0 200 160" width="100%" height="auto" role="img" aria-label="비가 그친 대피소 건물">
      {/* 개는 하늘 — 은은한 방사선 */}
      {[0, 30, 60, 120, 150, 180].map((deg) => (
        <line
          key={deg}
          x1="100"
          y1="54"
          x2={100 + 62 * Math.cos((deg * Math.PI) / 180 - Math.PI / 2)}
          y2={54 + 62 * Math.sin((deg * Math.PI) / 180 - Math.PI / 2)}
          stroke={C.mintPale}
          strokeWidth="3"
          strokeLinecap="round"
          opacity="0.6"
        />
      ))}
      <circle cx="100" cy="54" r="22" fill={C.mint} opacity="0.35" />

      {/* 대피소 건물 */}
      <path d="M40 96 L100 54 L160 96 V146 H40 Z" fill={C.safe} />
      <rect x="86" y="112" width="28" height="34" fill={C.white} />
      <circle cx="106" cy="130" r="2.4" fill={C.safe} />
      <rect x="52" y="104" width="18" height="18" fill={C.white} opacity="0.9" />
      <rect x="130" y="104" width="18" height="18" fill={C.white} opacity="0.9" />

      {/* 완료 배지 */}
      <circle cx="152" cy="118" r="18" fill={C.white} />
      <circle cx="152" cy="118" r="18" fill="none" stroke={C.safe} strokeWidth="3" />
      <path d="M144 118 l6 6 l12 -13" stroke={C.safe} strokeWidth="4" fill="none" strokeLinecap="round" strokeLinejoin="round" />

      {/* 마스코트 — 건물 옆에서 safe 포즈 */}
      <g transform="translate(6 84) scale(0.46)">
        <MascotGraphic pose="safe" />
      </g>
    </svg>
  )
}
