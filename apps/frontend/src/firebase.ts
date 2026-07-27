// Firebase initialization for the browser (foreground) side.
// Config is read from Vite env vars only — never hardcode values (public repo).
// See apps/frontend/.env.example for the key list.

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

export const firebaseApp: FirebaseApp = initializeApp(firebaseConfig)

// Messaging requires a browser context; lazy-init so callers that never use
// push don't pay the cost, and so server-side or test harnesses don't crash
// on import.
let _messaging: Messaging | null = null
export function getFcmMessaging(): Messaging {
  if (_messaging === null) {
    _messaging = getMessaging(firebaseApp)
  }
  return _messaging
}
