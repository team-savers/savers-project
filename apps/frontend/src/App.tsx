// Minimal app shell. Routing is by window.location.pathname — no router
// library is used.
//
// Routes:
//   /                       → home
//   /register               → guardian mobile surrogate-registration (pages/Register.tsx)
//   /demo                   → push demo + persona picker for the mock profiles
//   /a?t=                   → alert landing (pages/Landing.tsx)
//   /ops                    → operator surrogate-registration (pages/Ops.tsx)
//   /join?u=<userId>        → ward phone onboarding (pages/Join.tsx) — the
//                             QR on /ops opens this URL on the ward's phone
//   /preview?t=<token>      → EXPERIMENTAL staged flow (pages/Preview.tsx),
//                             not adopted into /a — see that file's header
//   /mockup                 → PRESENTATION-ONLY static mockups
//                             (pages/Mockup.tsx). Not wired to ../api/* at
//                             all — hardcoded example data only.
//
// The guardian route (/g/{token}), its page, and the ?s= stage parameter are
// intentionally not part of the route set. Landing takes only the session
// token.

import { useEffect, useRef, useState } from 'react'
import {
  onForegroundMessage,
  requestPushPermission,
  type TokenAttempt,
} from './lib/push'
import type { MessagePayload } from 'firebase/messaging'
import { Landing } from './pages/Landing'
import { Ops } from './pages/Ops'
import { Join } from './pages/Join'
import { Home } from './pages/Home'
import { Register } from './pages/Register'
import { Preview } from './pages/Preview'
import { Mockup } from './pages/Mockup'
import { initSwUpdates } from './lib/swUpdate'
import { PROFILES } from './mocks/profiles'
import type { Profile } from './api/types'
import './App.css'

// Module-scope guard that the update reload fires AT MOST ONCE per page
// session. A reload loop during a disaster alert is the worst possible
// outcome of the SW-update feature (a stale page is safer than one that
// keeps refreshing itself), so this guard is intentionally NOT component
// state (which a remount / StrictMode double-invoke could reset). It must
// survive for the entire lifetime of this document.
let didReloadForUpdate = false

