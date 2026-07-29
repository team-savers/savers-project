// Firestore adapter for the two-device surrogate-registration flow.
//
// WHY THIS EXISTS:
//   The /ops surrogate-registration scenario uses TWO devices. The welfare
//   worker's tablet fills in the registration; the ward's OWN phone is the
//   only device that can mint an FCM token (FCM tokens are per-browser). With
//   only an in-memory Map on the tablet's tab, the tablet never learns the
//   ward's token and the test send has nowhere to go. This adapter is the
//   temporary cross-device bridge.
//
// This Firestore path is a stand-in until the backend owns the server-side
// token→userId mapping. When it lands, client.ts swaps to the real HTTP
// endpoint and this file is deleted. This is an interim artifact, not a new
// contract surface.
//
// CRITICAL INVARIANT — unset env = current behavior, byte-for-byte:
//   The four VITE_FS_* vars must ALL be present to enable the store. If any
//   is missing, `isStoreEnabled()` returns false and client.ts falls through
//   to the original in-memory Map path with zero behavior change. "Unset is
//   the default" is a hard constraint and a safety property of the public
//   demo repo — no implicit Firestore use.
//
// SECOND APP, NOT THE DEFAULT:
//   The default Firebase app (src/firebase.ts) owns FCM for the team project.
//   We MUST NOT touch it. This adapter initializes a SECOND named app
//   (`'savers-store'`) so the store's project/auth domain stays isolated from
//   the FCM app. The name is passed as the 2nd arg to initializeApp.
//
// DEADLINE:
//   Every network read/write/subscribe here races a 10s deadline. Firestore
//   SDK calls do not accept an AbortSignal, so we wrap each promise with
//   Promise.race against a timer that rejects with a clear message. A blocked
//   store must surface as a thrown error — never an infinite spinner.
//
//   IMPORTANT — Firestore writes are NOT cancellable. When the timer fires on
//   a write, the SDK keeps retrying the Write stream in the background and the
//   write may still land later once connectivity returns. So the deadline on a
//   WRITE means "not confirmed within the deadline", NOT "the write failed".
//   The deadline is still worth keeping — the screen must not hang forever —
//   but the surfaced message says "확인되지 않았습니다" and tells the user to
//   refresh to see the actual outcome, rather than claiming the write failed.

import { initializeApp, type FirebaseApp } from 'firebase/app'
import {
  getFirestore,
  collection,
  deleteDoc,
  doc,
  setDoc,
  getDoc,
  getDocs,
  onSnapshot,
  runTransaction,
  type Unsubscribe as FsUnsubscribe,
} from 'firebase/firestore'
import type { RegistrationRecord } from './client'
import type { RegistrationTarget } from './types'

// The single collection this adapter touches. Document id = userId.
const COLLECTION_NAME = 'registrations'

// Env keys (read from import.meta.env only — never hardcoded). All four must
// be non-empty for the store to enable.
const FS_API_KEY = import.meta.env.VITE_FS_API_KEY
const FS_PROJECT_ID = import.meta.env.VITE_FS_PROJECT_ID
const FS_AUTH_DOMAIN = import.meta.env.VITE_FS_AUTH_DOMAIN
const FS_APP_ID = import.meta.env.VITE_FS_APP_ID

// Network deadline for every Firestore call. The store is a cross-device
// bridge that the operator tab and the ward phone wait on — a hung Firestore
// must not freeze either screen. 10s is generous for a single-region read and
// tight enough that the user never waits forever.
const DEADLINE_MS = 10000

// Whether all four required env vars are present. Memoized at module load —
// env does not change at runtime, so re-reading would be misleading.
function envPresent(): boolean {
  return (
    typeof FS_API_KEY === 'string' && FS_API_KEY !== '' &&
    typeof FS_PROJECT_ID === 'string' && FS_PROJECT_ID !== '' &&
    typeof FS_AUTH_DOMAIN === 'string' && FS_AUTH_DOMAIN !== '' &&
    typeof FS_APP_ID === 'string' && FS_APP_ID !== ''
  )
}

