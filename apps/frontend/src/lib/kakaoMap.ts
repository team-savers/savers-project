// Kakao Maps JS SDK loader.
//
// Loads the SDK script exactly once per page lifetime (module-scope promise
// cache) and resolves once `kakao.maps.load(cb)` reports the namespace ready.
// The script URL is fixed: appkey from Vite env, autoload=false so we control
// initialization timing.
//
// Failure modes (all reject the promise — ShelterMap renders the graceful
// fallback, never a half-loaded map):
//   - VITE_KAKAO_JS_KEY missing     → reject before injecting <script>.
//   - <script> onerror              → reject (network/CSP/blocked domain).
//   - 8s timeout                     → reject (deployed-origin `pending` issue).
//
// The 8s timeout is mandatory: without it, the deployed origin's `pending`
// state would leave the map slot stuck in "loading" forever (silent failure).
// localhost dev loads in well under 8s.
//
// Types: this file declares only the minimum surface used by ShelterMap
// (LatLng, Map, Marker, InfoWindow, load()). No `@types/kakao...` dependency —
// that would violate the wrapper-free rule (minimal type surface only).

// ---- Minimal SDK type surface ----------------------------------------
// Declared as `interface`/`class`-shaped locals; `kakao` global is attached by
// the SDK script. We never reference `any`.

export interface KakaoLatLng {
  getLat(): number
  getLng(): number
}

export interface KakaoMap {
  setCenter(latlng: KakaoLatLng): void
  getCenter(): KakaoLatLng
  // MarkerImage/size args omitted — we use default markers (44px tap target
  // rule: default control UI is disabled at the Map level in ShelterMap).
}

export interface KakaoMarker {
  setMap(map: KakaoMap | null): void
  setPosition(latlng: KakaoLatLng): void
}

export interface KakaoInfoWindow {
  open(map: KakaoMap, marker: KakaoMarker): void
  close(): void
  setContent(content: string): void
}

export interface KakaoMapsNamespace {
  LatLng: new (lat: number, lng: number) => KakaoLatLng
  Map: new (
    container: HTMLElement,
    options: { center: KakaoLatLng; level: number },
  ) => KakaoMap
  Marker: new (options: { map: KakaoMap; position: KakaoLatLng }) => KakaoMarker
  InfoWindow: new (options: { content: string }) => KakaoInfoWindow
  load(cb: () => void): void
}

export interface KakaoGlobal {
  maps: KakaoMapsNamespace
}

// Augment Window so we can read the SDK's injected global without a cast.
declare global {
  interface Window {
    kakao?: KakaoGlobal
  }
}

// ---- Loader ----------------------------------------------------------

const SDK_URL = 'https://dapi.kakao.com/v2/maps/sdk.js'
const LOAD_TIMEOUT_MS = 8000
const SCRIPT_ID = 'savers-kakao-maps-sdk'

// Module-scope promise cache. StrictMode mounts the consumer twice; without
// this, two <script> tags would race and the second `kakao.maps.load` would
// fire against a half-initialized namespace.
let loadPromise: Promise<KakaoMapsNamespace> | null = null

export function loadKakaoMaps(): Promise<KakaoMapsNamespace> {
  if (loadPromise !== null) {
    return loadPromise
  }
  loadPromise = new Promise<KakaoMapsNamespace>((resolve, reject) => {
    const appkey = import.meta.env.VITE_KAKAO_JS_KEY
    if (typeof appkey !== 'string' || appkey.length === 0) {
      // Reset so a later call (e.g. after env fix in dev HMR) can retry.
      loadPromise = null
      reject(
        new Error(
          'VITE_KAKAO_JS_KEY is not set. Add it to apps/frontend/.env.local.',
        ),
      )
      return
    }

    // If the SDK was injected by a previous call/page-lifetime (e.g. Vite HMR
    // preserved window), reuse it without re-injecting.
    if (typeof window !== 'undefined' && window.kakao?.maps !== undefined) {
      const ns = window.kakao.maps
      ns.load(() => resolve(ns))
      return
    }

    // Belt-and-braces dedupe: if a <script> tag with our id already exists
    // (HMR remount racing the cache above), don't append a second one.
    const existing = document.getElementById(SCRIPT_ID) as
      | HTMLScriptElement
      | null
    const script: HTMLScriptElement =
      existing ??
      (() => {
        const el = document.createElement('script')
        el.id = SCRIPT_ID
        return el
      })()

    const url = `${SDK_URL}?appkey=${encodeURIComponent(appkey)}&autoload=false`

    // Reject-without-cleanup contract. Every failure path resets
    // `loadPromise` so a future call can retry. The dangling <script> is
    // harmless — the SDK never fires `kakao.maps.load` on a failed load, so
    // consumers must not be stuck waiting on this promise.
    let settled = false
    const fail = (reason: string): void => {
      if (settled) return
      settled = true
      loadPromise = null
      reject(new Error(reason))
    }
    const succeed = (ns: KakaoMapsNamespace): void => {
      if (settled) return
      settled = true
      resolve(ns)
    }

    const timer = setTimeout(() => {
      fail(
        `Kakao Maps SDK failed to initialize within ${LOAD_TIMEOUT_MS}ms.`,
      )
    }, LOAD_TIMEOUT_MS)

    script.onload = () => {
      // autoload=false → we drive initialization via kakao.maps.load.
      const kakao = window.kakao
      if (kakao?.maps === undefined) {
        clearTimeout(timer)
        fail('Kakao SDK loaded but window.kakao.maps is undefined.')
        return
      }
      const ns = kakao.maps
      ns.load(() => {
        clearTimeout(timer)
        succeed(ns)
      })
    }
    script.onerror = () => {
      clearTimeout(timer)
      fail(
        'Kakao SDK <script> onerror: network/CORS/domain-whitelist failure.',
      )
    }

    script.src = url
    script.async = true
    if (existing === null) {
      document.head.appendChild(script)
    }
  })
  return loadPromise
}
