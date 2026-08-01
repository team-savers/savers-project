// The ONLY module components and pages may import. Routes between mock and
// real HTTP via VITE_USE_MOCK (defaults to true so the app works with no
// backend). Pages that import from './mock' or './http' directly are a
// defect — the whole point of this file is that the adapter swap is
// transparent to consumers.
//
// The canonical contract paths are re-exported from './http' here so that
// the v0.3 endpoint surface (e.g. POST /v1/shelters/search, which replaced
// the old GET /v1/shelters) is visible at the API boundary without
// consumers reaching past this module.
//
// The browser-facing v0.3 ApiClient methods (mirroring operationIds in
// packages/contracts/openapi.yaml 1:1):
//   getSession · postSessionResponse · getRegistrationTarget ·
//   searchShelters · postChat · registerDevice · unregisterDevice ·
//   getGuardianStatus · postGuardianAcknowledge
// (The internal `postGenerate` operationId is backend↔ai-engine only and is
// intentionally not on this client.)

import type { ApiClient, Ack, Profile } from './types'
import { mockAdapter } from './mock'
import { httpAdapter, PATH_SHELTERS_SEARCH } from './http'
import {
  isStoreEnabled,
  putRegistration as fsPut,
  listRegistrations as fsList,
  getRegistration as fsGet,
  recordSendState as fsRecordSend,
  deleteRegistration as fsDelete,
} from './firestore'
import { substituteAdminTerms } from '../lib/readability'

// Re-export so /ops and Join.tsx can subscribe without reaching past this
// module (the "components import only from client.ts" rule still holds).
export { isStoreEnabled }
export { subscribeRegistrations, getRegistration } from './firestore'
export { getRegistrationTarget } from './firestore'

const useMock =
  (import.meta.env.VITE_USE_MOCK ?? 'true').toLowerCase() !== 'false'

export const api: ApiClient = useMock ? mockAdapter : httpAdapter

// Re-exported contract path so the POST /v1/shelters/search migration stays
// discoverable at the client boundary. `void`-tagged to avoid tree-shaking
// stripping it from production builds before the real fetch lands.
export { PATH_SHELTERS_SEARCH }
void PATH_SHELTERS_SEARCH

// ---- /ops (운영자 등록 화면) mock-only helpers ---------------------------
//
// These functions exist for the /ops surrogate-registration screen
// (guardian/welfare-center/employer registers a ward). They are NOT part of
// the v0.3 ApiClient surface (the contract has no registration-write
// endpoint yet — only GET /v1/registration/{token} for the confirm screen).
//
// 컴포넌트는 오직 이 모듈에서만 import 해야 한다. 그래서 이 헬퍼들은
// './mock' 이 아니라 여기서 export 된다. 저장소는 인메모리 Map 을 쓴다 —
// 공개 데모 레포에서 브라우저 영속 저장은 one-way door 이므로 금지한다.

// ---- mock-only /ops record --------------------------------------------
//
// `Profile` (./types.ts) is a 1:1 hand-translation of
// packages/contracts/openapi.yaml and MUST NOT be edited from the frontend
// side — the comment at the top of types.ts forbids it, and the spec is the
// single source of truth for the field surface. The /ops screen needs a few
// extra operational columns (피보호자 전화번호 / 발송 상태 / 발송 시각 /
// 읽음 여부 / 토큰 보유) that have no place in the contract yet — they are
// operational metadata that only exists while the /ops session is open. So
// they live here as a mock-only `RegistrationRecord` extension. When/if the
// contract grows a registration-write endpoint that carries these fields,
// they get promoted into the spec and types.ts together with openapi.yaml —
// not before.
//
// `phone` rationale: /ops 화면에는 "피보호자 전화번호" 가 보여야 한다.
// 스펙의 `Guardian.phone` 은 보호자 연락처이지 피보호자 본인 번호가
// 아니므로, 피보호자 전화는 실제 새 필드다(중복이 아니다). mock 전용으로
// 여기 두면, 백엔드가 아직 노출하지 않기로 한 필드를 contract 에 확정
// 짓지 않고도 데모에서 컬럼을 보여줄 수 있다.

// Send outcome for a registration record. 'unconfirmed' is distinct from
// 'failed': the bridge may have already dispatched the push but the response
// did not arrive within the deadline (the browser closed the request, not
// the server). Recording 'unconfirmed' keeps the operator from treating the
// send as a failure and re-dispatching the SAME disaster alert twice. The
// operator must refresh to learn the real outcome rather than retry.
export type SendState =
  | 'not_sent'
  | 'sent'
  | 'failed'
  | 'unconfirmed'
  | 'no_token'

