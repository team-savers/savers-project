// Minimal app shell. Routing is by window.location.pathname — no router
// library (out of scope for this scaffold ticket). The /a view reads the
// ?t= and ?s= query params that the FCM notification URL carries and just
// displays them; full content rendering is the next ticket.

import { useEffect, useState } from 'react'
import { onForegroundMessage, requestPushPermission } from './lib/push'
import type { MessagePayload } from 'firebase/messaging'
import './App.css'

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

function DemoView() {
  const [token, setToken] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [foreground, setForeground] = useState<MessagePayload | null>(null)

  useEffect(() => {
    const unsub = onForegroundMessage((payload: MessagePayload) => {
      setForeground(payload)
    })
    return () => {
      unsub()
    }
  }, [])

  async function handleClick() {
    setError(null)
    try {
      const t = await requestPushPermission()
      setToken(t)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <main>
      <h1>SAVERS — Push Demo</h1>
      <button type="button" onClick={handleClick}>
        알림 받기
      </button>

      {token !== null && (
        <p>
          <strong>FCM token:</strong> <code>{token || '(permission denied or no token)'}</code>
        </p>
      )}
      {error !== null && (
        <p>
          <strong>Error:</strong> {error}
        </p>
      )}

      {foreground !== null && (
        <div role="status">
          <strong>Foreground message:</strong>
          <pre>{JSON.stringify(foreground, null, 2)}</pre>
        </div>
      )}
    </main>
  )
}

function LandingView() {
  // ?t= (alert title) and ?s= (status / source) are read-only display here.
  // The next ticket renders actual content from these.
  const params = new URLSearchParams(window.location.search)
  const t = params.get('t') ?? ''
  const s = params.get('s') ?? ''

  return (
    <main>
      <h1>SAVERS — 알림 랜딩</h1>
      <dl>
        <dt>t</dt>
        <dd>{t || '(없음)'}</dd>
        <dt>s</dt>
        <dd>{s || '(없음)'}</dd>
      </dl>
    </main>
  )
}

function HomeView() {
  return (
    <main>
      <h1>SAVERS</h1>
      <p>데모는 /demo 로 이동하세요.</p>
    </main>
  )
}

function App() {
  const pathname = usePathname()

  if (pathname === '/demo') {
    return <DemoView />
  }
  if (pathname === '/a' || pathname.startsWith('/a/')) {
    return <LandingView />
  }
  return <HomeView />
}

export default App