let _app: FirebaseApp | null = null
let _enabled: boolean | null = null

// Lazy-initialized so callers that never use the store never pay the init
// cost and so test code importing this module without env does not crash.
function ensureApp(): FirebaseApp | null {
  if (_enabled === null) {
    _enabled = envPresent()
  }
  if (!_enabled) return null
  if (_app === null) {
    // Second named app — does NOT touch the default FCM app in src/firebase.ts.
    _app = initializeApp(
      {
        apiKey: FS_API_KEY,
        authDomain: FS_AUTH_DOMAIN,
        projectId: FS_PROJECT_ID,
        appId: FS_APP_ID,
      },
      'savers-store',
    )
  }
  return _app
}

// Public enablement check. Pure — no side effects. client.ts / push.ts / pages
// branch on this before touching Firestore.
export function isStoreEnabled(): boolean {
  return ensureApp() !== null
}

// Race a Firestore promise against DEADLINE_MS. Resolves with the inner
// promise's value, or rejects with a clear timeout message. The inner
// promise is NOT cancelled (Firestore SDK has no abort), but the caller sees
// a deterministic rejection and the floating promise's eventual result is
// simply ignored by us — no UI waits on it.
//
// The rejection message is deliberately worded as "not confirmed", NOT
// "failed": Firestore writes cannot be cancelled, so a timed-out write may
// still land in the background once the connection returns. The message
// directs the user to refresh so they can observe the real outcome rather
// than be told (incorrectly) that the operation failed. Reads that time out
// are genuinely unresolved too, so the same honest wording fits both.
function withDeadline<T>(label: string, p: Promise<T>): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () =>
        reject(
          new Error(
            `${label}이(가) ${DEADLINE_MS}ms 안에 확인되지 않았습니다. ` +
              '네트워크 연결을 확인한 뒤 새로고침하여 실제 결과를 확인해 주세요.',
          ),
        ),
      DEADLINE_MS,
    )
  })
  return Promise.race([p, timeout]).finally(() => {
    if (timer !== undefined) clearTimeout(timer)
  })
}

// ---- Document shape -----------------------------------------------------
//
// RegistrationRecord (from client.ts) is the in-memory mock shape with
// operational metadata (sendState, lastSentAt, isRead, hasToken, phone) AND
// the full Profile surface (housing, mobility, vision, hearing, stairsOk,
// livesAlone, care, guardian, ...). In memory it is all present, but the
// PERSISTED document intentionally carries only an allow-list — see
// STORED_FIELDS below. Reads therefore cannot assume every Profile field is
// present; `toRecord` fills sane defaults for the fields the store no longer
// returns so the UI shape (RegistrationRecord) stays intact.

// Firestore may return Timestamp objects for any date-typed field; we don't
// persist any Date values (all our fields are string/boolean/null/enum), so a
// shallow cast of the doc data is sufficient for the persisted subset.
type StoredRecord = RegistrationRecord

// MINIMAL COLLECTION (allow-list, NOT a deny-list).
//
// The store is an unauthenticated, browser-direct Firestore bridge (see file
// header). Anyone with the public config can read these documents. To honour
// the project's minimal-collection constraint — *"Sensitive fields (location,
// disability status) are minimally collected and encrypted"* — the front half
// ("minimally collected") is enforced HERE by never writing the sensitive
// Profile fields in the first place. This adapter does NOT perform any
// encryption itself: it writes the allow-listed fields verbatim over HTTPS
// to Firestore, and whatever the transport layer protects stops there. The
// only safe sensitive field is one that is never sent, which is why the list
// below is curated so tightly.
//
// Why an allow-list and not a deny-list: if a future Profile extension adds
// another health/disability field, a deny-list would silently leak it here.
// The allow-list below is the exhaustive set of fields this store persists;
// anything not listed never reaches the wire.
//
// Every field below has a documented reason it must be persisted. The
// disabled/health/lifestyle survey answers (housing, mobility, stairsOk,
// vision, hearing, care, livesAlone, guardian, consents, dongCode,
// registeredBy, easyText, language) are NOT here: the cross-device flow only
// needs identification + operational state, and the /ops form keeps the full
// input in component memory where it is already shown to the operator.
const STORED_FIELDS = [
  'userId', // document id and /join lookup key — the ward's phone resolves its record by this.
  'name', // /join confirm screen greeting + /ops table name column.
  'dongName', // /ops table address column (human-readable; dongCode is derivable and is NOT needed cross-device).
  'phone', // ward's own contact number shown in the /ops table — operational, not a disability/health field.
  'sendState', // last test-send outcome (not_sent/sent/failed/no_token) shown in the /ops table.
  'lastSentAt', // timestamp string of the last send, shown in the /ops table.
  'isRead', // ward-side open acknowledgement shown in the /ops table.
  'hasToken', // whether the ward's phone has attached its FCM token — drives the /ops badge.
  'deviceToken', // the FCM token itself, needed by the bridge to actually dispatch.
] as const

