// Keeps the screen from auto-locking while `active` is true (Screen Wake
// Lock API). This is the one thing in the "화면 밝기/절전" request that a PWA
// can actually do — forcing max hardware brightness has no web API and needs
// a native shell, so it is not attempted here (see Preview.tsx comment).
import { useEffect, useRef } from 'react'

export function useWakeLock(active: boolean): void {
  const sentinelRef = useRef<WakeLockSentinel | null>(null)

  useEffect(() => {
    if (!active || !('wakeLock' in navigator)) return

    let cancelled = false

    async function acquire() {
      try {
        const sentinel = await navigator.wakeLock.request('screen')
        if (cancelled) {
          void sentinel.release()
          return
        }
        sentinelRef.current = sentinel
      } catch {
        // 배터리 절약 모드, 권한 거부 등으로 실패할 수 있음 — 화면 꺼짐 방지는
        // 보조 기능이라 조용히 무시하고 나머지 화면은 그대로 동작한다.
      }
    }

    void acquire()

    // 탭이 백그라운드로 갔다 돌아오면 sentinel이 브라우저에 의해 자동 해제되어
    // 있으므로, 다시 보일 때 재요청한다.
    function onVisibilityChange() {
      if (document.visibilityState === 'visible') void acquire()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      cancelled = true
      document.removeEventListener('visibilitychange', onVisibilityChange)
      void sentinelRef.current?.release()
      sentinelRef.current = null
    }
  }, [active])
}
