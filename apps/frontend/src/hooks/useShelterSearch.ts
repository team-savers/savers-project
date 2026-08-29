import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Profile, ShelterList } from '../api/types'

interface ShelterState {
  loading: boolean
  error: string | null
  result: ShelterList | null
}

// dongCode is always the matching key (search() below is called with no
// coords on mount and never omits dongCode) — coords only ever REFINE
// distance/bearing on top of it, mirroring components/ShelterGuide.tsx's
// "auto" branch (see its module header, branch B). This production flow has
// no explicit location-consent UI (no "밖이에요" / "현재 위치 사용" action —
// that ADR-0005/ADR-0007/OpenAPI-described landing flow is a separate,
// undecided product question — see PR notes). What runs here is strictly
// passive: it fires getCurrentPosition at most once, and only when BOTH the
// registration-time consent flag is already true AND the browser permission
// is already 'granted' — i.e. only when nothing new is being asked of the
// user. Every other permission/consent combination (prompt, denied, no
// flag) is left at dongCode-only, same as ShelterGuide's "card"/"refused"
// branches, since there is no consent-card UI here to resolve them. The
// resolved coordinate lives only in this hook's closure/React state; it is
// never written to session storage, local storage, or any request other
// than this one POST /v1/shelters/search call.
export function useShelterSearch(token: string, profile: Profile): ShelterState {
  const [state, setState] = useState<ShelterState>({ loading: false, error: null, result: null })
  const generation = useRef(0)
  const mounted = useRef(true)
  const geolocationStarted = useRef(false)

  const search = useCallback((coords?: { lat: number; lng: number }) => {
    if (profile.dongCode.trim() === '') return
    const requestGeneration = ++generation.current
    setState((current) => ({ ...current, loading: true, error: null }))
    void api.searchShelters({
      sessionToken: token,
      dongCode: profile.dongCode,
      ...(coords ?? {}),
    }).then((result) => {
      if (mounted.current && generation.current === requestGeneration) {
        setState({ loading: false, error: null, result })
      }
    }).catch((cause) => {
      if (mounted.current && generation.current === requestGeneration) {
        setState((current) => ({
          ...current,
          loading: false,
          error: cause instanceof Error ? cause.message : String(cause),
        }))
      }
    })
  }, [profile.dongCode, token])

  useEffect(() => {
    mounted.current = true
    if (profile.dongCode.trim() === '') return () => { mounted.current = false }
    search()

    if (profile.consents?.location !== true || navigator.permissions == null) {
      return () => { mounted.current = false }
    }
    void navigator.permissions.query({ name: 'geolocation' as PermissionName }).then((permission) => {
      if (!mounted.current || permission.state !== 'granted' || geolocationStarted.current) return
      geolocationStarted.current = true
      navigator.geolocation?.getCurrentPosition(
        (position) => search({ lat: position.coords.latitude, lng: position.coords.longitude }),
        () => undefined,
        { enableHighAccuracy: false, timeout: 8000, maximumAge: 0 },
      )
    }).catch(() => undefined)

    return () => { mounted.current = false }
  }, [profile.consents?.location, profile.dongCode, search])

  return state
}
