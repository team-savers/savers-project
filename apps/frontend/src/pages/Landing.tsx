import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import type { SessionResponse } from '../api/types'
import { ProductionEvacuationFlow } from './EvacuationFlow'
import './EvacuationFlow.css'

interface Props { token: string }

export function Landing({ token }: Props) {
  const [session, setSession] = useState<SessionResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    api.getSession(token)
      .then((value) => { if (!cancelled) setSession(value) })
      .catch((cause) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [retryCount, token])

  const suppressBody = useMemo(() => (
    session?.message.messageMode === 'grounded' && session.message.sources.length === 0
  ), [session])

  if (session !== null) {
    return <ProductionEvacuationFlow token={token} session={session} suppressBody={suppressBody} />
  }

  return <main className="evac-flow">
    <header className="evac-header">
      <span aria-hidden="true" />
      <strong className="evac-brand"><img src="/logo.png" alt="" />SAVERS</strong>
      <span aria-hidden="true" />
    </header>
    <div className="evac-content">
      <section className="evac-step evac-step-centered evac-alert-step">
        <div className="evac-content-group">
          <div className="evac-alert-main">
            <div className="evac-alert-icon-wrap" aria-hidden="true"><div className="evac-alert-icon">!</div></div>
            <p className="evac-kicker">긴급 재난 정보</p>
            <h1>{loading ? '맞춤 안내를 불러오고 있습니다.' : '맞춤 안내를 불러오지 못했습니다.'}</h1>
          </div>
          {error !== null && <div className="evac-card evac-notice" role="alert"><span aria-hidden="true">!</span><div>
            <strong>네트워크 또는 서버 오류</strong><small>{error}</small>
          </div></div>}
          {!loading && <footer className="evac-footer">
            <button className="evac-primary" type="button" onClick={() => setRetryCount((value) => value + 1)}>다시 시도</button>
            <p className="evac-footnote">세션을 확인하지 못한 상태에서는 임의의 대피 지침을 표시하지 않습니다.</p>
          </footer>}
        </div>
      </section>
    </div>
  </main>
}