function usePathname(): string {
  const [pathname, setPathname] = useState<string>(
    typeof window !== 'undefined' ? window.location.pathname : '/',
  )
  useEffect(() => {
    const onPop = () => setPathname(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  return pathname
}

// Foreground push banner. The app subscribes to FCM foreground messages at
// the TOP level so a push that arrives while ANY route is open (/, /demo,
// /a, /join, /ops) surfaces as an on-screen banner instead of being silently
// dropped. Web push delivers foreground messages via onMessage (not via the
// service worker), so without a top-level subscription these pushes vanish
// whenever the user is looking at the app.
//
// Rules:
//   - Tap → navigate to data.url (same destination as the service worker's
//     notificationclick). If data.url is absent the banner has no link and
//     only the close button is actionable.
//   - Does NOT auto-dismiss. The user must close it — a safety alert must
//     not disappear while unread.
//   - role="alert" so assistive tech announces it immediately.
//   - The on-screen banner is the only foreground surface; no system
//     notification API is invoked from here.
interface ForegroundBanner {
  // Monotonic per-arrival id. Dismiss is keyed on this, NOT on payload
  // content, so a repeat of the same disaster alert (which is the normal
  // case during an unfolding event) always re-shows the banner after the
  // user closes it. Keying on content would silently swallow repeats.
  arrivalId: number
  payload: MessagePayload
}

// Monotonic counter shared across the app's lifetime so each foreground
// message gets a distinct arrival id even if its payload is byte-identical
// to the previous one. A module-level counter is sufficient — banner
// visibility is not a security primitive.
let arrivalCounter = 0

function useForegroundPush(): ForegroundBanner | null {
  const [banner, setBanner] = useState<ForegroundBanner | null>(null)
  useEffect(() => {
    // FCM foreground messages depend on the messaging SDK, which in turn
    // needs service worker support. On a browser without service workers
    // (e.g. some in-app webviews, old browsers) subscribing would throw
    // before the fallback notice can render. Skip the subscription entirely
    // in that case — the app stays usable, just without foreground push.
    if (!('serviceWorker' in navigator)) return
    const unsub = onForegroundMessage((payload: MessagePayload) => {
      arrivalCounter += 1
      setBanner({ arrivalId: arrivalCounter, payload })
    })
    return () => {
      unsub()
    }
  }, [])
  return banner
}

function ForegroundBannerView({
  banner,
  onClose,
}: {
  banner: ForegroundBanner
  onClose: () => void
}): React.ReactElement {
  const payload = banner.payload
  // Our push contract is data-only: the title/body/url live on
  // payload.data, and a `notification` block is usually absent. We read
  // data first so the actual disaster message renders; `notification` is
  // consulted only as a fallback (e.g. a legacy notification-only push).
  const data = payload.data as
    | { title?: unknown; body?: unknown; url?: unknown }
    | undefined
  const notif = payload.notification as
    | { title?: unknown; body?: unknown }
    | undefined
  // data.url mirrors the destination the service worker's
  // notificationclick opens; tapping the banner follows the same intent.
  const url = typeof data?.url === 'string' ? data.url : undefined
  const dataTitle = typeof data?.title === 'string' ? data.title : null
  const dataBody = typeof data?.body === 'string' ? data.body : null
  const notifTitle =
    typeof notif?.title === 'string' ? notif.title : null
  const notifBody = typeof notif?.body === 'string' ? notif.body : null
  const title = dataTitle ?? notifTitle ?? '알림이 도착했습니다'
  const body = dataBody ?? notifBody ?? ''
  return (
    <div
      role="alert"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 1000,
        background: '#1565c0',
        color: '#fff',
        padding: '0.75rem 1rem',
        display: 'flex',
        alignItems: 'flex-start',
        gap: '0.75rem',
        boxShadow: '0 2px 8px rgba(0,0,0,0.25)',
        minHeight: '44px',
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: '1rem' }}>{title}</div>
        {body !== '' && (
          <div style={{ fontSize: '0.95rem', marginTop: '0.2rem' }}>
            {body}
          </div>
        )}
      </div>
      {url !== undefined && (
        <a
          href={url}
          style={{
            background: '#fff',
            color: '#1565c0',
            textDecoration: 'none',
            padding: '0.5rem 0.9rem',
            borderRadius: '6px',
            fontWeight: 700,
            minHeight: '44px',
            minWidth: '44px',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          열기
        </a>
      )}
      <button
        type="button"
        onClick={onClose}
        aria-label="알림 닫기"
        style={{
          background: 'transparent',
          color: '#fff',
          border: '2px solid rgba(255,255,255,0.7)',
          borderRadius: '6px',
          minHeight: '44px',
          minWidth: '44px',
          cursor: 'pointer',
          fontSize: '1rem',
          padding: '0 0.6rem',
          flexShrink: 0,
        }}
      >
        ✕
      </button>
    </div>
  )
}

function DemoView() {
  // The token and the failure reason are kept as separate states but are
  // mutually exclusive in practice: a successful attempt sets token and
  // clears the failure; any non-ok attempt clears the token and sets the
  // reason. The render below only shows ONE of the two blocks, so the user
  // never sees a token alongside an error.
  const [token, setToken] = useState<string | null>(null)
  const [attempt, setAttempt] = useState<TokenAttempt | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleClick(): Promise<void> {
    setError(null)
    try {
      // tokenOnly: the demo screen has no real ward identity and therefore
      // no registration document to attach to. We must NOT touch the
      // cross-device store here — the placeholder userId has nothing to
      // attach to, and creating a fake document is explicitly forbidden
      // (it would undo the no-resurrect guard). Foreground messaging still
      // works with the minted token.
      const result = await requestPushPermission('demo', { tokenOnly: true })
      if (result.status === 'ok') {
        setToken(result.token)
        setAttempt(null)
      } else {
        setToken(null)
        setAttempt(result)
      }
    } catch (err) {
      // Unexpected thrown error (not a discriminated failure). Surface it
      // rather than swallow — the screen must never silently do nothing.
      setToken(null)
      setAttempt(null)
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  // Map the discriminated failure to plain-Korean guidance. Each case matches
  // a distinct cause so the user gets actionable instructions instead of a
  // generic failure line.
  function guidanceFor(a: TokenAttempt): string {
    switch (a.status) {
      case 'unsupported':
        return '이 브라우저에서는 알림을 받을 수 없습니다. 다른 브라우저로 열어 주세요.'
      case 'denied':
        return '알림이 꺼져 있습니다. 브라우저 설정에서 이 사이트의 알림을 켜 주세요.'
      case 'misconfigured':
        return '알림 설정에 문제가 있습니다. 담당자에게 알려 주세요.'
      case 'token_unavailable':
      case 'timeout':
        return '알림을 준비하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
      default:
        return '알림을 준비하지 못했습니다. 잠시 뒤 다시 시도해 주세요.'
    }
  }

  return (
    <main style={{ padding: '1rem', maxWidth: '640px', margin: '0 auto' }}>
      <h1>SAVERS — Push Demo</h1>
      <button type="button" onClick={() => void handleClick()}>
        알림 받기
      </button>

      {token !== null && attempt === null && (
        <p>
          <strong>FCM token:</strong> <code>{token}</code>
        </p>
      )}
      {attempt !== null && token === null && (
        <p role="alert" style={{ color: '#c62828' }}>
          {guidanceFor(attempt)}
        </p>
      )}
      {error !== null && token === null && attempt === null && (
        <p role="alert" style={{ color: '#c62828' }}>
          <strong>오류:</strong> {error}
        </p>
      )}

      <hr style={{ margin: '1.5rem 0' }} />

      <h2>페르소나 선택</h2>
      <p>각 인물은 가상의 데모용 데이터입니다.</p>
      <ul style={{ listStyle: 'none', padding: 0 }}>
        {Object.values(PROFILES).map((p) => (
          <li key={p.userId} style={{ marginBottom: '0.5rem' }}>
            <a
              href={`/a?t=${encodeURIComponent(p.userId)}`}
              style={{
                display: 'block',
                padding: '0.75rem',
                background: '#e3f2fd',
                textDecoration: 'none',
                color: '#0d47a1',
                borderRadius: '8px',
              }}
            >
              <strong>{p.name}</strong> — {personaSummary(p)}
            </a>
          </li>
        ))}
      </ul>

      <hr style={{ margin: '1.5rem 0' }} />

      <h2>실험적 화면</h2>
      <p>
        단계별 대피 흐름(경고 → 갈림길 → 행동권고 → 경로 확인) 미리보기입니다.{' '}
        <code>/a</code>에 아직 반영되지 않았습니다 — 검토용입니다.
      </p>
      <a
        href="/preview?t=p001"
        style={{
          display: 'block',
          padding: '0.75rem',
          background: '#fde3e3',
          textDecoration: 'none',
          color: '#b3182b',
          borderRadius: '8px',
          fontWeight: 700,
        }}
      >
        /preview 열기 (김순자)
      </a>

      <h2>발표용 목업</h2>
      <p>
        코드/기능 연동 없는 정적 화면 모음입니다(보호자 현황 개념안 · AI 챗봇 · 관리자 요약).
        발표 자료용이며 실제 동작하지 않습니다.
      </p>
      <a
        href="/mockup"
        style={{
          display: 'block',
          padding: '0.75rem',
          background: '#e6f4f1',
          textDecoration: 'none',
          color: '#0b6e69',
          borderRadius: '8px',
          fontWeight: 700,
        }}
      >
        /mockup 열기
      </a>

      {/* Non-secret build stamp so an operator can verify at a glance which
          build is currently live on a device. Rendered only on the internal
          /demo route (never on the vulnerable-user landing). */}
      <p
        style={{
          marginTop: '2rem',
          fontSize: '0.7rem',
          color: '#888',
          fontFamily: 'monospace',
        }}
      >
        build: {__BUILD_STAMP__}
      </p>
    </main>
  )
}

function personaSummary(p: Profile): string {
  const bits: string[] = []
  bits.push(`주거 ${p.housing}`)
  bits.push(`이동 ${p.mobility}`)
  if (p.vision !== 'ok') bits.push(`시력 ${p.vision}`)
  if (p.hearing !== 'ok') bits.push(`청력 ${p.hearing}`)
  if (p.language !== 'ko') bits.push(`언어 ${p.language}`)
  if (p.care !== null) bits.push(`돌봄 ${p.care}`)
  bits.push(p.guardian === null ? '보호자 없음' : '보호자 있음')
  return bits.join(' · ')
}

function LandingView() {
  const params = new URLSearchParams(window.location.search)
  const t = params.get('t') ?? ''
  return <Landing token={t} />
}

// Experimental staged flow — not part of the role-defined route set. See
// pages/Preview.tsx header for what this is and is not.
function PreviewView() {
  const params = new URLSearchParams(window.location.search)
  const t = params.get('t') ?? 'p001'
  return <Preview token={t} />
}

function JoinView() {
  const params = new URLSearchParams(window.location.search)
  const u = params.get('u') ?? ''
  return <Join userId={u} />
}

function HomeView() {
  return <Home />
}

// Reload the page to apply a waiting service worker, guarded to fire AT MOST
// ONCE per page session via the module-scope `didReloadForUpdate` flag. This
// is the explicit anti-loop guarantee: even if `controllerchange` fires
// several times (e.g. the new SW activates, then a second update is
// detected), only the first call actually reloads. Subsequent calls are
// no-ops, so a disaster-alert tab can never be trapped in a refresh loop.
function applyUpdateOnce(): void {
  if (didReloadForUpdate) return
  didReloadForUpdate = true
  window.location.reload()
}

// Hook that wires SW-update detection to the page. A waiting update is
// reported through `initSwUpdates`; the hook decides whether it is SAFE to
// reload right now and, if not, exposes a non-dismissable banner the user
// can act on. Returns a `prompt` object (with a reload handler) when a banner
// must be shown, or null otherwise.
interface UpdatePrompt {
  // Called when the user taps the "새로 불러오기" button. Applies the update
  // through the same once-only guard as a safe-time auto reload.
  onApply: () => void
}

function useSwUpdate(promptNeeded: boolean): {
  prompt: UpdatePrompt | null
} {
  // `waitingForApply` flips true once `initSwUpdates` reports a waiting worker.
  // It drives both the safe-time auto-reload and the banner state.
  const [waitingForApply, setWaitingForApply] = useState(false)
  // Keep the latest "is it safe to reload now?" value in a ref so the
  // `controllerchange` listener (registered once) always reads the current
  // safety state without being re-registered on every render.
  const promptNeededRef = useRef(promptNeeded)
  useEffect(() => {
    promptNeededRef.current = promptNeeded
  }, [promptNeeded])

  useEffect(() => {
    // Service worker support guard. Without this, `navigator.serviceWorker`
    // is undefined on unsupported browsers and the addEventListener call
    // below throws — crashing the app before the "이 브라우저에서는 알림을
    // 받을 수 없습니다" notice can render. We skip silently: the app stays
    // usable, just without SW-update detection.
    if (!('serviceWorker' in navigator)) return
    // Capture whether a controller ALREADY existed when this effect runs. The
    // first time a service worker activates on this page it fires
    // `controllerchange` as it claims the page — but that is NOT an update,
    // it is the initial claim. If we treated it as an update we would either
    // reload once on every fresh page load (when safe) or show the update
    // banner once on every fresh page load (when on an alert route). Both are
    // false alarms. By checking that a controller already existed BEFORE the
    // change event, we distinguish "a NEW worker replaced an existing one"
    // (real update → act) from "a worker is claiming the page for the first
    // time" (initial activation → ignore).
    const hadControllerAtStart = navigator.serviceWorker.controller !== null
    // Listen for the new worker taking over. skipWaiting() in the SW means a
    // waiting worker activates on its own; when that happens we either reload
    // immediately (safe) or surface the banner (unsafe — user is reading an
    // alert). Either path is gated by `applyUpdateOnce` so it happens once.
    const onControllerChange = (): void => {
      // Initial SW activation — not an update. Ignore so we do not false-
      // alarm on every fresh page load.
      if (!hadControllerAtStart) return
      if (promptNeededRef.current) {
        // User is reading an alert — do NOT reload automatically. Show the
        // banner instead; the user will reload via the button.
        setWaitingForApply(true)
      } else {
        // Safe: reload now (once-only guard inside applyUpdateOnce).
        applyUpdateOnce()
      }
    }
    const teardown = initSwUpdates({
      // `onUpdateWaiting` is the earliest signal. We don't reload here — we
      // wait for `controllerchange`, which fires when the new worker has
      // actually activated (skipWaiting makes this near-instant). Reloading
      // before activation would reload into the OLD worker's shell.
      onUpdateWaiting: () => {
        /* handled via controllerchange listener below */
      },
    })
    navigator.serviceWorker.addEventListener(
      'controllerchange',
      onControllerChange,
    )
    return () => {
      navigator.serviceWorker.removeEventListener(
        'controllerchange',
        onControllerChange,
      )
      teardown()
    }
  }, [])

  const prompt: UpdatePrompt | null =
    waitingForApply && promptNeeded
      ? { onApply: applyUpdateOnce }
      : null
  return { prompt }
}

// Non-dismissable banner shown when a new SW version is ready but it is NOT
// safe to reload right now (the user is reading a disaster alert). The user
// taps the button to apply the update when they are ready. It does not cover
// the alert body — it is pinned to the bottom and is large/clear per the
// accessibility bar.
function UpdateReadyBanner({
  onApply,
}: {
  onApply: () => void
}): React.ReactElement {
  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        left: 0,
        right: 0,
        bottom: 0,
        zIndex: 1000,
        background: '#2e7d32',
        color: '#fff',
        padding: '0.75rem 1rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '0.75rem',
        boxShadow: '0 -2px 8px rgba(0,0,0,0.25)',
      }}
    >
      <span style={{ fontSize: '1rem', fontWeight: 600 }}>
        새 안내가 준비됐습니다
      </span>
      <button
        type="button"
        onClick={onApply}
        style={{
          background: '#fff',
          color: '#2e7d32',
          border: 'none',
          borderRadius: '6px',
          fontWeight: 700,
          fontSize: '1rem',
          minHeight: '44px',
          minWidth: '44px',
          padding: '0.5rem 1rem',
          cursor: 'pointer',
        }}
      >
        새로 불러오기
      </button>
    </div>
  )
}

function App() {
  const pathname = usePathname()
  const banner = useForegroundPush()
  // Dismiss is keyed by per-arrival id, not by payload content. A disaster
  // alert repeats as the situation develops; keying dismiss on content
  // would silently suppress the second identical alert. Each arrival gets
  // a fresh banner until the user dismisses THAT arrival.
  const [dismissedArrival, setDismissedArrival] = useState<number | null>(
    null,
  )
  const showBanner =
    banner !== null && dismissedArrival !== banner.arrivalId

  // It is UNSAFE to auto-reload for an SW update while the user is reading a
  // disaster alert on /a (or /a/...). On those routes we show the
  // "새로 불러오기" banner instead of reloading; everywhere else we apply the
  // update quietly (once). The rule is: apply at a safe time, never mid-alert.
  const onAlertRoute = pathname === '/a' || pathname.startsWith('/a/')
  const { prompt: updatePrompt } = useSwUpdate(onAlertRoute)

  return (
    <>
      {showBanner && banner !== null && (
        <ForegroundBannerView
          banner={banner}
          onClose={() => setDismissedArrival(banner.arrivalId)}
        />
      )}
      <AppRoutes pathname={pathname} />
      {updatePrompt !== null && (
        <UpdateReadyBanner onApply={updatePrompt.onApply} />
      )}
    </>
  )
}

function AppRoutes({ pathname }: { pathname: string }): React.ReactElement {
  if (pathname === '/ops') {
    return <Ops />
  }
  if (pathname === '/demo') {
    return <DemoView />
  }
  if (pathname === '/join') {
    return <JoinView />
  }
  if (pathname === '/register') {
    return <Register />
  }
  if (pathname === '/a' || pathname.startsWith('/a/')) {
    return <LandingView />
  }
  if (pathname === '/preview') {
    return <PreviewView />
  }
  if (pathname === '/mockup') {
    return <Mockup />
  }
  return <HomeView />
}

export default App
