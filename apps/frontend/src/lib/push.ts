// FCM push wiring for the foreground side.
// Permission is requested ONLY when requestPushPermission() is called from a
// user gesture — never at module load. The integrated service worker
// registration (src/sw.ts) is explicitly passed to getToken so FCM does not
// try to register a second SW.

import {
  getToken,
  onMessage,
  type MessagePayload,
  type Observer,
  type Unsubscribe,
} from 'firebase/messaging'
import { getFcmMessaging } from '../firebase'

// Token registration against the backend is intentionally a no-op here.
// The endpoint and payload shape will be defined once packages/contracts is
// finalized; replace this stub at that point.
async function registerTokenWithServer(_token: string): Promise<void> {
  // TODO: packages/contracts 확정 시 교체 — POST /v1/devices/register 등.
}

// Request notification permission and obtain an FCM token.
// Returns the token on success, or null if the user denied or no token was
// issued. MUST be called from a user gesture (e.g. button click) — browsers
// otherwise reject the permission prompt.
export async function requestPushPermission(): Promise<string | null> {
  if (typeof Notification === 'undefined') {
    return null
  }
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    return null
  }

  // Explicitly use the integrated SW registration so FCM never spins up its
  // default firebase-messaging-sw.js (we deliberately do not ship one).
  const registration = await navigator.serviceWorker.ready
  const vapidKey = import.meta.env.VITE_FIREBASE_VAPID_KEY
  if (!vapidKey) {
    return null
  }

  const token = await getToken(getFcmMessaging(), {
    vapidKey,
    serviceWorkerRegistration: registration,
  })
  if (!token) {
    return null
  }

  await registerTokenWithServer(token)
  return token
}

// Subscribe to FCM messages that arrive while the page is in the foreground.
// The callback receives the message payload; the caller decides how to render
// it (banner, toast, etc.).
export function onForegroundMessage(
  cb: ((payload: MessagePayload) => void) | Observer<MessagePayload>,
): Unsubscribe {
  return onMessage(getFcmMessaging(), cb)
}
