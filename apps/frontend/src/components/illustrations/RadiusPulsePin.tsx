// 위험 반경 펄스 링 — 실제 지도(AlertAreaMap) 위에 얹는 오버레이.
// 사용자가 "반경링(펄스 애니메이션)은 마음에 든다"고 확인했다(2026-08-04)
// — 이전 버전(LocationRiskRadar, 어두운 원판 배경 안에 넣었던 것)의 배경은
// 실제 지도로 대체하고, 펄스 링만 가져와 지도 위에 얹는다.
//
// ⚠️ 중심에 "내 위치" 점을 찍지 않는다(2026-08-06 제거). 지도 앱 관례(흰
// 테두리 + 채워진 점)를 쓰고 있었는데, 이 지도의 중심은 사용자 위치가 아니라
// **가장 가까운 대피소 좌표**다(AlertAreaMap 헤더 주석 참조 — 그 파일도 같은
// 이유로 정밀 사용자 핀을 찍지 않는다). 결과적으로 "위험 반경이 대피
// 목적지에서 퍼진다"는 의미가 뒤집힌 그림이 되고, 정밀 좌표를 모른다는 사실과
// 반대되는 인상을 준다(PR #54 리뷰, 머지 전 필수 3).
//
// 그래서 남는 것은 링뿐이고, 링은 "이 근처에 위험이 번지고 있다"는 은유일 뿐
// 실측 반경이 아니다 — 그 사실은 호출부(IntroScreenTakeAction)의 "대략적
// 위치" 배지가 계속 밝힌다. 빨강은 링 스트로크(가는 선)로만 쓴다 — 채워진
// 면적이 아니라서 기존 "레드는 작은 신호만" 원칙 안에 있다.
import { C } from '../../lib/tokens'

export function RadiusPulsePin() {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        // 지도 중심과 정확히 겹친다. 이전 값(38%)은 지도 중심(50%)도 아닌
        // 임의 지점이라, 링이 감싸는 지역과 지도가 보여주는 지역이 어긋났다
        // (PR #54 리뷰).
        top: '50%',
        left: '50%',
        transform: 'translate(-50%, -50%)',
        zIndex: 1,
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
        {/* 옅은 중심 헤이즈. 링이 어디에서 퍼져 나오는지 시각적 기점만
            주고, 특정 지점을 "여기"라고 지목하지 않는다 — 테두리 있는
            점(내 위치 관례)으로 다시 만들지 말 것(헤더 주석 참조). */}
        <circle cx="85" cy="85" r="11" fill={C.alert} opacity="0.25" />
      </svg>
    </div>
  )
}
