// FCM push wiring for the foreground side.
// Permission is requested ONLY when requestPushPermission() is called from a
// user gesture — never at module load. The integrated service worker
// registration (src/sw.ts) is explicitly passed to getToken so FCM does not
// try to register a second SW.
//
// registerTokenWithServer used to be a no-op stub — the two-device
// surrogate-registration flow (tablet registers, ward's phone owns the FCM
// token) needs the phone's freshly-minted token to reach the operator's
// tab. When the Firestore store is enabled (VITE_FS_* set), the token is
// attached to that user's registration document so the /ops badge flips to
// "등록" and the test send can target it. When the store is disabled this
// is a quiet no-op again — the foreground-only demo flow still works.
//
// TWO ENTRY POINTS:
//   - requestPushPermission(userId, opts?): returns a TokenAttempt. Used by
//     the /demo foreground view (which passes { tokenOnly: true } so it never
//     touches the cross-device store — the demo userId has no registration
//     document) and any other foreground-only caller. Failure reasons are
//     surfaced distinctly instead of collapsed to null, so the screen can
//     tell the user exactly what went wrong.
//   - requestPushPermissionForJoin(userId, opts?): returns
//     PushPermissionResult. Used by /join, where a DIFFERENT device may
//     already hold the FCM slot. The conflict result is surfaced to
//     Join.tsx, which asks the ward in plain Korean whether to replace the
//     existing device and, only on explicit consent, re-calls with
//     replace:true. No path here silently swaps a safety-alert recipient.

import {
  getToken,
  onMessage,
  type MessagePayload,
  type Observer,
  type Unsubscribe,
} from 'firebase/messaging'
import { getFcmMessaging } from '../firebase'

// When the default Firebase app is absent (no VITE_FIREBASE_* env), push is
// unavailable. The obtainToken core surfaces this as a distinct `misconfigured`
// outcome so the screen can tell the user exactly why notifications are off
// instead of throwing through the render path.
import {
  attachDeviceToken,
  type AttachResult,
  isStoreEnabled,
} from '../api/firestore'

// Outcome of attaching the freshly-minted FCM token to the cross-device
// store, for the /join flow. Mirrors the AttachResult shape from firestore.ts
// so callers can branch on `status`:
//   - 'granted'    : permission granted AND token stored (or store disabled).
//   - 'denied'     : the user declined the notification permission prompt.
//   - 'conflict'   : a different device already holds the slot. The caller
//                    MUST ask before replacing; call again with
//                    { replace: true } only after explicit consent.
//   - 'unavailable': permission could not be obtained or no token issued
//                    (e.g. missing VAPID/SW, or prompt dismissed). Retryable.
export type PushPermissionResult =
  | { status: 'granted'; token: string }
  | { status: 'denied' }
  | { status: 'conflict'; existingToken: string; attemptedToken: string }
  | { status: 'unavailable' }

// Discriminated outcome of the token-acquisition core. Each failure mode
// carries its own reason so the caller can render the right plain-Korean
// guidance instead of a generic "something went wrong". `return null` is
// deliberately NOT used here — collapsing four distinct states into one
// would erase the reason before it ever reached the screen.
//
//   - unsupported       : the browser has no Notification API at all.
//   - denied            : the user declined (or dismissed) the prompt.
//   - misconfigured     : no VAPID key / no service worker — an operator
//                         setup problem, not something the user can fix.
//   - token_unavailable : getToken resolved without a token.
//   - timeout           : the network/permission step did not settle within
//                         TOKEN_DEADLINE_MS — the screen must never hang.
//   - ok                : a token was issued.
export type TokenAttempt =
  | { status: 'ok'; token: string }
  | { status: 'unsupported' }
  | { status: 'denied' }
  | { status: 'misconfigured' }
  | { status: 'token_unavailable' }
  | { status: 'timeout' }

