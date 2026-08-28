// Real HTTP adapter. Function signatures match the ApiClient interface so
// swapping mock -> http is a one-line change in client.ts.
//
// Every method below is a real fetch() call against the contract paths in
// packages/contracts/openapi.yaml (v0.10). The base URL comes from env only —
// never hardcoded (public repo). No retry, no client-side timeout, no auth
// header, and no `credentials` option are added — none of those are in the
// contract, and inventing them here would be exactly the kind of assumption
// this file must not make.

import type {
  Ack,
  ApiClient,
  ChatRequest,
  ChatResponse,
  DeviceRegisterRequest,
  ErrorCode,
  GuardianAnswer,
  GuardianAskRequest,
  GuardianDeviceRegisterRequest,
  GuardianStatus,
  RecordedUserActionEvent,
  RegistrationTarget,
  SessionResponse,
  ShelterList,
  ShelterSearchRequest,
  UserActionEventCreate,
} from './types'

// Contract paths (see packages/contracts/openapi.yaml v0.10).
//   GET    /v1/session/{token}
//   POST   /v1/session/{token}/response
//   POST   /v1/session/{token}/events
//   GET    /v1/registration/{registrationToken}
//   POST   /v1/shelters/search
//   POST   /v1/chat
//   POST   /v1/devices
//   DELETE /v1/devices
//   GET    /v1/guardian/{token}
//   POST   /v1/guardian/{token}/acknowledge
//   POST   /v1/guardian/{token}/device
//   DELETE /v1/guardian/{token}/device
//   POST   /v1/guardian/{token}/ask
const PATH_SESSION = '/v1/session/'
const PATH_SESSION_RESPONSE_SUFFIX = '/response'
const PATH_SESSION_EVENTS_SUFFIX = '/events'
const PATH_REGISTRATION = '/v1/registration/'
const PATH_CHAT = '/v1/chat'
const PATH_DEVICES = '/v1/devices'
const PATH_GUARDIAN = '/v1/guardian/'
const PATH_GUARDIAN_ACK_SUFFIX = '/acknowledge'
const PATH_GUARDIAN_DEVICE_SUFFIX = '/device'
const PATH_GUARDIAN_ASK_SUFFIX = '/ask'

// v0.3 changed GET /v1/shelters → POST /v1/shelters/search (body carries
// coordinates + sessionToken; health/disability fields never leave the
// client). Exported so client.ts can surface the canonical contract path
// without re-deriving it — the single source of truth lives here, next to
// the adapter that consumes it.
export const PATH_SHELTERS_SEARCH = '/v1/shelters/search'

// Reads from env only — never hardcoded. Empty until the backend ships (a
// relative path then resolves against the frontend's own origin).
const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '')

// ---- shared request/error plumbing -------------------------------------

// Thrown for any non-2xx response. Carries the contract's Error.code when
// the server returned a parseable Error body (packages/contracts/openapi.yaml
// `Error` schema); `code` is left undefined when the server could not be
// read as that shape (non-JSON body, network proxy error page, etc.) so
// callers never see a fabricated code.
export class ApiRequestError extends Error {
  readonly status: number
  readonly code?: ErrorCode

  constructor(message: string, status: number, code?: ErrorCode) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.code = code
  }
}

const ERROR_CODES: Record<ErrorCode, true> = {
  SESSION_NOT_FOUND: true,
  SESSION_EXPIRED: true,
  INVALID_REQUEST: true,
  IDEMPOTENCY_KEY_CONFLICT: true,
  RATE_LIMITED: true,
  INTERNAL: true,
  UPSTREAM_UNAVAILABLE: true,
}

function isErrorCode(value: string): value is ErrorCode {
  return Object.hasOwn(ERROR_CODES, value)
}

interface ParsedErrorBody {
  message: string
  code?: ErrorCode
}

const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._~-]{16,128}$/

interface RequestOptions {
  method: 'GET' | 'POST' | 'DELETE'
  path: string
  // Omit entirely for a body-less request (e.g. GET, or a POST whose
  // requestBody is optional and being skipped) — no Content-Type or body is
  // sent in that case.
  body?: unknown
  headers?: Record<string, string>
}

// Attempts to read the response as the contract's `Error` shape. Returns
// null on any failure (non-JSON body, empty body, shape mismatch) so the
// caller can fall back to a generic message instead of throwing a second,
// unrelated error out of the error path itself.
async function tryReadErrorBody(res: Response): Promise<ParsedErrorBody | null> {
  try {
    const text = await res.text()
    if (text.length === 0) return null
    const parsed: unknown = JSON.parse(text)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'message' in parsed &&
      typeof parsed.message === 'string'
    ) {
      const code =
        'code' in parsed &&
        typeof parsed.code === 'string' &&
        isErrorCode(parsed.code)
          ? parsed.code
          : undefined
      return { message: parsed.message, code }
    }
    return null
  } catch {
    return null
  }
}

// Single fetch entrypoint for every ApiClient method below. Handles base
// URL prefixing, JSON request encoding (only when a body is given),
// contract-Error-aware failure reporting, and JSON response decoding
// (only when the response actually has a body — no forced parse of an
// empty success response).
async function request<T>(opts: RequestOptions): Promise<T> {
  const headers: Record<string, string> = { ...opts.headers }
  let bodyInit: string | undefined
  if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    bodyInit = JSON.stringify(opts.body)
  }

  const res = await fetch(`${BASE_URL}${opts.path}`, {
    method: opts.method,
    headers,
    body: bodyInit,
  })

  if (!res.ok) {
    const errorBody = await tryReadErrorBody(res)
    const message = errorBody?.message ?? `${opts.method} ${opts.path} failed with HTTP ${res.status}`
    throw new ApiRequestError(message, res.status, errorBody?.code)
  }

  const text = await res.text()
  if (text.length === 0) {
    // No response body — every current contract success response does
    // define a JSON body, but this guards against a body-less 200 rather
    // than forcing JSON.parse('') to throw.
    return undefined as T
  }
  return JSON.parse(text) as T
}

