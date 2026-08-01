// Firebase initialization for the browser (foreground) side.
// Config is read from Vite env vars only — never hardcode values (public repo).
// See apps/frontend/.env.example for the key list.
//
// Empty-env safety: when the required env vars are absent (a fresh clone,
// a judge/teammate running the build locally) the app MUST still render —
// only push is disabled. The resolved app is nullable; consumers branch on
// null before touching messaging. The disabled state is surfaced via
// console.warn so a developer can see why push is inert instead of
// guessing. With a complete config the behavior is identical to a plain
// initializeApp at module scope.

import { initializeApp, type FirebaseApp } from 'firebase/app'
import { getMessaging, type Messaging } from 'firebase/messaging'

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

// A config field is considered present only when it is a non-empty string.
// `import.meta.env` is typed as string | boolean | undefined; boolean false
// or undefined both count as "missing".
function hasValue(v: unknown): boolean {
  return typeof v === 'string' && v !== ''
}

// Whether the default FCM app can be initialized at all. initializeApp
// cannot proceed reliably without apiKey/authDomain/projectId/appId; checking
// the full set avoids a half-initialized app that fails later at an opaque
// point inside the SDK. Exported so tests and consumers can read the
// configured state without triggering the SDK path.
export function isFirebaseConfigured(): boolean {
  return (
    hasValue(firebaseConfig.apiKey) &&
    hasValue(firebaseConfig.authDomain) &&
    hasValue(firebaseConfig.projectId) &&
    hasValue(firebaseConfig.storageBucket) &&
    hasValue(firebaseConfig.messagingSenderId) &&
    hasValue(firebaseConfig.appId)
  )
}

// Memoized resolver state. `undefined` = not yet resolved, `null` = env
// missing (push disabled), otherwise the initialized FirebaseApp.
let _app: FirebaseApp | null | undefined

function resolveApp(): FirebaseApp | null {
  if (_app !== undefined) return _app
  if (!isFirebaseConfigured()) {
    // Report the disabled path: a developer cloning this repo without a
    // .env needs to see WHY push is inert. The message names the env prefix
    // and the example file so the fix is discoverable.
    console.warn(
      '[SAVERS] Firebase 환경변수가 설정돼 있지 않아 웹 푸시(FCM)를 사용할 수 없습니다. ' +
        '화면은 정상적으로 동작하지만 알림 수신은 불가합니다. ' +
        'apps/frontend/.env.example 을 참고해 VITE_FIREBASE_* 값을 채워 주세요.',
    )
    _app = null
    return null
  }
  _app = initializeApp(firebaseConfig)
  return _app
}

// Explicit accessor for the default FirebaseApp. Returns null when env is
// absent — callers must branch on null and surface "push unavailable".
// Eagerly initializing at module scope would crash a fresh clone before any
// screen renders; the lazy gate keeps the page alive.
export function getFirebaseApp(): FirebaseApp | null {
  return resolveApp()
}

// Convenience for consumers that only want to know whether the app resolved.
export function hasFirebaseApp(): boolean {
  return resolveApp() !== null
}

// Messaging requires a browser context; lazy-init so callers that never use
// push don't pay the cost, and so test code importing this module without
// env does not crash. Returns null when Firebase config is missing — callers
// must branch on null and treat it as "push unavailable".
let _messaging: Messaging | null | undefined
export function getFcmMessaging(): Messaging | null {
  if (_messaging !== undefined) return _messaging
  const app = resolveApp()
  if (app === null) {
    _messaging = null
    return null
  }
  _messaging = getMessaging(app)
  return _messaging
}