// Bounding the token-acquisition step. getToken can hang indefinitely when
// the network or the messaging backend is slow; a vulnerable user staring
// at a frozen button is the failure mode this guards against. 10s matches
// the cross-device store deadline and is generous for a single token mint.
const TOKEN_DEADLINE_MS = 10000

// Persist the freshly-minted FCM token against the user's registration so
// the operator tablet (a different device) can dispatch to it. Returns the
// raw attach outcome — a conflict is NOT an error, it is a result the caller
// must handle. No-op returning { status: 'stored' } when the Firestore store
// is disabled (isStoreEnabled() false inside attachDeviceToken) — original
// behavior preserved.
async function registerTokenWithServer(
  userId: string,
  token: string,
  opts?: { replace?: boolean },
): Promise<AttachResult> {
  return attachDeviceToken(userId, token, opts)
}

// Race a promise against TOKEN_DEADLINE_MS. Resolves with the inner value,
// or rejects with a clear timeout marker so the caller can distinguish a
// hang from a denial. The inner promise is not cancelled — the SDK has no
// abort — but its eventual resolution is simply ignored by us.
function withTokenDeadline<T>(p: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('token_timeout')), TOKEN_DEADLINE_MS)
  })
  return Promise.race([p, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer)
  })
}

// Obtain the FCM token (shared core). Returns a discriminated TokenAttempt
// so every failure mode is distinguishable by the caller — the reason must
// survive all the way to the screen, not be flattened to null. MUST be
// called from a user gesture.
async function obtainToken(): Promise<TokenAttempt> {
  if (typeof Notification === 'undefined') {
    return { status: 'unsupported' }
  }
  // requestPermission can also hang on a slow/absent prompt UI; bound it.
  let permission: NotificationPermission
  try {
    permission = await withTokenDeadline(Notification.requestPermission())
  } catch {
    return { status: 'timeout' }
  }
  if (permission !== 'granted') {
    return { status: 'denied' }
  }
  // Explicitly use the integrated SW registration so FCM never spins up its
  // default firebase-messaging-sw.js (we deliberately do not ship one).
  let registration: ServiceWorkerRegistration
  try {
    registration = await withTokenDeadline(navigator.serviceWorker.ready)
  } catch {
    return { status: 'timeout' }
  }
  const vapidKey = import.meta.env.VITE_FIREBASE_VAPID_KEY
  if (!vapidKey) {
    return { status: 'misconfigured' }
  }
  // The messaging instance is null when Firebase env is missing (see
  // firebase.ts). Treat that exactly like a missing VAPID key: push is
  // not wired up, and the operator must fix env, not retry the prompt.
  const messaging = getFcmMessaging()
  if (messaging === null) {
    return { status: 'misconfigured' }
  }
  let token: string
  try {
    token = await withTokenDeadline(
      getToken(messaging, {
        vapidKey,
        serviceWorkerRegistration: registration,
      }),
    )
  } catch {
    return { status: 'token_unavailable' }
  }
  if (!token) {
    return { status: 'token_unavailable' }
  }
  return { status: 'ok', token }
}

// Options for requestPushPermission.
//
//   - tokenOnly : skip the cross-device store attach entirely. Used by the
//                 /demo foreground view, whose placeholder userId has NO
//                 registration document — attaching would attempt to write a
//                 document that does not exist and fail. We do NOT instead
//                 create a fake document; that would undo the no-resurrect
//                 guard. The demo path simply mints a token for foreground
//                 messaging and never touches the store.
export interface RequestPushOptions {
  tokenOnly?: boolean
}

