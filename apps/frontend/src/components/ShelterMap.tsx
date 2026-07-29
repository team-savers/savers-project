// Kakao Maps container for shelter list.
//
// Accessibility contract (core constraints of this component):
//   - The map container is `aria-hidden="true"`. Map DOM is noise to screen
//     readers — the equivalent information (distance + bearing) lives in the
//     ShelterGuide text list, which stays rendered whether the map succeeds
//     or not.
//   - Map controls are disabled (the default zoom/control UI includes
//     sub-44px tap targets). ShelterMap opts into a bare map; map
//     manipulation is not a core function.
//   - When `profile.vision === 'blind'`, ShelterMap is NOT mounted at all
//     (handled in ShelterGuide, not here). This component assumes a
//     non-blind profile.
//
// Three render states (mandatory):
//   loading → role="status" "지도를 불러오는 중…"
//   success → the map DOM (aria-hidden)
//   failure → quiet one-line notice + console.warn with the real cause.
//             The distance/bearing text in ShelterGuide is unaffected.
//
// Map failure is non-fatal by design: the text guidance + action buttons
// must survive any map breakage. The map occupies exactly its slot; it
// cannot break the page.
//
// Error notices are kept intentionally quiet — a red alert card would make a
// map failure read as "evacuation guidance is broken", which overstates the
// situation. The distance/bearing text stays in the list, so the user can
// still reach the shelter. One icon and one line is the ceiling here.

import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type {
  KakaoInfoWindow,
  KakaoLatLng,
  KakaoMap,
  KakaoMapsNamespace,
  KakaoMarker,
} from '../lib/kakaoMap'
import { loadKakaoMaps } from '../lib/kakaoMap'
import type { Language, Shelter } from '../api/types'
import { t } from '../lib/i18n'
import { C, ICON } from '../lib/tokens'

type MapStatus = 'loading' | 'ready' | 'error'

interface Props {
  shelters: Shelter[]
  // User coord from the one-shot geolocation consent. When absent (denied /
  // unsupported / dongCode-only basis), the map centers on the first
  // coord-bearing shelter.
  userCoord?: { lat: number; lng: number } | null
  // UI language for the loading / error notices. Threaded from
  // ShelterGuide, which reads it from the profile.
  lang: Language
}