// Compile-time check: every entry of STORED_FIELDS is a real key of
// RegistrationRecord. If a key is mistyped or RegistrationRecord changes in
// a way that removes one, this line fails to type-check. The binding is
// never read at runtime; the `void` avoids "unused" complaints.
const _storeFieldsAreRecordKeys: Array<keyof RegistrationRecord> = [
  ...STORED_FIELDS,
]
void _storeFieldsAreRecordKeys

// Build the persisted payload by projecting only STORED_FIELDS out of the
// in-memory record. A fresh key set is built deliberately (not
// `{ ...rec }` then delete) so a new field added to RegistrationRecord can
// never sneak through — only an explicit append to STORED_FIELDS exposes it.
//
// UNDEFINED IS DROPPED, NULL IS KEPT — why this distinction matters:
//   Firestore rejects `undefined` as a field value and throws, killing the
//   entire write silently from the caller's view. Some allow-listed fields
//   are legitimately absent at write time — most notably `deviceToken`,
//   which is not minted until the ward's phone scans the QR at /join. At
//   /ops registration time it is `undefined`, and feeding it to setDoc made
//   the whole registration disappear (no document, no UI change). The fix
//   is to omit undefined keys from the payload entirely.
//   `null` is a different story: `guardian: null` is the deliberate value
//   "no guardian", a confirmed fact we must persist. Lumping null together
//   with undefined would erase that signal. So only undefined is skipped.
//   The allow-list above is unchanged — omitting a key from one payload
//   does not let a sensitive field back in; STORED_FIELDS still gates what
//   can ever reach the wire.
function pickStored(rec: RegistrationRecord): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const key of STORED_FIELDS) {
    const value = rec[key]
    if (value !== undefined) {
      out[key] = value
    }
  }
  return out
}

// Coerce a persisted document back into the in-memory RegistrationRecord
// shape. Because the store carries only STORED_FIELDS, every other Profile
// field is absent in the persisted payload. We mark the record with
// `fromStore: true` so the UI can distinguish "the store did not return
// this field" (must be shown as 미저장) from "the in-memory mock genuinely
// holds this value" (shown as-is). The neutral defaults below remain for
// type-safety only — they are NOT facts and the UI must never render them
// as facts when fromStore is true.
//
// This is NOT data resurrection — no sensitive value is reconstructed. The
// only thing added is the fromStore marker so downstream code can tell
// "absent because not stored" apart from "absent because never set".
function toRecord(data: unknown): StoredRecord {
  const d = (data ?? {}) as Partial<RegistrationRecord>
  return {
    userId: d.userId ?? '',
    name: d.name ?? '',
    dongCode: d.dongCode ?? '',
    dongName: d.dongName ?? '',
    // 민감/건강 필드들은 저장소에 적히지 않는다(STORED_FIELDS 참조). fromStore
    // 마커가 true 일 때 UI 는 이 기본값들을 사실로 보여주지 않고 「미저장」
    // 으로 표시해야 한다 — 운영자가 잘못된 사실을 믿고 판단하는 일을 막기 위해.
    housing: d.housing ?? 'normal',
    mobility: d.mobility ?? 'ok',
    stairsOk: d.stairsOk ?? true,
    easyText: d.easyText ?? true,
    vision: d.vision ?? 'ok',
    hearing: d.hearing ?? 'ok',
    language: d.language ?? 'ko',
    livesAlone: d.livesAlone ?? true,
    care: d.care ?? null,
    guardian: d.guardian ?? null,
    registeredBy: d.registeredBy ?? 'guardian',
    consents: d.consents,
    phone: d.phone ?? null,
    sendState: d.sendState ?? 'not_sent',
    lastSentAt: d.lastSentAt ?? null,
    isRead: d.isRead ?? false,
    hasToken: d.hasToken ?? false,
    deviceToken: d.deviceToken ?? null,
    // Marker: this record was hydrated from the store, so the sensitive/
    // health fields above are placeholder defaults, NOT facts the operator
    // may rely on. Memory-mock records never set this flag (it defaults to
    // undefined / falsy), so the existing mock path renders unchanged.
    fromStore: true,
  }
}

