export const GUARDIAN_FCM_TOKEN_STORAGE_KEY = 'savers.guardianPush.fcmToken'

export function readGuardianFcmToken(): string | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage.getItem(GUARDIAN_FCM_TOKEN_STORAGE_KEY)
  } catch {
    return null
  }
}

export function writeGuardianFcmToken(token: string): void {
  try {
    window.localStorage.setItem(GUARDIAN_FCM_TOKEN_STORAGE_KEY, token)
  } catch {
    // Backend registration already succeeded; local persistence is best-effort.
  }
}

export function removeGuardianFcmToken(): void {
  try {
    window.localStorage.removeItem(GUARDIAN_FCM_TOKEN_STORAGE_KEY)
  } catch {
    // The backend deletion succeeded. There is nothing else safe to delete.
  }
}

export function migrateLegacyGuardianFcmToken(guardianToken: string): string | null {
  const legacyTokenKey = `savers.guardianPush.fcmToken.${guardianToken}`
  const legacyFlagKey = `savers.guardianPush.subscribed.${guardianToken}`
  try {
    const current = window.localStorage.getItem(GUARDIAN_FCM_TOKEN_STORAGE_KEY)
    const legacy = window.localStorage.getItem(legacyTokenKey)
    if (current === null && legacy !== null) {
      window.localStorage.setItem(GUARDIAN_FCM_TOKEN_STORAGE_KEY, legacy)
    }
    window.localStorage.removeItem(legacyTokenKey)
    window.localStorage.removeItem(legacyFlagKey)
    return current ?? legacy
  } catch {
    return readGuardianFcmToken()
  }
}
