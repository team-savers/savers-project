// Service-worker update detection. The PWA plugin's auto-generated
// registration script only registers `/sw.js`; it never polls for new
// versions and never tells the page when one is waiting. This module fills
// that gap with the standard `navigator.serviceWorker` API (no virtual
// module) so a freshly deployed build actually reaches the device.
//
// The actual "apply the update" decision (reload vs. show a prompt) lives in
// the UI layer; this module only emits a single callback when a new worker is
// installed and waiting to take over.

// Interval between proactive `registration.update()` polls. We don't want to
// hammer the network, but in a disaster-response context an alert that opens
// a stale page can be dangerous, so we err on the side of "a few minutes".
// A constant (not a magic number) so the intent is obvious at the call site.
const UPDATE_POLL_INTERVAL_MS = 5 * 60 * 1000 // 5 minutes

interface InitSwUpdatesOptions {
  // Called when a newly installed worker is waiting to activate AND there is
  // already an active controller (i.e. this is an *update*, not the very first
  // install). The UI decides whether it is safe to reload right now or
  // whether the user must be prompted.
  onUpdateWaiting: () => void
}

// Returns a teardown function that removes every listener and timer this
// function installed. Callers MUST invoke it on unmount; otherwise the
// interval and listeners leak across HMR / remounts.
export function initSwUpdates(
  opts: InitSwUpdatesOptions,
): () => void {
  // SSR / unsupported guard. In environments without service worker support
  // there is nothing to do; return a no-op teardown.
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    return () => {}
  }

  let updateTimer: ReturnType<typeof setInterval> | null = null
  let registration: ServiceWorkerRegistration | null = null

  // Track which waiting worker we already reported so we don't fire the
  // callback on every poll for the same waiting SW (would cause the UI to
  // re-show the prompt repeatedly and could re-trigger a reload guard).
  let reportedWaitingScriptURL: string | null = null

  const notifyIfWaiting = (): void => {
    const reg = registration
    if (reg === null) return
    const waiting = reg.waiting
    // Only an update matters: if there is no active controller yet, this is
    // the very first install and the page will be controlled on next load
    // anyway — no action needed.
    if (
      waiting !== null &&
      typeof waiting.scriptURL === 'string' &&
      navigator.serviceWorker.controller !== null &&
      waiting.scriptURL !== reportedWaitingScriptURL
    ) {
      reportedWaitingScriptURL = waiting.scriptURL
      opts.onUpdateWaiting()
    }
  }

  // A new worker reached the "installed" state. If an old controller exists,
  // this is a pending update; report it immediately (don't wait for the next
  // poll) so the UI can react as soon as the worker is ready.
  const onUpdateFound = (): void => {
    const reg = registration
    if (reg === null || reg.installing === null) return
    const installingWorker = reg.installing
    installingWorker.addEventListener('statechange', () => {
      if (installingWorker.state === 'installed') {
        notifyIfWaiting()
      }
    })
  }

  // `controllerchange` fires when a new worker takes over (after skipWaiting).
  // We don't reload here — the UI owns the reload decision and its once-only
  // guard. We do, however, treat the change as a signal to re-check state for
  // diagnostics; the actual reload is gated in App.tsx.
  const onControllerChange = (): void => {
    // Intentionally empty: reload orchestration lives in App.tsx behind a
    // once-only guard. Keeping this listener lets us extend diagnostics later
    // without re-plumbing registration.
  }

  // Trigger path #2: when the tab becomes visible again, check for an update
  // immediately. A user who backgrounded the app for hours must not see a
  // stale page when they come back during an unfolding alert.
  const onVisibilityChange = (): void => {
    if (document.visibilityState === 'visible') {
      void checkForUpdate()
    }
  }

  const checkForUpdate = async (): Promise<void> => {
    if (registration === null) return
    try {
      await registration.update()
      // `update()` resolves after the browser has re-fetched sw.js; if that
      // produced a new waiting worker, notify from here as well (covers the
      // race where updatefound fired before our listener attached).
      notifyIfWaiting()
    } catch {
      // A failed poll (transient network blip) is not fatal — the next
      // interval or visibilitychange will retry. Swallowing the error here is
      // intentional, not "swallowing failures": the failure mode is "check
      // again later", which is the correct degraded behavior.
    }
  }

  let cancelled = false

  // Kick off registration. We don't call `register()` ourselves if a
  // registration already exists (the PWA plugin's auto-injected script
  // registers `/sw.js` on load); `getRegistration` reuses it so we don't
  // spawn a duplicate.
  void (async () => {
    try {
      let reg = await navigator.serviceWorker.getRegistration()
      if (reg === undefined) {
        reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' })
      }
      if (cancelled) return
      registration = reg
      registration.addEventListener('updatefound', onUpdateFound)
      // Initial state check in case a worker was already waiting before this
      // function ran (e.g. the page loaded after the SW had already updated).
      notifyIfWaiting()

      // Trigger path #3 (page-load fallback for notification entry): if the
      // user just tapped a push notification to open this tab, we cannot
      // distinguish that from a normal load, so we always do one immediate
      // check right after registration. This guarantees a notification-driven
      // entry sees the freshest version without delay.
      await checkForUpdate()

      // Trigger path #1: periodic polling.
      updateTimer = setInterval(() => {
        void checkForUpdate()
      }, UPDATE_POLL_INTERVAL_MS)
    } catch {
      // Registration itself failed (e.g. SW unsupported at runtime, or a
      // mixed-content block). Nothing we can recover here; the app still
      // works without offline support, so do not throw.
    }
  })()

  document.addEventListener('visibilitychange', onVisibilityChange)
  navigator.serviceWorker.addEventListener('controllerchange', onControllerChange)

  // Teardown: remove every listener and clear the interval. Returning this
  // is mandatory — a leaked interval would keep polling forever across
  // remounts and could re-fire the update callback after unmount.
  return () => {
    cancelled = true
    if (updateTimer !== null) {
      clearInterval(updateTimer)
      updateTimer = null
    }
    document.removeEventListener('visibilitychange', onVisibilityChange)
    navigator.serviceWorker.removeEventListener(
      'controllerchange',
      onControllerChange,
    )
    if (registration !== null) {
      registration.removeEventListener('updatefound', onUpdateFound)
    }
  }
}