// Request notification permission and obtain an FCM token.
//
// Returns a TokenAttempt. The /demo view consumes this with
// { tokenOnly: true } — it has no registration document to attach to, so it
// only mints a token for foreground messaging. Callers that DO have a real
// registration (a registered ward) omit tokenOnly and the freshly-minted
// token is attached to that user's cross-device registration when the store
// is enabled; when the store is disabled the attach is a no-op.
//
// MUST be called from a user gesture (e.g. button click) — browsers
// otherwise reject the permission prompt.
export async function requestPushPermission(
  userId: string,
  opts?: RequestPushOptions,
): Promise<TokenAttempt> {
  const attempt = await obtainToken()
  if (attempt.status !== 'ok') {
    return attempt
  }
  // tokenOnly (the /demo path) → never touch the cross-device store. The
  // demo userId is a placeholder with no registration document; attempting
  // to attach would try to update a document that does not exist. We do not
  // create a fake document either — that would resurrect a deleted-doc guard
  // on purpose. Foreground messaging still works with the minted token.
  if (opts?.tokenOnly === true) {
    return attempt
  }
  // Store disabled → nothing to attach; return the token so the foreground
  // flow proceeds. Store enabled → attach. On a non-join path a conflict is
  // not a meaningful state, so we simply do not pass replace and let attach
  // store-or-conflict; the returned token still represents a successful
  // foreground enrollment regardless of the store outcome.
  if (isStoreEnabled()) {
    await registerTokenWithServer(userId, attempt.token)
  }
  return attempt
}

// /join entry point. Same permission+token acquisition, but returns a
// PushPermissionResult so the caller can distinguish denial (one way —
// browser won't re-prompt) from a conflict (recoverable via user consent)
// from a transient unavailability (retryable).
//
// opts.replace === true forces an overwrite of an existing different token —
// only the caller knows whether the user explicitly confirmed a device swap.
// Default is conflict-aware.
export async function requestPushPermissionForJoin(
  userId: string,
  opts?: { replace?: boolean },
): Promise<PushPermissionResult> {
  const attempt = await obtainToken()
  if (attempt.status === 'unsupported') {
    return { status: 'unavailable' }
  }
  if (attempt.status === 'denied') {
    // The browser only lets us ask once. A 'default' here (prompt dismissed
    // without a choice) is still effectively denied for this attempt —
    // treat anything other than 'granted' as denial so the screen tells the
    // user to re-enable via browser settings.
    return { status: 'denied' }
  }
  if (
    attempt.status === 'misconfigured' ||
    attempt.status === 'token_unavailable' ||
    attempt.status === 'timeout'
  ) {
    return { status: 'unavailable' }
  }

  const token = attempt.token

  // When the cross-device store is disabled, there is nothing to attach the
  // token to — return granted so the foreground flow proceeds exactly as
  // before. When the store is enabled, attach and surface any conflict.
  if (!isStoreEnabled()) {
    return { status: 'granted', token }
  }

  const result = await registerTokenWithServer(userId, token, opts)
  if (result.status === 'stored') {
    return { status: 'granted', token }
  }
  if (result.status === 'not_found') {
    // The registration document is gone — the operator deleted it between the
    // ward opening the QR confirm screen and tapping "알림 받기", or it never
    // existed. We MUST NOT report success here: the previous flow silently
    // created a token-only ghost row on /ops and showed the ward a green
    // "등록 완료" for a record that no longer existed. Throw with a plain-
    // Korean "찾을 수 없습니다" message so the ward sees an honest error.
    throw new Error('등록 정보를 찾을 수 없습니다. 운영자에게 문의해 주세요.')
  }
  return {
    status: 'conflict',
    existingToken: result.existingToken,
    attemptedToken: result.attemptedToken,
  }
}

// Subscribe to FCM messages that arrive while the page is in the foreground.
// The callback receives the message payload; the caller decides how to render
// it (banner, toast, etc.). When Firebase env is absent the returned
// unsubscribe is a no-op — the page still renders, push simply does nothing.
export function onForegroundMessage(
  cb: ((payload: MessagePayload) => void) | Observer<MessagePayload>,
): Unsubscribe {
  const messaging = getFcmMessaging()
  if (messaging === null) {
    return () => {}
  }
  return onMessage(messaging, cb)
}
