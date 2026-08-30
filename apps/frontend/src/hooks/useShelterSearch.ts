import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Profile, ShelterList } from '../api/types'

interface ShelterState {
  loading: boolean
  error: string | null
  result: ShelterList | null
}

// Production EvacuationFlow has no explicit location-consent UI yet — the
// `[집이에요]/[밖이에요]` landing flow described in ADR-0005/ADR-0007/OpenAPI
// is a separate, undecided product question. Until that UI exists, this
// hook does exactly one thing: search by the registered 행정동 (dongCode).
// It must never call navigator.geolocation itself — scripts/check_privacy.py
// (P1-consent-path) only allows getCurrentPosition inside the two files that
// own an actual consent branch (components/LocationConsent.tsx,
// components/ShelterGuide.tsx); a call from here fails CI by design.
export function useShelterSearch(token: string, profile: Profile): ShelterState {
  const [state, setState] = useState<ShelterState>({ loading: false, error: null, result: null })
  const generation = useRef(0)
  const mounted = useRef(true)

  const search = useCallback(() => {
    if (profile.dongCode.trim() === '') return
    const requestGeneration = ++generation.current
    setState((current) => ({ ...current, loading: true, error: null }))
    void api.searchShelters({
      sessionToken: token,
      dongCode: profile.dongCode,
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
    search()
    return () => { mounted.current = false }
  }, [search])

  return state
}