export interface RegistrationRecord extends Profile {
  // 피보호자 본인 전화번호. Mock-only — see block comment above.
  phone: string | null
  // 테스트 발송 상태. 'no_token' is set automatically at seed time when
  // hasToken === false — no manual send attempt is made for such users.
  sendState: SendState
  // 마지막 발송 시각(HH:MM:SS). null until a successful send.
  lastSentAt: string | null
  // 읽음 여부. Mock simulates "사용자가 알림을 열었는지" — toggled only for
  // seed personas; runtime /ops does not flip this (이 화면은 운영자 사이드만
  // 다루고 피보호자 사이드는 다루지 않는다).
  isRead: boolean
  // 디바이스 토큰 보유 여부. false 면 발송 시도 없이 'no_token' 상태로
  // 표시된다(실사용에서는 FCM 등록 전 상태와 동일).
  hasToken: boolean
  // FCM 토큰 원문. Firestore(store) 경로에서만 채운다 — 폰이
  // attachDeviceToken(userId, token) 로 저장소에 적어두면, /ops 발송
  // 시 브리지 본문에 실려 함께 나간다. 메모리 mock 경로에서는 사용하지
  // 않으므로 optional + nullable.
  deviceToken?: string | null
  // 저장소(Firestore)에서 읽어온 레코드임을 나타내는 마커. true 이면
  // health/disability/lifestyle 필드(housing·mobility·stairsOk·vision·
  // hearing·livesAlone·care·guardian·consents·easyText 등)는 저장소에
  // 적히지 않았기 때문에 toRecord 가 채운 중립 기본값일 뿐 사실이 아니다.
  // UI 는 이 마커가 true 일 때 해당 필드를 「미저장」으로 표시해야 한다 —
  // 사실처럼 보여주면 운영자가 잘못 판단한다(예: 계단 불가자를 가능으로 표시).
  // 메모리 mock 경로는 이 플래그를 설정하지 않으므로 기존 동작이 유지된다.
  fromStore?: boolean
}

// In-memory store. Keyed by userId. Survives across renders (module
// singleton) but resets on full page reload — acceptable for a demo screen
// whose data is not persisted anywhere in this scope.
const registrations = new Map<string, RegistrationRecord>()

// ---- helpers -----------------------------------------------------------

