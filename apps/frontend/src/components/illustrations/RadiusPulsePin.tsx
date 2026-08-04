// 위험 반경 펄스 핀 — 실제 지도(AlertAreaMap) 위에 얹는 오버레이.
// 사용자가 "반경링(펄스 애니메이션)은 마음에 든다"고 확인했다(2026-08-04)
// — 이전 버전(LocationRiskRadar, 어두운 원판 배경 안에 넣었던 것)의 배경은
// 실제 지도로 대체하고, 펄스 링과 중심 핀만 그대로 가져와 지도 위에
// 얹는다.
//
// 지도 앱의 "내 위치" 점 관례(흰 테두리 + 채워진 점)로 중심을 표시하고,
// 퍼지는 원은 "위험이 번지고 있다"는 은유일 뿐 실측 반경이 아니다 — 실제
// 정밀 좌표가 없다는 사실은 이 컴포넌트가 아니라 호출부(IntroScreenTakeAction)
// 의 "대략적 위치" 배지로 밝힌다. 빨강은 링 스트로크(가는 선)로만 쓴다 —
// 채워진 면적이 아니라서 기존 "레드는 작은 신호만" 원칙 안에 있다.
import { C } from '../../lib/tokens'

export function RadiusPulsePin() {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        top: '38%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        width: '170px',
        height: '170px',
        pointerEvents: 'none',
      }}
    >
      <svg viewBox="0 0 170 170" width="100%" height="100%">
        <style>{`
          @keyframes savers-radar-pulse {
            0% { r: 14px; opacity: .65; }
            100% { r: 78px; opacity: 0; }
          }
          .savers-radar-ring { animation: savers-radar-pulse 2.6s ease-out infinite; }
          .savers-radar-ring:nth-of-type(2) { animation-delay: .85s; }
          .savers-radar-ring:nth-of-type(3) { animation-delay: 1.7s; }
          @media (prefers-reduced-motion: reduce) {
            .savers-radar-ring { animation: none; opacity: .22; r: 52px; }
          }
        `}</style>
        <circle className="savers-radar-ring" cx="85" cy="85" r="14" fill="none" stroke={C.alert} strokeWidth="2.5" />
        <circle className="savers-radar-ring" cx="85" cy="85" r="14" fill="none" stroke={C.alert} strokeWidth="2.5" />
        <circle className="savers-radar-ring" cx="85" cy="85" r="14" fill="none" stroke={C.alert} strokeWidth="2.5" />
        <circle cx="85" cy="85" r="11" fill={C.alert} opacity="0.25" />
        <circle cx="85" cy="85" r="6" fill={C.alert} stroke={C.white} strokeWidth="3" />
      </svg>
    </div>
  )
}