export function ShelterMap({ shelters, userCoord, lang }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  // Kakao namespace — populated once the SDK finishes loading.
  const mapsApiRef = useRef<KakaoMapsNamespace | null>(null)
  // Base map instance — populated when the Map is constructed, used by the
  // marker effect. Stored on a ref rather than state to avoid an extra
  // render cycle that could race with the marker effect.
  const baseMapRef = useRef<KakaoMap | null>(null)
  // Live markers — cleared + rebuilt whenever `shelters` changes (also
  // covers StrictMode double-fire of the marker effect).
  const markersRef = useRef<KakaoMarker[]>([])
  // Shared InfoWindow; opening it on a new marker moves it (Kakao's API
  // supports one open InfoWindow per call).
  const infoRef = useRef<KakaoInfoWindow | null>(null)

  const [status, setStatus] = useState<MapStatus>('loading')

  // ---- SDK load + base map render ------------------------------------
  useEffect(() => {
    let cancelled = false

    loadKakaoMaps()
      .then((ns: KakaoMapsNamespace) => {
        if (cancelled) return
        const container = containerRef.current
        if (container === null) return

        // Center priority: explicit user coord → first coord-bearing
        // shelter → none. The user coord here is the one already resolved
        // by ShelterGuide's permission branch — ShelterMap never probes
        // GPS itself (hard rule: ShelterMap never probes location).
        const centerInput =
          userCoord !== null && userCoord !== undefined
            ? { lat: userCoord.lat, lng: userCoord.lng }
            : firstShelterLatLng(shelters)
        if (centerInput === null) {
          // Nothing on the map to anchor. Quiet failure — the text list
          // already covers the user.
          if (!cancelled) {
            console.warn(
              'ShelterMap: no coord available (userCoord=null and no shelter carries lat/lng).',
            )
            setStatus('error')
          }
          return
        }

        const center: KakaoLatLng = new ns.LatLng(
          centerInput.lat,
          centerInput.lng,
        )
        const map = new ns.Map(container, { center, level: 4 })
        if (cancelled) return

        mapsApiRef.current = ns
        baseMapRef.current = map
        infoRef.current = new ns.InfoWindow({ content: '' })
        setStatus('ready')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        // Quiet UI, loud console — design rule. kakaoMap.ts already
        // names the cause (missing key / onerror / timeout).
        console.warn(
          'ShelterMap: SDK load failed —',
          err instanceof Error ? err.message : String(err),
        )
        setStatus('error')
      })

    return () => {
      cancelled = true
    }
  }, [shelters, userCoord])

  // ---- Markers --------------------------------------------------------
  // Runs once the base map is ready. Skips shelters without lat/lng (the
  // contract makes these optional; the text list still shows them).
  useEffect(() => {
    if (status !== 'ready') return
    const ns = mapsApiRef.current
    const map = baseMapRef.current
    const info = infoRef.current
    if (ns === null || map === null || info === null) return

    for (const m of markersRef.current) m.setMap(null)
    markersRef.current = []

    for (const s of shelters) {
      if (s.lat === undefined || s.lng === undefined) continue
      const marker = new ns.Marker({
        map,
        position: new ns.LatLng(s.lat, s.lng),
      })
      // Tapping a marker opens a one-line InfoWindow with the shelter
      // name. Kakao's marker event API requires the `kakao.maps.event`
      // surface; we register it via ns (typed minimally inline to avoid
      // expanding the SDK type surface in kakaoMap.ts). The InfoWindow
      // HTML is injected into Kakao's own DOM (NOT React's), so React's
      // conditional-wrap helpers cannot reach it; the lang="ko" attribute
      // is written into the HTML string directly, and only when the
      // screen language is not Korean (matching the rule used in the
      // text list above).
      registerMarkerTap(ns, marker, map, info, s.name, lang)
      markersRef.current.push(marker)
    }
  }, [shelters, status, lang])

  return (
    <div style={wrapperStyle}>
      {status === 'loading' && (
        <p role="status" style={loadingNoticeStyle}>
          {t('shelter.map.loading', lang)}
        </p>
      )}
      {status === 'error' && (
        // 조용한 한 줄. 파일 상단의 ⚠️ 주석 참조 — 지도 실패에 붉은 경보를
        // 띄우면 실제보다 상황을 나쁘게 전달한다.
        <p role="status" style={errorNoticeStyle}>
          <svg
            viewBox="0 0 24 24"
            style={{ ...ICON, width: 17, height: 17, flex: 'none' }}
          >
            <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
            <path d="m2 2 20 20" />
          </svg>
          <span>{t('shelter.map.error', lang)}</span>
        </p>
      )}
      {/* The map container is always in the DOM once mounted so the SDK has
          a target node. aria-hidden keeps screen readers off the noise;
          visually hidden unless ready so loading/error notices own the
          slot instead of a half-painted canvas. */}
      <div
        ref={containerRef}
        aria-hidden="true"
        style={{
          ...mapStyle,
          visibility: status === 'ready' ? 'visible' : 'hidden',
        }}
      />
    </div>
  )
}

// ---- helpers ---------------------------------------------------------

// Returns the {lat,lng} of the first shelter carrying coords, or null when
// none do. Kept tiny so the load effect reads linearly.
function firstShelterLatLng(
  shelters: Shelter[],
): { lat: number; lng: number } | null {
  for (const s of shelters) {
    if (s.lat !== undefined && s.lng !== undefined) {
      return { lat: s.lat, lng: s.lng }
    }
  }
  return null
}

