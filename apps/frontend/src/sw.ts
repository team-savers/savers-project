/// <reference lib="webworker" />

// Integrated service worker: Workbox precaching + FCM background message
// handling in a single file. Do NOT add a root firebase-messaging-sw.js;
// both SWs would compete for the same scope and registration would race.

import { clientsClaim, type RouteHandlerCallback } from 'workbox-core'
import {
  cleanupOutdatedCaches,
  createHandlerBoundToURL,
  precacheAndRoute,
} from 'workbox-precaching'
import { NavigationRoute, registerRoute } from 'workbox-routing'
import { initializeApp } from 'firebase/app'
import { getMessaging, onBackgroundMessage } from 'firebase/messaging/sw'

// `self` in a service worker is a ServiceWorkerGlobalScope. The WebWorker lib
// gives us most of the surface; we extend it with the Workbox-injected precache
// manifest that vite-plugin-pwa replaces at build time.
declare const self: ServiceWorkerGlobalScope & {
  __WB_MANIFEST: Array<{ url: string; revision: string | null }>
}

// Firebase web config is read from Vite env vars. Values live only in
// apps/frontend/.env.local (gitignored); the committed .env.example carries
// key names only. This repo is public — never hardcode real values here.
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

// Precache fallback bound to the SPA shell, used when the network is
// unreachable so that navigation (including `/a?t=...`) still resolves to the
// last cached `index.html` — the offline hard-constraint.
//
// This handler MUST be created AFTER `precacheAndRoute` has populated the
// precache cache: `createHandlerBoundToURL` looks the URL up in the precache
// list at call time and throws synchronously if it is missing, which would
// abort module evaluation and (because there is then no installing worker)
// leave the site with no active worker at all — breaking push registration.
// We keep it lazy and let the navigation route build it on first use so that
// the very creation step never blocks module completion; if the precache list
// genuinely has no `index.html`, we log and fall back to a direct cache match.
let precacheNavigationFallback: RouteHandlerCallback | undefined

// All cache/routing setup is isolated: a throwing line here used to abort the
// whole module, which silently killed the SW (no install -> no active worker
// -> `navigator.serviceWorker.ready` never resolved -> push registration
// timed out). Notification delivery is the last-resort function of a disaster
// app and must survive a routing misconfiguration, so we log the reason and
// keep evaluating.
try {
  // Workbox precache manifest is injected by vite-plugin-pwa at build time.
  precacheAndRoute(self.__WB_MANIFEST)
  // Drop precache entries from older SW versions so they don't accumulate.
  cleanupOutdatedCaches()
  // Now that the precache list is registered it is safe to bind the fallback.
  // Empty/degenerate manifests can still throw here; we keep going so that
  // the rest of the worker (push, notificationclick) stays functional.
  try {
    precacheNavigationFallback = createHandlerBoundToURL('index.html')
  } catch (fallbackError) {
    console.error(
      '[sw] precache navigation fallback could not be bound; ' +
        'offline /a?t= entry will use a direct cache lookup instead',
      fallbackError,
    )
  }
} catch (cacheError) {
  console.error(
    '[sw] precache/routing setup failed; continuing with degraded caching',
    cacheError,
  )
}

try {
  // SPA navigation: every navigation request (incl. /a?t=...) must resolve to
  // the SPA shell. Previously this was served purely from the precache, which
  // meant a freshly deployed `index.html` never reached the device while online
  // — the browser kept rendering the old cached shell until the user manually
  // cleared cache.
  //
  // Behavior: try the NETWORK first for navigation so a fresh build's
  // `index.html` is served as soon as the device is online. If the network is
  // unreachable (offline hard-constraint — `/a?t=...` MUST still open), fall
  // back to the precached shell exactly as before. The fallback is
  // load-bearing: do not remove it.
  registerRoute(
    new NavigationRoute(async (params) => {
      const request = params.request
      try {
        const response = await fetch(request, {
          credentials: 'same-origin',
          redirect: 'follow',
        })
        // Only trust OK-ish responses from the network; a 4xx/5xx should fall
        // through to the precache shell rather than rendering an error page.
        if (response.ok || response.type === 'opaqueredirect') {
          return response
        }
      } catch {
        // Network unreachable — fall through to the precache fallback below.
        // This is the offline path and the expected degraded mode; swallowing
        // here is correct, not a swallowed failure.
      }
      // Prefer the bound precache handler when it was built successfully.
      // Wrap it so an async rejection (e.g. a precache miss surfacing as a
      // thrown promise) flows into the shell fallback instead of aborting the
      // navigation and surfacing a 503 to the user.
      if (precacheNavigationFallback) {
        try {
          return await precacheNavigationFallback(params)
        } catch (boundError) {
          console.error(
            '[sw] bound navigation fallback rejected; trying shell cache',
            boundError,
          )
        }
      }
      // Fallback construction failed (or the bound handler rejected): still
      // honor the offline hard-constraint by looking the SPA shell up in the
      // cache directly. The original request (e.g. `/a?t=...`) is not a
      // precached key, so matching against it finds nothing and the user sees
      // a 503 in place of the app shell — match `index.html` instead.
      const shellResponse = await caches.match('index.html', {
        ignoreSearch: true,
      })
      if (shellResponse) return shellResponse
      return new Response('오프라인 상태입니다. 잠시 뒤 다시 시도해 주세요.', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' },
      })
    }),
  )
} catch (routeError) {
  console.error('[sw] navigation route registration failed', routeError)
}

