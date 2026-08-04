// 인트로 화면(IntroScreenTakeAction) 배경용 대략적인 지역 지도.
// ShelterMap과 같은 카카오맵 SDK 로더(lib/kakaoMap.ts)를 재사용하되,
// 마커 없이 배경 지도만 그린다 — 이 화면의 역할은 "당신이 있는 동네가
// 위험하다"는 인상을 실제 지도로 전달하는 것뿐, 대피소 안내는 여전히
// RouteScreen의 ShelterMap이 맡는다.
//
// "대략적"인 이유: 여기서 실제로 아는 좌표는 가장 가까운 대피소(nearest
// shelter) 좌표뿐이다 — 사용자의 정밀 GPS는 이 화면 다음 단계에서만
// (위치 공유를 직접 누르거나, 실제 서비스라면 별도 동의 절차를 거쳐)
// 얻는다. 그래서 확대 레벨을 낮게(level 6, 더 넓게) 잡아 "이 동네 근처"
// 라는 느낌만 주고, 정밀한 사용자 핀을 찍지 않는다.
//
// 카카오 SDK 키(VITE_KAKAO_JS_KEY)가 없거나 로드에 실패하면 조용히
// 실패한다(ShelterMap과 같은 원칙 — 지도 실패가 "안내가 고장났다"로
// 읽히면 안 된다). 이 화면은 하단 시트에 이미 모든 행동 지침이 있으므로
// 지도 없이(하자드 옐로 대체 배경으로) 화면은 정상 작동한다.
import { useEffect, useRef, useState } from 'react'
import { loadKakaoMaps } from '../lib/kakaoMap'
import { C } from '../lib/tokens'

type MapStatus = 'loading' | 'ready' | 'error'

export function AlertAreaMap({ center }: { center: { lat: number; lng: number } }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [status, setStatus] = useState<MapStatus>('loading')

  useEffect(() => {
    let cancelled = false
    loadKakaoMaps()
      .then((ns) => {
        if (cancelled) return
        const container = containerRef.current
        if (container === null) return
        const latlng = new ns.LatLng(center.lat, center.lng)
        // eslint-disable-next-line no-new -- 배경 지도일 뿐, 인스턴스를 따로 참조할 일이 없다.
        new ns.Map(container, { center: latlng, level: 6 })
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.warn('AlertAreaMap: Kakao Maps 로드 실패 —', err instanceof Error ? err.message : String(err))
        setStatus('error')
      })
    return () => {
      cancelled = true
    }
  }, [center.lat, center.lng])

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        background:
          status === 'error' ? `linear-gradient(180deg, ${C.hazard} 0%, ${C.hazard} 55%, #E6A800 100%)` : '#E4EAEF',
      }}
    >
      <div
        ref={containerRef}
        aria-hidden="true"
        style={{ width: '100%', height: '100%', visibility: status === 'ready' ? 'visible' : 'hidden' }}
      />
    </div>
  )
}
