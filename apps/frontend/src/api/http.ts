// Real HTTP adapter. Function signatures match the ApiClient interface so
// swapping mock -> http is a one-line change in client.ts.
//
// Bodies are stubs by design: the backend endpoints do not exist yet.
// Replace each throw with a fetch() call once the backend serves the
// endpoints. The base URL must come from env — never hardcode (public repo).
//
// The contract path strings are kept as named constants below so wiring
// them later is a lookup, not a re-derivation. They mirror
// packages/contracts/openapi.yaml paths exactly (v0.3).

import type {
  Ack,
  ApiClient,
  ChatRequest,
  ChatResponse,
  DeviceRegisterRequest,
  GuardianStatus,
  RegistrationTarget,
  SessionResponse,
  ShelterList,
  ShelterSearchRequest,
} from './types'

// Contract paths (see packages/contracts/openapi.yaml v0.3).
//   GET    /v1/session/{token}
//   POST   /v1/session/{token}/response
//   GET    /v1/registration/{registrationToken}
//   POST   /v1/shelters/search
//   POST   /v1/chat
//   POST   /v1/devices
//   DELETE /v1/devices
//   GET    /v1/guardian/{token}
//   POST   /v1/guardian/{token}/acknowledge
const PATH_SESSION = '/v1/session/'
const PATH_SESSION_RESPONSE_SUFFIX = '/response'
const PATH_REGISTRATION = '/v1/registration/'
const PATH_CHAT = '/v1/chat'
const PATH_DEVICES = '/v1/devices'
const PATH_GUARDIAN = '/v1/guardian/'
const PATH_GUARDIAN_ACK_SUFFIX = '/acknowledge'

// v0.3 changed GET /v1/shelters → POST /v1/shelters/search (body carries
// coordinates + sessionToken; health/disability fields never leave the
// client). Exported so client.ts can surface the canonical contract path
// without re-deriving it — the single source of truth lives here, next to
// the adapter that will eventually consume it.
export const PATH_SHELTERS_SEARCH = '/v1/shelters/search'

// Reads from env only — never hardcoded. Empty until the backend ships.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
void BASE_URL // reserved for the real fetch implementation
void PATH_SESSION
void PATH_SESSION_RESPONSE_SUFFIX
void PATH_REGISTRATION
void PATH_SHELTERS_SEARCH
void PATH_CHAT
void PATH_DEVICES
void PATH_GUARDIAN
void PATH_GUARDIAN_ACK_SUFFIX

export const httpAdapter: ApiClient = {
  async getSession(_token: string): Promise<SessionResponse> {
    // GET `${BASE_URL}${PATH_SESSION}${encodeURIComponent(_token)}`
    throw new Error('not wired yet')
  },
  async postSessionResponse(
    _token: string,
    _response: 'home' | 'outside',
  ): Promise<Ack> {
    // POST `${BASE_URL}${PATH_SESSION}${encodeURIComponent(_token)}${PATH_SESSION_RESPONSE_SUFFIX}`
    throw new Error('not wired yet')
  },
  async getRegistrationTarget(
    _registrationToken: string,
  ): Promise<RegistrationTarget> {
    // GET `${BASE_URL}${PATH_REGISTRATION}${encodeURIComponent(_registrationToken)}`
    throw new Error('not wired yet')
  },
  async searchShelters(_req: ShelterSearchRequest): Promise<ShelterList> {
    // POST `${BASE_URL}${PATH_SHELTERS_SEARCH}` (body = ShelterSearchRequest)
    throw new Error('not wired yet')
  },
  async postChat(_req: ChatRequest): Promise<ChatResponse> {
    // POST `${BASE_URL}${PATH_CHAT}`
    throw new Error('not wired yet')
  },
  async registerDevice(_req: DeviceRegisterRequest): Promise<Ack> {
    // POST `${BASE_URL}${PATH_DEVICES}`
    throw new Error('not wired yet')
  },
  async unregisterDevice(
    _registrationToken: string,
    _fcmToken: string,
  ): Promise<Ack> {
    // DELETE `${BASE_URL}${PATH_DEVICES}` (body = DeviceRegisterRequest)
    throw new Error('not wired yet')
  },
  async getGuardianStatus(_token: string): Promise<GuardianStatus> {
    // GET `${BASE_URL}${PATH_GUARDIAN}${encodeURIComponent(_token)}`
    throw new Error('not wired yet')
  },
  async postGuardianAcknowledge(_token: string): Promise<Ack> {
    // POST `${BASE_URL}${PATH_GUARDIAN}${encodeURIComponent(_token)}${PATH_GUARDIAN_ACK_SUFFIX}`
    throw new Error('not wired yet')
  },
}
