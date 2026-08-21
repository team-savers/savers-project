// SAVERS 마스코트 — 물방울 모양 캐릭터. 인트로(경보) · 경로(이동 중) ·
// 도착(안전) 세 포즈로 같은 몸통을 재사용해 화면이 바뀌어도 "같은 캐릭터가
// 함께 대피하고 있다"는 연속성을 준다. 몸통 도형은 고정, 표정·팔다리
// 각도만 포즈별로 바뀐다. 색은 기존 하자드 잉크/옐로만 쓰고 빨강은 쓰지
// 않는다 — 빨강은 이 세션에서 정한 대로 각 장면의 단 하나뿐인 경고 점
// 자리를 위해 남겨둔다.
import { C } from '../../lib/tokens'

export type MascotPose = 'alert' | 'moving' | 'safe'

/** 재사용 가능한 도형 묶음 — 다른 일러스트 안에 <g transform="..."> 로 얹어 쓴다. */
export function MascotGraphic({ pose }: { pose: MascotPose }) {
  return (
    <g>
      {/* 몸통 — 물방울 실루엣 */}
      <path d="M55 6 C82 40 100 66 100 90 a45 45 0 1 1 -90 0 C10 66 28 40 55 6 Z" fill={C.hazardInk} />
      <ellipse cx="55" cy="98" rx="28" ry="24" fill={C.hazard} opacity="0.16" />

      {/* 팔 */}
      {pose === 'moving' && (
        <>
          <path d="M22 90 Q2 80 0 60" stroke={C.hazardInk} strokeWidth="9" fill="none" strokeLinecap="round" />
          <path d="M88 90 Q110 100 108 120" stroke={C.hazardInk} strokeWidth="9" fill="none" strokeLinecap="round" />
        </>
      )}
      {pose === 'safe' && (
        <>
          <path d="M20 88 Q2 70 10 50" stroke={C.hazardInk} strokeWidth="9" fill="none" strokeLinecap="round" />
          <path d="M90 88 Q108 70 100 50" stroke={C.hazardInk} strokeWidth="9" fill="none" strokeLinecap="round" />
        </>
      )}
      {pose === 'alert' && (
        <>
          <path d="M18 94 Q0 92 -4 106" stroke={C.hazardInk} strokeWidth="9" fill="none" strokeLinecap="round" />
          <path d="M92 94 Q110 92 114 106" stroke={C.hazardInk} strokeWidth="9" fill="none" strokeLinecap="round" />
        </>
      )}

      {/* 다리 */}
      {pose === 'moving' ? (
        <path d="M40 130 L32 140 M70 130 L80 138" stroke={C.hazardInk} strokeWidth="9" strokeLinecap="round" />
      ) : (
        <path d="M40 132 L40 140 M70 132 L70 140" stroke={C.hazardInk} strokeWidth="9" strokeLinecap="round" />
      )}

      {/* 얼굴 */}
      {pose === 'safe' ? (
        <>
          <path d="M36 78 q6 -9 12 0" stroke={C.white} strokeWidth="4" fill="none" strokeLinecap="round" />
          <path d="M62 78 q6 -9 12 0" stroke={C.white} strokeWidth="4" fill="none" strokeLinecap="round" />
          <path d="M40 90 q15 14 30 0" stroke={C.white} strokeWidth="4" fill="none" strokeLinecap="round" />
        </>
      ) : (
        <>
          <circle cx="42" cy="76" r="6" fill={C.white} />
          <circle cx="42" cy="77" r="3" fill={C.hazardInk} />
          <circle cx="68" cy="76" r="6" fill={C.white} />
          <circle cx="68" cy="77" r="3" fill={C.hazardInk} />
          {pose === 'alert' ? (
            <path d="M40 96 q15 -6 30 0" stroke={C.white} strokeWidth="4" fill="none" strokeLinecap="round" />
          ) : (
            <ellipse cx="55" cy="95" rx="7" ry="5" fill={C.white} />
          )}
        </>
      )}
    </g>
  )
}

/** 독립적으로 쓸 때(예: 헤더 옆 작은 마스코트)의 래퍼. */
export function Mascot({ pose, width = 60 }: { pose: MascotPose; width?: number }) {
  const height = Math.round(width * (140 / 110))
  return (
    <svg viewBox="0 0 110 140" width={width} height={height} role="img" aria-hidden="true">
      <MascotGraphic pose={pose} />
    </svg>
  )
}