// Activate the new SW immediately instead of waiting for every tab to close.
// `registerType: 'autoUpdate'` only drives the registration script; under
// injectManifest the SW itself must call these to take over.
try {
  self.skipWaiting()
  clientsClaim()
} catch (lifecycleError) {
  console.error('[sw] skipWaiting/clientsClaim failed', lifecycleError)
}

// FCM background delivery. Kept in its own block so a Firebase init failure
// cannot take down notification handling that only needs the SW to be alive.
let messagingInitialized = false
try {
  initializeApp(firebaseConfig)
  const messaging = getMessaging()
  // Background push handler: FCM messages arriving while the page is closed
  // or backgrounded are surfaced as a system notification. The `data.url`
  // payload drives where notificationclick lands.
  // contract: data-only, no notification block
  onBackgroundMessage(messaging, (payload) => {
    // Read payload.data first. FCM SDK auto-renders messages that carry a
    // `notification` block, which would double-notify; the backend contract is
    // data-only. Reading data first also means we always have the
    // url for the landing page even when a notification block slips through.
    const data = (payload.data ?? {}) as Record<string, string | undefined>
    const title = data.title ?? payload.notification?.title ?? '세이버스'
    const body = data.body ?? payload.notification?.body ?? ''
    const url = (data.url as string | undefined) ?? '/'
    // Return the promise so it threads through the SDK's event.waitUntil chain.
    // `void`-dropping it can let the SW terminate before the notification shows
    // (intermittent, easily mis-blamed on the environment).
    return self.registration.showNotification(title, {
      body,
      data: { url },
    })
  })
  messagingInitialized = true
} catch (fcmError) {
  console.error('[sw] FCM background messaging setup failed', fcmError)
}

// notificationclick: focus an existing client on the target URL if possible,
// otherwise open a new window. Falls back to '/' when no url is set.
// Match on the full URL (not pathname) and navigate the focused tab to the
// new alert URL, so a stale `/a?t=prev-session` tab no longer shows the old
// alert when a fresh one arrives. Registered independently of FCM so that a
// Firebase init failure cannot break deep-linking.
self.addEventListener('notificationclick', (event) => {
  const rawUrl = (event.notification.data?.url as string | undefined) ?? '/'
  event.notification.close()
  event.waitUntil(
    (async () => {
      // Resolve the destination exactly once and constrain it to this origin.
      // A notification payload must never send the user to an arbitrary page:
      // the URL is parsed against our own origin, and anything that fails to
      // parse or resolves to a different origin collapses to the SPA root.
      // The same-origin check applies to the destination itself (not just to
      // tab selection), so `https://evil.example/...`, protocol-relative
      // `//evil.example/...`, empty strings, and malformed URLs all land on
      // `/`. `/a?t=...&s=...` is same-origin and continues to open normally.
      const targetUrl = (() => {
        try {
          const parsed = new URL(rawUrl, self.location.origin)
          if (parsed.origin !== self.location.origin) {
            return new URL('/', self.location.origin).toString()
          }
          return parsed.toString()
        } catch {
          return new URL('/', self.location.origin).toString()
        }
      })()
      const allClients = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true,
      })
      for (const client of allClients) {
        let clientUrl: string
        try {
          clientUrl = new URL(client.url).toString()
        } catch {
          // Ignore malformed client URLs; fall through to next iteration.
          continue
        }
        if (clientUrl === targetUrl) {
          await client.focus()
          return
        }
      }
      // No exact match: focus the first same-origin window we find and navigate
      // it to the target URL (avoids opening a redundant tab when the PWA is
      // already open on a different alert session). same-origin only.
      // If a client rejects the navigation (or returns null), keep going so a
      // single bad client cannot abort the whole waitUntil chain — try the
      // next window, and finally open a new one on the resolved destination.
      for (const client of allClients) {
        let sameOrigin = false
        try {
          sameOrigin = new URL(client.url).origin === self.location.origin
        } catch {
          continue
        }
        if (sameOrigin) {
          try {
            await client.focus()
            const navigated = await client.navigate(targetUrl)
            if (navigated) {
              return
            }
          } catch {
            // This client refused the navigation; try the next one or fall
            // through to opening a fresh window below.
          }
        }
      }
      await self.clients.openWindow(targetUrl)
    })(),
  )
})

// Lifecycle markers: module completion and install/activate success are
// distinct events, and the bug fixed here lived exactly in the gap between
// them. These logs are the only external evidence that the worker reached
// each stage; no tokens or keys are emitted.
self.addEventListener('install', () => {
  console.log('[sw] install: reached', {
    messaging: messagingInitialized,
    fallback: precacheNavigationFallback ? 'bound' : 'unbound',
  })
})
self.addEventListener('activate', () => {
  console.log('[sw] activate: reached')
})
console.log('[sw] module evaluated')
