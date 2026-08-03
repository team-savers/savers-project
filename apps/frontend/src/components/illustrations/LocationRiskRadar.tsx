// 위치 기반 위험 반경 레이더 (IntroScreenTakeAction 히어로, 2026-08-04).
// 참고 이미지: Apple 날씨 앱의 "당신이 있는 곳" 지구본/지도 화면 —
// "지금 계신 곳이 위험합니다. 어디 계신지 알고, 대피 경로도 안내해
// 드립니다"라는 인상을 직관적으로 준다.
//
// 정직성 제약: 실제 GPS 위성 지도가 아니다(Kakao 지도 SDK는 대피소
// 화면(ShelterMap)에서만 실좌표로 쓰인다). 여기서는 "등록하신 동" 하나만
// 알고 있으므로, 그 사실 그대로 "등록하신 동" 라벨과 동 이름만 보여주고
// 실제 좌표·정밀 반경을 지어내지 않는다. 중심점은 지도 앱의 "내 위치"
// 점 관례(흰 테두리 + 채워진 점)로 표시하고, 퍼지는 원은 "위험이
// 번지고 있다"는 은유일 뿐 실측 반경이 아니라는 걸 라벨로 밝힌다.
// 빨강은 반경 링 스트로크(가는 선)로만 쓴다 — 채워진 면적이 아니라서
// 기존 "레드는 작은 신호만" 원칙 안에 있다.
import { C } from '../../lib/tokens'

export function LocationRiskRadar({ dongName }: { dongName: string }) {
  return (
    <svg viewBox="0 0 240 240" width="100%" height="auto" role="img" aria-label={`${dongName} 위치와 위험 반경을 나타낸 레이더`}>
      <style>{`
        @keyframes savers-radar-pulse {
          0% { r: 22px; opacity: .6; }
          100% { r: 112px; opacity: 0; }
        }
        .savers-radar-ring { animation: savers-radar-pulse 2.6s ease-out infinite; }
        .savers-radar-ring:nth-of-type(2) { animation-delay: .85s; }
        .savers-radar-ring:nth-of-type(3) { animation-delay: 1.7s; }
        @media (prefers-reduced-motion: reduce) {
          .savers-radar-ring { animation: none; opacity: .22; r: 74px; }
        }
      `}</style>

      <defs>
        <radialGradient id="savers-radar-bg" cx="50%" cy="42%" r="68%">
          <stop offset="0%" stopColor="#28405c" />
          <stop offset="55%" stopColor="#13233a" />
          <stop offset="100%" stopColor="#081422" />
        </radialGradient>
      </defs>

      <circle cx="120" cy="120" r="120" fill="url(#savers-radar-bg)" />

      {/* 위험이 번지는 신호 — 실측 반경이 아니라 은유. 링만 그려서(채우지
          않아서) 화면이 빨갛게 물들지 않게 한다. */}
      <circle className="savers-radar-ring" cx="120" cy="120" r="22" fill="none" stroke={C.alert} strokeWidth="2" />
      <circle className="savers-radar-ring" cx="120" cy="120" r="22" fill="none" stroke={C.alert} strokeWidth="2" />
      <circle className="savers-radar-ring" cx="120" cy="120" r="22" fill="none" stroke={C.alert} strokeWidth="2" />

      {/* 현재 위치 — 지도 앱의 "내 위치" 점과 같은 관례(흰 테두리 + 채워진
          점, 은은한 글로우). 마스코트를 여기 넣었더니 이 화면 톤(어두운
          레이더)과 안 어울려서 뺐다 — 마스코트는 인트로 아래 문구·다른
          화면에서 계속 쓴다. */}
      <circle cx="120" cy="120" r="16" fill={C.alert} opacity="0.25" />
      <circle cx="120" cy="120" r="7" fill={C.alert} stroke={C.white} strokeWidth="3" />

      <text x="120" y="188" textAnchor="middle" fontSize="12" fill="rgba(255,255,255,.55)">
        등록하신 동
      </text>
      <text x="120" y="212" textAnchor="middle" fontSize="21" fontWeight="800" fill={C.white}>
        {dongName}
      </text>
    </svg>
  )
}