// Kakao's marker click API: `kakao.maps.event.addListener(target, type, cb)`.
// We narrow the event surface as a one-off inline type on `ns` rather than
// adding `KakaoEventNamespace` to kakaoMap.ts (whose type surface is meant
// to stay minimal).
type KakaoMapsNamespaceWithEvents = KakaoMapsNamespace & {
  event: {
    addListener(target: KakaoMarker, type: 'click', cb: () => void): void
  }
}

function registerMarkerTap(
  ns: KakaoMapsNamespace,
  marker: KakaoMarker,
  _map: KakaoMap,
  info: KakaoInfoWindow,
  name: string,
  lang: Language,
): void {
  const withEvents = ns as KakaoMapsNamespaceWithEvents
  if (withEvents.event === undefined) return
  // The InfoWindow shows the shelter name (a Korean proper noun). On a
  // non-Korean screen the name carries lang="ko" so any assistive tech
  // that reaches into the Kakao DOM (and any future a11y pass over the
  // map) announces the place with Korean phonetics. On a Korean screen
  // the wrapper is omitted — the document is already lang="ko".
  //
  // 이 HTML 은 카카오 DOM 에 직접 주입되므로 React 스타일 객체가 닿지 않는다.
  // 그래서 인라인 style 문자열로 팔레트를 맞춘다 — 값이 tokens.ts 와
  // 중복되지만 여기서 import 한 상수를 문자열에 끼워 넣으면 escape 규칙이
  // 복잡해지므로 리터럴로 둔다.
  const escaped = escapeHtml(name)
  const inner = lang !== 'ko' ? `<span lang="ko">${escaped}</span>` : escaped
  info.setContent(
    `<div style="padding:7px 11px;font-family:'Pretendard',system-ui,sans-serif;` +
      `font-size:14.5px;font-weight:700;letter-spacing:-.015em;color:#0D2B45;">` +
      `${inner}</div>`,
  )
  withEvents.event.addListener(marker, 'click', () => {
    // Open on the marker's owning map. Kakao's InfoWindow.open takes a map
    // and a marker; using `_map` directly would be cleaner, but the SDK
    // signature wants the live map the marker is attached to.
    info.open(_map, marker)
  })
}

function escapeHtml(s: string): string {
  // Shelter names come from our own fixture/server response and are
  // already-display strings, but escape defensively before injecting into
  // the InfoWindow's HTML content.
  return s.replace(
    /[&<>"']/g,
    (ch) =>
      (
        {
          '&': '&amp;',
          '<': '&lt;',
          '>': '&gt;',
          '"': '&quot;',
          "'": '&#39;',
        } as Record<string, string>
      )[ch],
  )
}

// ---- styles ----------------------------------------------------------

const wrapperStyle: CSSProperties = {
  width: '100%',
}

const mapStyle: CSSProperties = {
  width: '100%',
  // Fixed height (예: 260px). Below the 44px-target rule's
  // concern (that's about interactive controls, not the map canvas).
  height: '260px',
  borderRadius: '14px',
  background: '#E4EAEF',
  border: `1px solid ${C.border}`,
}

// 공통 한 줄 알림. 크기·행간은 이 화면의 본문 하한(16px)을 따른다.
const noticeBase: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '9px',
  margin: '0 0 10px',
  padding: '13px 15px',
  borderRadius: '12px',
  fontSize: '16px',
  lineHeight: 1.55,
  letterSpacing: '-.012em',
  textWrap: 'pretty',
}

// 오는 중 — 연틸. "진행"은 이 앱에서 틸이다.
const loadingNoticeStyle: CSSProperties = {
  ...noticeBase,
  background: C.tealBg,
  color: C.tealDeep,
  fontWeight: 700,
}

// 실패 — 중성 회색. 붉음이 아닌 이유는 파일 상단 ⚠️ 주석 참조.
const errorNoticeStyle: CSSProperties = {
  ...noticeBase,
  background: C.greyBg,
  border: `1px solid ${C.border}`,
  color: C.body,
}