// ---- Public write/read API --------------------------------------------

// Create or update a registration document. Document id = rec.userId. Only
// the allow-listed STORED_FIELDS are written — sensitive Profile fields
// (disability/health/lifestyle answers and the guardian contact) never reach
// the store. See STORED_FIELDS above for the per-field rationale.
export async function putRegistration(rec: RegistrationRecord): Promise<void> {
  const app = ensureApp()
  if (app === null) return
  const db = getFirestore(app)
  const payload = pickStored(rec)
  await withDeadline(
    'putRegistration',
    setDoc(doc(db, COLLECTION_NAME, rec.userId), payload),
  )
}

// One-shot read of the full collection. Used for the initial table load on
// /ops. Real-time updates go through subscribeRegistrations.
//
// FRESHNESS (offline masquerade): when the Firestore backend is unreachable
// the SDK does NOT throw — it silently serves results from its local cache.
// A try/catch around getDocs cannot see this outage. The only signal that
// the result is not server-confirmed is `snapshot.metadata.fromCache`. When
// that flag is true the data may be stale (the operator could be acting on
// out-of-date registrations), so we surface it instead of hiding it: we
// throw so the caller's catch path renders the outage honestly.
export async function listRegistrations(): Promise<RegistrationRecord[]> {
  const app = ensureApp()
  if (app === null) return []
  const db = getFirestore(app)
  const snap = await withDeadline(
    'listRegistrations',
    getDocs(collection(db, COLLECTION_NAME)),
  )
  // Cache-served result — the server was not reached, so this is not a
  // confirmed-fresh list. Throw rather than return a possibly-stale list
  // as if it were current; the caller shows the outage state.
  if (snap.metadata.fromCache) {
    throw new Error(
      '저장소 연결이 끊겨 확인되지 않은 정보입니다. 잠시 후 다시 시도해 주세요.',
    )
  }
  const out: RegistrationRecord[] = []
  snap.forEach((d) => {
    out.push(toRecord(d.data()))
  })
  return out
}

// Real-time subscription. cb fires with the full list on every change. The
// returned function MUST be called on unmount (no-op when the store is
// disabled, but still returned so callers can wire it unconditionally).
//
// onError is optional so existing single-arg callers keep compiling. When
// provided, Firestore's onSnapshot error argument is delivered there; the
// store's real-time stream never fails silently.
export function subscribeRegistrations(
  cb: (rows: RegistrationRecord[]) => void,
  onError?: (error: Error) => void,
): () => void {
  const app = ensureApp()
  if (app === null) {
    // Store disabled — emit nothing and return a no-op unsubscribe so the
    // caller's cleanup path works without branching.
    return () => {}
  }
  const db = getFirestore(app)
  const unsub: FsUnsubscribe = onSnapshot(
    collection(db, COLLECTION_NAME),
    (snap) => {
      // FRESHNESS (offline masquerade): a fromCache snapshot means the SDK
      // answered from local persistence without server confirmation. An
      // empty fromCache snapshot in particular would disguise an outage as
      // "no registrations" — a dangerous lie during an actual disaster
      // where the operator needs to know the channel is down. Route every
      // cache-served snapshot through the error callback so the caller can
      // flag the list as potentially stale (the caller may still render the
      // cached rows but MUST mark them as not fresh).
      if (snap.metadata.fromCache) {
        if (onError !== undefined) {
          onError(
            new Error(
              '저장소 연결이 끊겼습니다. 표시되는 목록은 최신이 아닐 수 있습니다.',
            ),
          )
        }
        return
      }
      const out: RegistrationRecord[] = []
      snap.forEach((d) => {
        out.push(toRecord(d.data()))
      })
      cb(out)
    },
    (error: Error) => {
      // Firestore realtime stream errored — surface, don't swallow. A blank
      // table here would hide a broken store from the operator.
      if (onError !== undefined) onError(error)
    },
  )
  return () => {
    unsub()
  }
}