export const httpAdapter: ApiClient = {
  async getSession(token: string): Promise<SessionResponse> {
    return request<SessionResponse>({
      method: 'GET',
      path: `${PATH_SESSION}${encodeURIComponent(token)}`,
    })
  },

  async postSessionResponse(
    token: string,
    response: 'home' | 'outside',
  ): Promise<Ack> {
    return request<Ack>({
      method: 'POST',
      path: `${PATH_SESSION}${encodeURIComponent(token)}${PATH_SESSION_RESPONSE_SUFFIX}`,
      body: { response },
    })
  },

  async postSessionEvent(
    token: string,
    event: UserActionEventCreate,
    idempotencyKey: string,
  ): Promise<RecordedUserActionEvent> {
    // Idempotency-Key is a required header on this endpoint
    // (openapi.yaml POST /v1/session/{token}/events, parameters). The caller
    // supplies it — this adapter never invents or randomizes one, since only
    // the caller knows whether this is a fresh user action or a retry.
    if (
      typeof idempotencyKey !== 'string' ||
      !IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)
    ) {
      throw new Error(
        'Idempotency-Key must be 16 to 128 characters using only A-Z, a-z, 0-9, ., _, ~, or -',
      )
    }
    return request<RecordedUserActionEvent>({
      method: 'POST',
      path: `${PATH_SESSION}${encodeURIComponent(token)}${PATH_SESSION_EVENTS_SUFFIX}`,
      body: event,
      headers: { 'Idempotency-Key': idempotencyKey },
    })
  },

  async getRegistrationTarget(
    registrationToken: string,
  ): Promise<RegistrationTarget> {
    return request<RegistrationTarget>({
      method: 'GET',
      path: `${PATH_REGISTRATION}${encodeURIComponent(registrationToken)}`,
    })
  },

  async searchShelters(req: ShelterSearchRequest): Promise<ShelterList> {
    return request<ShelterList>({
      method: 'POST',
      path: PATH_SHELTERS_SEARCH,
      body: req,
    })
  },

  async postChat(req: ChatRequest): Promise<ChatResponse> {
    return request<ChatResponse>({
      method: 'POST',
      path: PATH_CHAT,
      body: req,
    })
  },

  async registerDevice(req: DeviceRegisterRequest): Promise<Ack> {
    return request<Ack>({
      method: 'POST',
      path: PATH_DEVICES,
      body: req,
    })
  },

  async unregisterDevice(
    registrationToken: string,
    fcmToken: string,
  ): Promise<Ack> {
    // DELETE /v1/devices requestBody = DeviceUnregisterRequest
    // { registrationToken, fcmToken, userAgent? } — no `role` (openapi.yaml
    // DeviceUnregisterRequest). userAgent is optional and this ApiClient
    // signature does not carry one, so it is simply omitted.
    return request<Ack>({
      method: 'DELETE',
      path: PATH_DEVICES,
      body: { registrationToken, fcmToken },
    })
  },

  async getGuardianStatus(token: string): Promise<GuardianStatus> {
    return request<GuardianStatus>({
      method: 'GET',
      path: `${PATH_GUARDIAN}${encodeURIComponent(token)}`,
    })
  },

  async postGuardianAcknowledge(token: string): Promise<Ack> {
    // requestBody is `required: false` with an empty-object schema
    // (openapi.yaml POST /v1/guardian/{token}/acknowledge) — sent with no
    // body at all, which the spec's "빈 객체 또는 생략 가능" explicitly allows.
    return request<Ack>({
      method: 'POST',
      path: `${PATH_GUARDIAN}${encodeURIComponent(token)}${PATH_GUARDIAN_ACK_SUFFIX}`,
    })
  },

  async registerGuardianDevice(
    token: string,
    req: GuardianDeviceRegisterRequest,
  ): Promise<Ack> {
    return request<Ack>({
      method: 'POST',
      path: `${PATH_GUARDIAN}${encodeURIComponent(token)}${PATH_GUARDIAN_DEVICE_SUFFIX}`,
      body: req,
    })
  },

  async unregisterGuardianDevice(
    token: string,
    req: GuardianDeviceRegisterRequest,
  ): Promise<Ack> {
    // DELETE /v1/guardian/{token}/device uses the SAME body schema as the
    // POST (GuardianDeviceRegisterRequest — no `role`/`registrationToken` on
    // either side; the path's guardian token answers both), per
    // openapi.yaml.
    return request<Ack>({
      method: 'DELETE',
      path: `${PATH_GUARDIAN}${encodeURIComponent(token)}${PATH_GUARDIAN_DEVICE_SUFFIX}`,
      body: req,
    })
  },

  async postGuardianAsk(
    token: string,
    req: GuardianAskRequest,
  ): Promise<GuardianAnswer> {
    // 200 covers BOTH the delivered and refused (`no_evidence`) branches of
    // the GuardianAnswer oneOf — a refusal is a normal response body, not an
    // HTTP error, so it flows straight back to the caller unmodified. Only a
    // real HTTP failure (404/410/422/...) goes through the error path above.
    return request<GuardianAnswer>({
      method: 'POST',
      path: `${PATH_GUARDIAN}${encodeURIComponent(token)}${PATH_GUARDIAN_ASK_SUFFIX}`,
      body: req,
    })
  },
}