// Returns "HH:MM:SS" for the current wall-clock time. Used to stamp the
// `lastSentAt` column. Kept here (not exported) because it is a mock detail.
function nowHMS(): string {
  const d = new Date()
  const pad = (n: number): string => n.toString().padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// Seeds the store with the demo personas on first access so the /ops
// table is not empty on first paint. Idempotent — only fills missing keys.
//
// 분포 요구사항(11인):
//   - not_sent   : 8  (발송을 한 번도 하지 않은 기본 상태)
//   - sent+read  : 1  (발송 완료 + 사용자가 알림을 읽음)
//   - sent+unread: 1  (발송 완료 + 아직 읽지 않음)
//   - no_token   : 1  (토큰 없음 — 발송 시도 자체가 불가)
//
// "발송 가능한 사용자에게만 [발송] 버튼이 의미가 있다" — 그래서
// 'no_token' 페르소나는 처음부터 sendState='no_token' 으로 시드하고,
// [테스트 발송] 핸들러가 그들에 대해 발송을 시도할 필요가 없다. 분포는
// 입력 배열의 처음 11 키에 결정적으로 적용되어, 렌더된 행을 읽는 쪽에서
// 안정적인 개수를 보도록 한다.
const SEED_DISTRIBUTION: ReadonlyArray<{
  sendState: SendState
  isRead: boolean
  hasToken: boolean
}> = [
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p001
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p002
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p003
  { sendState: 'sent', isRead: true, hasToken: true }, // p004  — read
  { sendState: 'sent', isRead: false, hasToken: true }, // p005  — unread
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p006
  { sendState: 'no_token', isRead: false, hasToken: false }, // p007 — no token
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p008
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p009
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p010
  { sendState: 'not_sent', isRead: false, hasToken: true }, // p011
]

// 피보호자 본인 전화번호 시드값. 모두 가상 번호이며, 실대역과 절대 겹치지
// 않는 예약 번호(가운데 자리 0000)를 써서 데모 데이터임이 한눈에 드러나게
// 한다. null 엔트리는 "전화번호 미확보" 상태를 표현(p007).
const SEED_WARD_PHONES: ReadonlyArray<string | null> = [
  '010-0000-0001',
  '010-0000-0002',
  '010-0000-0003',
  '010-0000-0004',
  '010-0000-0005',
  '010-0000-0006',
  null, // p007 — 전화번호 미확보 상태 표현
  '010-0000-0008',
  '010-0000-0009',
  '010-0000-0010',
  '010-0000-0011',
]

export function seedRegistrations(profiles: ReadonlyArray<Profile>): void {
  let i = 0
  for (const p of profiles) {
    if (!registrations.has(p.userId)) {
      const dist = SEED_DISTRIBUTION[i] ?? SEED_DISTRIBUTION[0]
      const phone = SEED_WARD_PHONES[i] ?? null
      const lastSentAt = dist.sendState === 'sent' ? '00:00:00' : null
      registrations.set(p.userId, {
        ...p,
        phone,
        sendState: dist.sendState,
        lastSentAt,
        isRead: dist.isRead,
        hasToken: dist.hasToken,
      })
    }
    i += 1
  }
}

export async function registerUser(profile: Profile): Promise<Ack> {
  // Same artificial-delay contract as the mock adapter so the UI shows a
  // brief pending state. No real I/O.
  await new Promise((resolve) => setTimeout(resolve, 200))
  // Newly registered users start with the "fresh ward" operational state:
  // 발송 안 함 / 읽지 않음 / 토큰 보유(가정) / 피보호자 전화번호는 폼에서
  // 받은 값을 그대로 저장.
  const rec: RegistrationRecord = {
    ...profile,
    phone: null,
    sendState: 'not_sent',
    lastSentAt: null,
    isRead: false,
    hasToken: true,
  }
  registrations.set(profile.userId, rec)
  if (isStoreEnabled()) {
    // Cross-device path: persist so the ward's phone can see this record on
    // /join and the operator tablet can subscribe to badge updates. The
    // in-memory copy is the local mirror, but the persisted document is the
    // source of truth the other device reads — if the write fails we MUST
    // throw so the caller shows a registration failure instead of a success
    // with a QR that leads to a missing document.
    await fsPut(rec)
  }
  return { ok: true }
}

// registerUser variant that also persists the ward's phone number.
// The plain `registerUser(profile)` above is preserved for backward
// compatibility with any other caller, but the /ops form uses this overload
// so the phone column is populated from the form rather than left null.
export async function registerUserWithPhone(
  profile: Profile,
  phone: string | null,
): Promise<Ack> {
  await new Promise((resolve) => setTimeout(resolve, 200))
  // On the mock path, hasToken stays true (the original behavior — a freshly
  // registered persona is assumed to have a device for demo purposes). On the
  // store path the ward's phone has NOT opened /join yet, so hasToken:false
  // is the honest initial state and the /ops badge starts "미등록" until the
  // phone attaches its token. This split keeps the no-env-default byte-for-byte
  // the original mock behavior.
  const storeOn = isStoreEnabled()
  const rec: RegistrationRecord = {
    ...profile,
    phone,
    sendState: 'not_sent',
    lastSentAt: null,
    isRead: false,
    hasToken: storeOn ? false : true,
  }
  registrations.set(profile.userId, rec)
  if (storeOn) {
    // Same persistence contract as registerUser: the in-memory copy is the
    // local mirror, the Firestore document is what the ward's phone reads on
    // /join. A failed write must surface as a registration failure, not a
    // success with a QR that points at a missing record.
    await fsPut(rec)
  }
  return { ok: true }
}

export async function listRegistrations(): Promise<RegistrationRecord[]> {
  if (isStoreEnabled()) {
    // Store path. fsList now applies the 10s deadline and throws on failure
    // (broken/offline store), so we let the error propagate — a real failure
    // must not masquerade as "0 rows" in the operator table. The mirror into
    // the local Map only runs on a successful read.
    const rows = await fsList()
    // Mirror into the local Map so the existing sendTestNotification
    // lookup-by-Map still works on the store path (it needs the token).
    for (const r of rows) {
      registrations.set(r.userId, r)
    }
    return rows
  }
  await new Promise((resolve) => setTimeout(resolve, 200))
  return Array.from(registrations.values())
}

// Sends a test notification to a registered user. Two paths:
//
// 1. VITE_PUSH_BRIDGE_URL unset (the default) → the original mock path.
//    Returns a fake `mock-...` id, never touches the network. This MUST stay
//    byte-for-byte the original behavior so the app runs identically with no
//    bridge present.
// 2. VITE_PUSH_BRIDGE_URL set → POST `{userId, title?, body?, url?}` to that
//    loopback bridge (a local helper script), which holds the FCM
//    service-account key and does the actual web push. On success the record
//    is mutated exactly like the mock path (sendState='sent', lastSentAt) and
//    the real `messageId` from the bridge is returned. On failure this throws
//    — the caller already surfaces a failure toast, so silent success is
//    forbidden.
//
// `hasToken === false` rejection is enforced on BOTH paths before any
// network attempt, so the 'no_token' state can never flip to 'sent'.
//
// The bridge fetch uses a 10s AbortController timeout so a dead bridge does
// not freeze the /ops UI — it surfaces as a thrown error instead.
//
// SEND vs PERSIST SEPARATION (double-send avoidance): a successful push is
// reported as success even when the subsequent send-state write to the store
// fails. If we let that state-write failure throw, the caller would treat a
// sent message as "failed" and retry — sending the SAME alert to the ward a
// second time. So the success return carries an optional `persistWarning`
// string; when set, the bridge send succeeded (the user MUST NOT retry) but
// the local record of that send could not be saved (the operator is told so
// they understand a refresh may not show the sent state). Only a failure of
// the push ITSELF (bridge down, non-OK, non-JSON, missing messageId) throws.
export async function sendTestNotification(userId: string): Promise<{
  ok: boolean
  messageId: string
  persistWarning?: string
}> {
  // On the store path, refresh from Firestore first so the operator tab
  // sees the freshest hasToken/deviceToken state (the ward's phone may have
  // attached its token seconds ago on a different device). On the no-store
  // path this is a pure local Map lookup — original behavior preserved.
  let rec = registrations.get(userId)
  if (rec === undefined && isStoreEnabled()) {
    const fresh = await fsGet(userId)
    if (fresh !== null) {
      registrations.set(userId, fresh)
      rec = fresh
    }
  }
  if (rec === undefined) {
    throw new Error(`unknown userId: ${userId}`)
  }
  if (isStoreEnabled()) {
    // Pull latest once more in case the in-memory copy is stale relative to
    // the cross-device write. Cheap relative to a network send.
    const fresh = await fsGet(userId)
    if (fresh !== null) {
      registrations.set(userId, fresh)
      rec = fresh
    }
  }
  if (!rec.hasToken) {
    // Reject — do not flip state. Caller surfaces a failure toast.
    throw new Error(`no device token for userId: ${userId}`)
  }

  const bridgeUrl = import.meta.env.VITE_PUSH_BRIDGE_URL
  if (bridgeUrl === undefined || bridgeUrl === null || bridgeUrl === '') {
    // ---- Default path: original mock, unchanged -------------------------
    // The simulated send updates the in-memory record. When the store is
    // enabled, the caller (handleTestSend) immediately refresh()s from the
    // store, which would overwrite this in-memory write and leave the row
    // showing "발송 안 함" with an empty timestamp — contradicting the
    // success toast. Persisting the simulated state to the same store the
    // refresh reads from keeps the toast and the table consistent.
    //
    // This does NOT make a fake send look real: the messageId still carries
    // the `mock-` prefix and the operator toast still says "시뮬레이션".
    // Only the consistency of the table is fixed. The persistWarning path
    // from the bridge branch is mirrored here so a store write failure is
    // surfaced the same way (success + warning, never a retry-inducing
    // failure).
    await new Promise((resolve) => setTimeout(resolve, 200))
    const stamp = nowHMS()
    registrations.set(userId, { ...rec, sendState: 'sent', lastSentAt: stamp })
    let mockPersistWarning: string | undefined
    if (isStoreEnabled()) {
      try {
        await fsRecordSend(userId, 'sent', stamp)
      } catch (persistErr) {
        mockPersistWarning =
          '발송은 성공했지만 발송 기록 저장에 실패했습니다. 목록에 바로 반영되지 않을 수 있습니다. ' +
          `재발송하지 마세요. (${
            persistErr instanceof Error ? persistErr.message : String(persistErr)
          })`
      }
    }
    return {
      ok: true,
      // Deterministic-looking but obviously fake id, so it is clear in the
      // UI/log that no real FCM round-trip happened.
      messageId: `mock-${userId}-${Date.now()}`,
      ...(mockPersistWarning !== undefined
        ? { persistWarning: mockPersistWarning }
        : {}),
    }
  }

  // ---- Bridge path: real FCM via the local loopback HTTP sender ---------
  // 저장소가 켜져 있을 때, 피보호자의 deviceToken 은 Firestore 에 있고
  // 위에서 `rec.deviceToken` 으로 로드된다. 브리지 본문에 실어 보내
  // 루프백 sender 가 자체 토큰 저장소를 가질 필요가 없게 한다.
  // 저장소가 꺼져 있을 때(VITE_FS_* 없음)는 원래 브리지 본문 `{userId}`
  // 가 바이트 단위로 보존된다 — 이 모드에서는 브리지가 자기 쪽에서
  // 토큰을 해결한다.
  //
  // 발송 결과(sendState)는 성공·실패 모두 Firestore 문서에 저장된다 —
  // 그래야 페이지를 새로고침해도 'sent'/'failed' 상태가 유지되고, 새로고침
  // 직후 'not_sent'로 돌아가는 회귀가 생기지 않는다. 메모리 mock 경로는
  // 저장소가 켜져 있지 않으므로 그대로 인메모리만 갱신한다.
  //
  // DEEP-LINK + TITLE + BODY: 브리지의 기본 딥링크(/a?t=p001&s=2)는 데모
  // 페르소나 김순자를 가리키고, 기본 제목·본문에는 등록하지 않은 동
  // 이름(서원동)과 주거 형태(반지하)가 박혀 있다. 그 기본값을 그대로 쓰면
  // 누구를 등록하든 항상 같은 사람의 화면으로 열리고 문장도 틀린다. 그래서
  // 이 발송이 가리키는 사람의 딥링크·제목·본문을 본문에 함께 실어 보낸다.
  // 문구에는 저장된 값(이름·행정동)만 쓴다 — 저장하지 않는 주거 형태·건강·
  // 장애는 넣지 않는다.
  const storeOn = isStoreEnabled()
  const tokenToSend: string | null =
    storeOn && rec.deviceToken !== undefined ? rec.deviceToken : null
  // 알림 본문. 푸시에서 읽은 문장과 탭해서 들어간 화면의 문장이 같아야 한다 —
  // 화면(EasyText)은 한국어일 때 행정 용어를 쉬운 우리말로 치환해 보여주므로,
  // 알림 본문도 같은 치환을 거친다. 베트남어 화면은 치환 사전이 없어 원문
  // 그대로이므로 알림도 원문을 쓴다. 알림 제목은 건드리지 않는다.
  const rawBody = `${rec.dongName}에 호우경보가 발령됐습니다. ${rec.name}님, 안내를 확인해 주세요.`
  const bodyText =
    rec.language === 'vi'
      ? rawBody
      : substituteAdminTerms(rawBody).plain
  const bridgeBody: Record<string, unknown> = {
    userId,
    // `/a?t=<userId>&s=2` — 등록한 그 사람을 가리키는 딥링크. 폰이 알림을
    // 탭하면 이 사람 화면으로 열린다.
    url: `/a?t=${encodeURIComponent(userId)}&s=2`,
    title: `[세이버스] ${rec.dongName} 호우경보`,
    body: bodyText,
  }
  if (storeOn) {
    if (tokenToSend === null) {
      throw new Error(`no device token for userId: ${userId}`)
    }
    bridgeBody.token = tokenToSend
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), 10000)
  let res: Response
  try {
    res = await fetch(bridgeUrl as string, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bridgeBody),
      signal: controller.signal,
    })
  } catch (e) {
    // Network error, connection refused (bridge down), or 10s abort. Persist
    // the outcome to the store (when enabled) so a refresh does not erase it,
    // then surface as a thrown error — never fall through to mock-success.
    //
    // TIMEOUT is NOT 'failed'. The browser closed the request, not the
    // server; the bridge may have already dispatched the push and the only
    // thing missing is the HTTP response. Recording 'unconfirmed' instead of
    // 'failed' keeps the operator from treating a possibly-sent push as a
    // failure and re-dispatching the SAME alert twice. The surfaced error
    // text and the record state both reflect this distinction.
    const isAbort = controller.signal.aborted
    const failStamp = nowHMS()
    registrations.set(userId, {
      ...rec,
      sendState: isAbort ? 'unconfirmed' : 'failed',
      lastSentAt: failStamp,
    })
    if (storeOn) {
      await fsRecordSend(
        userId,
        isAbort ? 'unconfirmed' : 'failed',
        failStamp,
      )
    }
    if (isAbort) {
      throw new Error(
        `발송 요청이 10초 안에 끝나지 않아 결과를 확인하지 못했습니다. 실제로는 발송되었을 수 있습니다. 새로고침하여 발송 상태를 다시 확인해 주세요. 재발송 금지. (${
          bridgeUrl as string
        })`,
      )
    }
    throw new Error(
      `push bridge request failed (${bridgeUrl as string}): ${
        e instanceof Error ? e.message : String(e)
      }`,
    )
  } finally {
    clearTimeout(timer)
  }

  let payload: { ok?: boolean; messageId?: string; error?: string }
  try {
    payload = (await res.json()) as {
      ok?: boolean
      messageId?: string
      error?: string
    }
  } catch (e) {
    const failStamp = nowHMS()
    registrations.set(userId, {
      ...rec,
      sendState: 'failed',
      lastSentAt: failStamp,
    })
    if (storeOn) {
      await fsRecordSend(userId, 'failed', failStamp)
    }
    throw new Error(
      `push bridge returned non-JSON (HTTP ${res.status}): ${
        e instanceof Error ? e.message : String(e)
      }`,
    )
  }

  if (!res.ok || !payload.ok || typeof payload.messageId !== 'string') {
    // Bridge reported failure (4xx/5xx with {ok:false} or missing messageId).
    // Persist the failed state, then throw — the caller already shows a
    // failure toast; mock-success here would silently hide a broken send.
    const failStamp = nowHMS()
    registrations.set(userId, {
      ...rec,
      sendState: 'failed',
      lastSentAt: failStamp,
    })
    if (storeOn) {
      await fsRecordSend(userId, 'failed', failStamp)
    }
    throw new Error(
      `push bridge send failed (HTTP ${res.status}): ${
        typeof payload.error === 'string' ? payload.error : 'no messageId'
      }`,
    )
  }

  // Success — mutate the record the same way the mock path does, persist the
  // 'sent' state so a refresh does not regress to 'not_sent', then return
  // the real messageId from the bridge.
  //
  // The push already succeeded. If the state write fails we MUST NOT throw —
  // throwing would make the caller show "발송 실패" and the operator would
  // retry, sending the SAME disaster alert to the ward TWICE. Instead we
  // return success with a persistWarning so the operator sees "보냈습니다,
  // 다만 기록 저장에 실패해 목록에 안 보일 수 있습니다" and does not retry.
  const stamp = nowHMS()
  registrations.set(userId, { ...rec, sendState: 'sent', lastSentAt: stamp })
  let persistWarning: string | undefined
  if (storeOn) {
    try {
      await fsRecordSend(userId, 'sent', stamp)
    } catch (persistErr) {
      persistWarning =
        '발송은 성공했지만 발송 기록 저장에 실패했습니다. 목록에 바로 반영되지 않을 수 있습니다. ' +
        `재발송하지 마세요. (${persistErr instanceof Error ? persistErr.message : String(persistErr)})`
    }
  }
  return {
    ok: true,
    messageId: payload.messageId,
    ...(persistWarning !== undefined ? { persistWarning } : {}),
  }
}

// Delete a registration record. Used by the /ops screen to remove a wrongly
// registered ward (wrong name, duplicate, etc). This is irreversible — the
// caller MUST confirm with the user before invoking.
//
// Two paths mirror sendTestNotification:
//   - Store enabled → delete the Firestore document (fsDelete applies the
//     10s deadline and throws on failure). The in-memory mirror is removed
//     AFTER the document delete succeeds so a failed delete does not leave
//     the local Map out of sync with the persisted truth.
//   - Store disabled → remove from the in-memory Map only (original
//     behavior preserved: no persistence in the public demo repo).
//
// On either path a failure throws — the caller surfaces the error to the
// operator. Silent failure is forbidden (a "deleted" row that still exists
// would mislead the operator into thinking the ward is gone).
export async function deleteRegistration(userId: string): Promise<void> {
  const storeOn = isStoreEnabled()
  if (storeOn) {
    // Persisted delete first — if it fails we throw and the local Map is
    // untouched, so the row stays on screen and the operator sees the error.
    await fsDelete(userId)
  } else {
    // Mock path mirrors the artificial delay of the other mock helpers so
    // the UI shows a brief pending state.
    await new Promise((resolve) => setTimeout(resolve, 200))
  }
  registrations.delete(userId)
}