// Result of attaching a device token. Discriminated union so callers narrow
// with `result.status` and cannot accidentally treat a conflict or a missing
// document as success.
export type AttachResult =
  | { status: 'stored'; token: string }
  | { status: 'conflict'; existingToken: string; attemptedToken: string }
  | { status: 'not_found' }

// `replace: true` forces an overwrite of an existing different token — only
// set after the user explicitly confirmed the replacement. Default is
// conflict-aware.
export interface AttachOptions {
  replace?: boolean
}

// The ward's phone attaches its freshly-minted FCM token to its own
// registration document. Called from push.ts after getToken succeeds.
//
// SAFETY (token replacement): a second phone scanning the same QR used to
// silently overwrite the first phone's token. To prevent that, this function
// reads the existing deviceToken atomically inside runTransaction:
//   1. If absent or equal → stores and returns { status: 'stored' }.
//   2. If present and different AND opts.replace !== true → returns
//      { status: 'conflict' }. The caller asks the user whether to replace,
//      then re-calls with replace: true.
//   3. If the document does not exist → returns { status: 'not_found' }.
//      The old behavior called tx.set on the missing branch, which CREATED a
//      nameless ghost row holding only the token. We must NOT resurrect a
//      deleted registration; the caller throws so the ward sees an honest
//      error instead of a fake "등록 완료".
//
// No-op (returns { status: 'stored' }) when the store is disabled.
export async function attachDeviceToken(
  userId: string,
  token: string,
  opts?: AttachOptions,
): Promise<AttachResult> {
  const app = ensureApp()
  if (app === null) {
    return { status: 'stored', token }
  }
  const db = getFirestore(app)
  const ref = doc(db, COLLECTION_NAME, userId)
  const replace = opts?.replace === true
  // Atomic read-then-write: the conflict check and the write happen as one
  // unit, so two phones racing to attach cannot both succeed with different
  // tokens.
  const outcome = await withDeadline(
    'attachDeviceToken',
    runTransaction(db, async (tx) => {
      const snap = await tx.get(ref)
      if (!snap.exists()) {
        // The registration is gone (deleted by the operator, or never existed).
        // Do NOT create a token-only ghost document. Return not_found so the
        // caller can surface an honest error to the ward.
        return { status: 'not_found' as const }
      }
      const data = snap.data() as { deviceToken?: string | null }
      const existing = data.deviceToken ?? null
      if (existing === null || existing === '' || existing === token) {
        tx.update(ref, { hasToken: true, deviceToken: token })
        return { status: 'stored' as const, token }
      }
      if (replace) {
        tx.update(ref, { hasToken: true, deviceToken: token })
        return { status: 'stored' as const, token }
      }
      return {
        status: 'conflict' as const,
        existingToken: existing,
        attemptedToken: token,
      }
    }),
  )
  return outcome
}

// Read a single registration by userId. Used by sendTestNotification to
// resolve the device token before calling the bridge. Returns null when the
// document does not exist or the store is disabled.
export async function getRegistration(
  userId: string,
): Promise<RegistrationRecord | null> {
  const app = ensureApp()
  if (app === null) return null
  const db = getFirestore(app)
  const snap = await withDeadline(
    'getRegistration',
    getDoc(doc(db, COLLECTION_NAME, userId)),
  )
  if (!snap.exists()) return null
  return toRecord(snap.data())
}

