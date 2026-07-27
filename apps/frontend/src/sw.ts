/// <reference lib="webworker" />

// Integrated service worker: Workbox precaching + FCM background message
// handling in a single file. Do NOT add a root firebase-messaging-sw.js;
// both SWs would compete for the same scope and registration would race.

import { precacheAndRoute } from 'workbox-precaching'
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

initializeApp(firebaseConfig)

// Workbox precache manifest is injected by vite-plugin-pwa at build time.
precacheAndRoute(self.__WB_MANIFEST)

const messaging = getMessaging()

// Background push handler: FCM messages arriving while the page is closed
// or backgrounded are surfaced as a system notification. The `data.url`
// payload drives where notificationclick lands.
onBackgroundMessage(messaging, (payload) => {
  const title = payload.notification?.title ?? payload.data?.title ?? '세이버스'
  const body = payload.notification?.body ?? payload.data?.body ?? ''
  const url = (payload.data?.url as string | undefined) ?? '/'
  void self.registration.showNotification(title, {
    body,
    data: { url },
  })
})

// notificationclick: focus an existing client on the target URL if possible,
// otherwise open a new window. Falls back to '/' when no url is set.
self.addEventListener('notificationclick', (event) => {
  const url = (event.notification.data?.url as string | undefined) ?? '/'
  event.notification.close()
  event.waitUntil(
    (async () => {
      const targetPath = (() => {
        try {
          return new URL(url, self.location.origin).pathname
        } catch {
          return '/'
        }
      })()
      const allClients = await self.clients.matchAll({
        type: 'window',
        includeUncontrolled: true,
      })
      for (const client of allClients) {
        let clientPath = '/'
        try {
          clientPath = new URL(client.url).pathname
        } catch {
          // Ignore malformed client URLs; fall through to next iteration.
          continue
        }
        if (clientPath === targetPath) {
          await client.focus()
          return
        }
      }
      await self.clients.openWindow(url)
    })(),
  )
})