// Minimum-field read for the /join confirm screen. The ward's phone opens
// /join?u=<userId> and must verify identity — but it should not receive the
// full registration document, which carries phone, FCM deviceToken, and the
// allow-listed operational state. This function returns ONLY the three
// fields the confirm screen needs (name, dongName, registeredBy) in the
// contract's RegistrationTarget shape.
//
// LIMITATION (honest): Firestore's browser SDK has no server-side field
// projection on getDoc. This function calls getDoc, which downloads the
// WHOLE stored document over the wire, and then projects to the three
// fields in JavaScript before returning. So the returned value has only
// three fields, but phone and deviceToken (and every other stored field)
// DID travel to this device inside the SDK response and remain in SDK
// memory until garbage-collected. This is a known gap of the interim
// browser-direct bridge; closing it properly means routing through a
// backend endpoint that reads three fields server-side and returns only
// those — out of scope for this adapter today.
//
// Returns null when the document does not exist or the store is disabled.
export async function getRegistrationTarget(
  userId: string,
): Promise<RegistrationTarget | null> {
  const app = ensureApp()
  if (app === null) return null
  const db = getFirestore(app)
  const snap = await withDeadline(
    'getRegistrationTarget',
    getDoc(doc(db, COLLECTION_NAME, userId)),
  )
  if (!snap.exists()) return null
  const d = (snap.data() ?? {}) as Partial<RegistrationRecord>
  return {
    wardName: d.name ?? '',
    dongName: d.dongName ?? '',
    registeredBy: d.registeredBy ?? 'guardian',
  }
}

// Persist the send outcome (success or failure) against a registration. Used
// by client.ts sendTestNotification on the bridge path so a page refresh does
// not erase the dispatched/failed state. The deadline applies here too.
//
// NO-RESURRECT (deletion race): the operator can delete a ward's registration
// while a bridge send is still in flight. By the time the bridge response
// arrives and this function runs, the document may already be gone. A naive
// `setDoc(..., {merge:true})` would RE-CREATE that document as a ghost row
// holding only {sendState, lastSentAt} — the user deleted it on purpose and
// must not see it return. So we update ONLY when the document still exists:
// inside runTransaction we read first; if it's gone we return silently (the
// delete was intentional, there is nothing to record the send state against).
//
// sendState: 'sent' on bridge success, 'failed' on bridge failure,
// 'unconfirmed' on timeout (the browser closed the request; the bridge may
// have already dispatched the push). The caller supplies lastSentAt (already
// formatted) so this stays a thin writer.
export async function recordSendState(
  userId: string,
  sendState: 'sent' | 'failed' | 'unconfirmed',
  lastSentAt: string,
): Promise<void> {
  const app = ensureApp()
  if (app === null) return
  const db = getFirestore(app)
  const ref = doc(db, COLLECTION_NAME, userId)
  // Existence-guarded update: only write when the document still exists. If
  // it was deleted in the meantime we do nothing — the user's delete wins.
  await withDeadline(
    'recordSendState',
    runTransaction(db, async (tx) => {
      const snap = await tx.get(ref)
      if (!snap.exists()) {
        // The registration was deleted while the send was in flight. Do NOT
        // recreate it. The user's intent (remove this ward) stands.
        return
      }
      tx.update(ref, { sendState, lastSentAt })
    }),
  )
}

// Delete a registration document. Used by the /ops screen so an operator can
// remove a wrongly-registered ward (wrong name, duplicate, etc). Document
// id = userId. The 10s deadline applies like every network call here — a
// hung store must surface as a thrown error, not a silent no-op.
//
// No-op (returns immediately) when the store is disabled — client.ts handles
// the in-memory Map removal in that case.
export async function deleteRegistration(userId: string): Promise<void> {
  const app = ensureApp()
  if (app === null) return
  const db = getFirestore(app)
  await withDeadline(
    'deleteRegistration',
    deleteDoc(doc(db, COLLECTION_NAME, userId)),
  )
}
