// Shelter guide. Location handling resolves TWO independent signals — the
// browser permission state and the registration-time consent flag — and
// combines them per their own meaning:
//
//   A. Explicit refusal: consent flag === false, OR browser permission
//      'denied'. Location is not used. No card is shown.
//   B. Explicit consent AND permission 'granted': call getCurrentPosition
//      exactly once automatically (the user already granted, so re-prompting
//      would be noise). success → coord search; any failure → dong search.
//   C. Every other combination: render LocationConsent. getCurrentPosition
//      is invoked only inside that component, only when the user taps the
//      button, and at most once. Until then we do NOT pre-run a coord
//      search. This covers the common contract responses: permission
//      'granted' with no consent flag, permission 'prompt' with consent
//      true, permission 'prompt' with no consent flag, etc.
//
// HARD RULES (one-time, session-scoped location):
//   - getCurrentPosition is invoked at most once per page load. `geoStarted`
//     enforces this across StrictMode double-fire and across the granted vs.
//     consent-prompt branches.
//   - The resolved coordinate lives only in React state. It is never written
//     to any client-side persistent store.
//   - The registered 행정동 (dongCode) is ALWAYS the matching key. A coord
//     only refines distance/bearing; without it we still return a list.
//
// Contract notes (POST /v1/shelters/search):
//   - sessionToken in the body → server looks up stairsOk / disaster context
//     internally. Health/disability fields are NEVER re-sent from the client.
//   - The server is the single authority on which shelters to exclude
//     (underground, closed, unreachable). The client renders `items` verbatim
//     and only reorders for stairsOk.
//   - availability carries the freshness/outage axis: cache_only and the
//     upstream-outage value are normal 200 responses — the response body is
//     served from cache or the upstream was unreachable. The client must
//     render the body whenever items is non-empty even under cache_only,
//     and disclose the cache/stale provenance honestly. When the server
//     could not build a list at all (items empty), the client shows fallback
//     guidance so the last guidance still reaches the user.
//   - `dataAsOf !== null` means cached/stale data — disclose it honestly.
//
// Display rules preserved:
//   - stairsOk: false on the profile → hasStairs:true shelters sink to the
//     bottom while remaining visible.
//   - basis === 'dongCode' → the registered-home wording; never imply
//     current location in this mode.
//   - The shelter list is collapsed by default. Each list item with lat/lng
//     is tap-to-expand: tapping it renders an INLINE map for THAT shelter
//     only, tapping again collapses it, and only one shelter is expanded at
//     a time (openId). The Kakao SDK is NOT loaded on page entry — it loads
//     lazily the first time any shelter is expanded (the SDK promise cache
//     in kakaoMap.ts dedupes subsequent expands). Shelters without coords
//     render no expand affordance (there is nothing to plot).
//   - Blind profiles never mount ShelterMap and never trigger the SDK load —
//     expanding a shelter for a blind profile shows the address + distance +
//     bearing as a detailed text block instead. The list's own distance/
//     bearing text stays rendered regardless of map outcome (the map is
//     supplementary information).
//
// LANGUAGE (i18n): the UI language is received as a prop (the parent
// read it from the profile once and threaded it down). Every visible label
// goes through the i18n dictionary or a language-aware helper so a
// Vietnamese screen never shows a Korean label mid-sentence. Proper nouns
// (shelter name, address) stay in their original script — that is data, not
// UI copy, and is not "mixing languages".
//
// NOT shown on screen: hazardMatch, messageMode, safetyStatus — their
// presentation is a separate decision and only the types carry them.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { api } from '../api/client'
import type {
  ExcludedReason,
  Language,
  Profile,
  Shelter,
  ShelterExclusion,
  ShelterList,
} from '../api/types'
import {
  bearingLabel,
  countUnit,
  excludedReasonLabel,
  formatDistance,
  KoreanSpan,
  t,
} from '../lib/i18n'
import { LocationConsent } from './LocationConsent'
import { ShelterMap } from './ShelterMap'
import { C, FONT_MONO, SHADOW_CARD } from '../lib/tokens'

// Single option passed to getCurrentPosition on the "granted" branch (the
// LocationConsent button branch carries its own copy with identical values).
const GEO_OPTIONS: PositionOptions = {
  enableHighAccuracy: false,
  maximumAge: 0,
  timeout: 8000,
}

// Resolved browser permission state from navigator.permissions.query.
// 'granted' / 'denied' map directly; 'unknown' covers prompt, unsupported
// API, thrown error, or non-browser environment.
type PermissionBranch = 'granted' | 'denied' | 'unknown'

// Derived location mode once both signals (permission + consent flag) are
// resolved. Computed by deriveLocationMode below.
//   'auto'   → explicit consent + permission granted → read once on mount.
//   'card'   → not refused and not auto → show the consent card; the user
//              taps to read once.
//   'refused → explicit refusal (consent false or permission denied) →
//              no location use, no card.
type LocationMode = 'auto' | 'card' | 'refused'

// ---- 표현 상수 --------------------------------------------------------
//
// 배너 톤. 의미가 다른 것을 같은 색으로 칠하면 사용자는 "정보"와 "경고"를
// 구분할 수 없다.
//   info  틸    — 다음 행동 안내. 지시다.
//   warn  노랑  — 신선도·가용성 문제. 정보는 유효하나 최신이 아니다.
//   alert 붉음  — 제외된 시설. 안전 관련 사실이다.
const BANNER: Record<'info' | 'warn' | 'alert', CSSProperties> = {
  info: {
    background: C.tealBg,
    borderLeft: `4px solid ${C.tealText}`,
    color: C.tealDeep,
  },
  warn: {
    background: C.warnBg,
    borderLeft: `4px solid ${C.warn}`,
    color: C.warnText,
  },
  alert: {
    background: C.alertBg,
    borderLeft: `4px solid ${C.alertBorder}`,
    color: C.alertText,
  },
}

function banner(tone: 'info' | 'warn' | 'alert'): CSSProperties {
  return {
    ...BANNER[tone],
    margin: '0 0 11px',
    padding: '14px 15px',
    borderRadius: '0 12px 12px 0',
    fontSize: '17px',
    lineHeight: 1.6,
    letterSpacing: '-.012em',
    textWrap: 'pretty',
  }
}

// 목록 아래 토글(지도 / 상세). 아우트라인 테두리는 흰 카드 위에서 3:1 이상
// 이어야 한다(WCAG 1.4.11) — 연틸 계열로는 못 맞춘다.
function toggleButton(open: boolean): CSSProperties {
  return {
    width: '100%',
    minHeight: '52px',
    marginTop: '12px',
    padding: '14px 15px',
    fontFamily: 'inherit',
    fontSize: '17px',
    fontWeight: 700,
    letterSpacing: '-.015em',
    background: open ? C.tealBg : C.white,
    color: C.tealText,
    border: `1.5px solid ${C.tealText}`,
    borderRadius: '11px',
    cursor: 'pointer',
    textAlign: 'left',
  }
}

interface Props {
  profile: Profile | null
  // UI language, threaded from the parent (which read it from
  // Profile.language once). Drives every label below.
  lang: Language
  // The session token from the URL — required by POST /v1/shelters/search
  // so the server can look up stairsOk / disaster context internally.
  sessionToken: string
  // Fallback dong code to use as the registered address for the home flow.
  // OPTIONAL: when undefined, no 행정동 matching key is known and
  // ShelterGuide MUST NOT call searchShelters — searching on a hardcoded
  // dong for an unknown user would be wrong-location-during-disaster
  // (harm). In that case the section renders an honest notice and skips
  // the list entirely.
  fallbackDongCode?: string
  // Display dong name for the registered-home wording. The shelter
  // response no longer carries dongName (it isn't in the contract), so the
  // caller passes the registered dong name from the profile.
  dongName: string
}

interface Result {
  response: ShelterList
}

export function ShelterGuide({
  profile,
  lang,
  sessionToken,
  fallbackDongCode,
  dongName,
}: Props) {
  const [loading, setLoading] = useState<boolean>(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Result | null>(null)

  // The resolved one-shot coord (if any). Lives only in React state — never
  // persisted. Passed to ShelterMap so the map can center on the user
  // instead of on the first shelter. Reset to null whenever the user
  // re-runs the dongCode fallback (the coord is no longer authoritative).
  const [userCoord, setUserCoord] = useState<{
    lat: number
    lng: number
  } | null>(null)

  // SAFETY: when `fallbackDongCode` is undefined we have no matching
  // key and MUST NOT call searchShelters. The effect below checks this
  // before issuing any request.
  const dongCode = fallbackDongCode

  // stairs resolution is a THREE-state decision, not a
  // boolean. Registration-built sessions (profile.fromRegistration === true)
  // ship `stairsOk: true` from the mock/contract as a NEUTRAL placeholder —
  // that value was never confirmed by a guardian during surrogate
  // registration. Treating it as confirmed would make the screen hand a
  // definitive "go upstairs" instruction to a resident whose stairs ability
  // is genuinely unknown, which is unsafe. So:
  //   - fromRegistration === true  → 'unknown' (do NOT advise climbing)
  //   - stairsOk === false          → 'blocked'
  //   - otherwise (real profile, stairsOk true) → 'ok'
  // `stairsState` drives the NextActionNotice copy; `stairsOkBoolean` is the
  // boolean projection the list-sorting and per-item warning still consume
  // (the sort keeps stairs shelters last under both 'blocked' and 'unknown' —
  // under 'unknown' we must not PROMOTE stairs shelters, so we treat the list
  // conservatively the same as 'blocked' for ordering).
  const fromRegistration = profile?.fromRegistration === true
  const stairsState: 'ok' | 'blocked' | 'unknown' = fromRegistration
    ? 'unknown'
    : profile?.stairsOk === false
      ? 'blocked'
      : 'ok'
  const stairsOkBoolean = stairsState !== 'ok'

  // Permission branch resolved once on mount. Until resolved this is null
  // and we render nothing location-related (the list is fetched regardless).
  const [branch, setBranch] = useState<PermissionBranch | null>(null)

  // getCurrentPosition may be invoked from two sites: the "auto" mode
  // (below) and the LocationConsent button. This flag guarantees at most
  // one invocation across both, even under React StrictMode double-fire.
  const geoStarted = useRef<boolean>(false)

  // Race guard for concurrent shelter searches. Mount kicks off a dongCode
  // search immediately, and — when geolocation resolves — a coord search
  // starts on top of it. Both write to `result`; without a generation
  // counter a slow dongCode response could overwrite a fresher coord
  // response. Each search increments `searchGen.current` and captures its
  // own number; the .then() callback only applies the result if it is
  // still the latest generation.
  const searchGen = useRef<number>(0)

  // Unmount guard. The race guard above stops a stale search from overwriting
  // a fresher one, but it does NOT stop a search response from calling
  // setState AFTER the component has unmounted (React would warn, and the
  // state write is wasted work). This ref flips to false in the mount
  // effect's cleanup; every search completion checks it before touching
  // state. The generation guard is kept — it serves a different purpose
  // (inter-request ordering) and both guards compose.
  const mountedRef = useRef<boolean>(true)

  // ---- search helpers --------------------------------------------------
  //
  // Wrapped in useCallback so they are referentially stable across renders
  // and can be listed in the mount-effect's deps without re-running the
  // effect each render (they only change identity when sessionToken/dongCode
  // change, which is exactly when we want to re-run).
  //
  // SAFETY: both helpers refuse to run when `dongCode` is undefined.
  // The matching key must be a real registered 행정동; calling the API
  // with a hardcoded dong would surface wrong-location shelters.
  //
  // RACE: each call stamps a generation number. The response handler
  // rejects any response whose generation is not the latest, so a stale
  // dongCode result cannot overwrite a fresher coord result (or vice versa).

  const searchByDong = useCallback((): void => {
    if (dongCode === undefined) return
    const gen = ++searchGen.current
    setLoading(true)
    setError(null)
    // dongCode basis → the previously-resolved user coord is no longer
    // authoritative for this list; reset it so ShelterMap doesn't center
    // on a stale coord.
    setUserCoord(null)
    api
      .searchShelters({ sessionToken, dongCode })
      .then((r) => {
        // Stale response — a newer search (coord or dongCode) superseded
        // this one. Drop the result; the newer search owns the screen.
        if (gen !== searchGen.current) return
        // Unmounted since the request started — the result has no home.
        if (!mountedRef.current) return
        setResult({ response: r })
      })
      .catch((err) => {
        if (gen !== searchGen.current) return
        if (!mountedRef.current) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (gen !== searchGen.current) return
        if (!mountedRef.current) return
        setLoading(false)
      })
  }, [sessionToken, dongCode])

  const searchByCoord = useCallback(
    (lat: number, lng: number): void => {
      if (dongCode === undefined) return
      const gen = ++searchGen.current
      setLoading(true)
      setError(null)
      setUserCoord({ lat, lng })
      api
        .searchShelters({ sessionToken, dongCode, lat, lng })
        .then((r) => {
          if (gen !== searchGen.current) return
          if (!mountedRef.current) return
          setResult({ response: r })
        })
        .catch((err) => {
          if (gen !== searchGen.current) return
          if (!mountedRef.current) return
          setError(err instanceof Error ? err.message : String(err))
        })
        .finally(() => {
          if (gen !== searchGen.current) return
          if (!mountedRef.current) return
          setLoading(false)
        })
    },
    [sessionToken, dongCode],
  )

  // Combine the browser permission branch with the registration-time consent
  // flag into a single location mode. Two independent signals, decided per
  // their own meaning:
  //   - consent false OR permission denied → 'refused' (no location use).
  //   - consent true AND permission granted → 'auto' (read once on mount).
  //   - everything else → 'card' (show LocationConsent; user taps to read).
  // This means every state that is NOT an explicit consent+granted pair and
  // NOT an explicit refusal shows the card — including "granted but no
  // consent flag" (the typical contract response) and "prompt with consent
  // true" (the user consented at registration but the browser has not been
  // asked yet). Returns null while the permission branch has not resolved
  // yet so the caller can avoid deciding location UI prematurely.
  function deriveLocationMode(
    resolvedBranch: PermissionBranch | null,
    consentFlag: boolean | undefined,
  ): LocationMode | null {
    if (resolvedBranch === null) return null
    if (consentFlag === false || resolvedBranch === 'denied') return 'refused'
    if (consentFlag === true && resolvedBranch === 'granted') return 'auto'
    return 'card'
  }

  // ---- mount: resolve permission branch, then act ---------------------

  useEffect(() => {
    let cancelled = false
    // Mark mounted for the unmount guard in the search callbacks. Flipped
    // back to false on cleanup so a response that resolves after unmount
    // does not call setState on an unmounted component.
    mountedRef.current = true

    // SAFETY: the dongCode-only search runs ONLY when we actually
    // have a registered 행정동. When `dongCode` is undefined we skip the
    // search entirely (no hardcoded fallback) and the section renders the
    // "no matching key" notice instead.
    if (dongCode !== undefined) {
      searchByDong()
    }

    // Non-browser / no Permissions API → fall through to LocationConsent,
    // which itself falls back to a dongCode list if geolocation is missing.
    const hasPermissions =
      typeof navigator !== 'undefined' &&
      navigator.permissions != null &&
      typeof navigator.permissions.query === 'function'

    if (!hasPermissions) {
      if (!cancelled) setBranch('unknown')
      return () => {
        cancelled = true
        mountedRef.current = false
      }
    }

    navigator.permissions
      .query({ name: 'geolocation' as PermissionName })
      .then((status) => {
        if (cancelled) return
        const apply = (state: PermissionState): void => {
          if (cancelled) return
          if (state === 'granted') {
            setBranch('granted')
            // Auto-read only when both signals agree: explicit consent at
            // registration AND the browser permission is granted. Every
            // other combination is handled by the card (see the render
            // branch below), including "granted but no consent flag" —
            // the typical contract response — where we must NOT auto-read
            // but we DO show the card so the user can read once on tap.
            const consentFlag = profile?.consents?.location
            if (!geoStarted.current && consentFlag === true) {
              geoStarted.current = true
              if (
                typeof navigator !== 'undefined' &&
                navigator.geolocation != null
              ) {
                navigator.geolocation.getCurrentPosition(
                  (pos) => {
                    if (!cancelled) {
                      searchByCoord(pos.coords.latitude, pos.coords.longitude)
                    }
                  },
                  () => {
                    // Failure is non-fatal: the dongCode list already shown
                    // remains authoritative. No state change needed.
                  },
                  GEO_OPTIONS,
                )
              }
            }
          } else if (state === 'denied') {
            setBranch('denied')
          } else {
            setBranch('unknown')
          }
        }
        apply(status.state)
        // Observe live permission changes. If the user
        // flips the OS/browser toggle while the page is open we re-apply
        // the branch. This is NOT background location observation — it
        // only re-runs the branching logic; getCurrentPosition is still
        // one-shot (guarded by geoStarted).
        status.onchange = () => {
          if (!cancelled) apply(status.state)
        }
      })
      .catch(() => {
        // Throwing from permissions.query (e.g. unsupported name in some
        // browsers) is treated as 'unknown' → user-driven consent path.
        if (!cancelled) setBranch('unknown')
      })

    return () => {
      cancelled = true
      mountedRef.current = false
    }
  }, [searchByDong, searchByCoord, dongCode, profile])

  // ---- coord callbacks from LocationConsent (prompt branch) -----------

  const onConsentResolved = (lat: number, lng: number): void => {
    // Replaces the dongCode list with a coordinate-basis list.
    searchByCoord(lat, lng)
  }
  const onConsentFailed = (): void => {
    // Nothing to do: the dongCode list is already on screen.
  }

  return (
    <section id="shelter-section" aria-label={t('shelter.sectionLabel', lang)}>
      {/* SAFETY: when we have no matching 행정동 key we MUST NOT
          search. This is the honest notice for that case — the
          frontend does not invent a fallback list with shelters plucked
          from a hardcoded dong. The screen still renders a clear reason
          and a path forward (the user re-loads the session via the
          Landing-level retry). */}
      {dongCode === undefined && (
        <div
          role="status"
          style={{
            background: C.white,
            border: `2px solid ${C.warn}`,
            borderRadius: '18px',
            padding: '19px 20px',
            boxShadow: SHADOW_CARD,
          }}
        >
          <p
            style={{
              margin: '0 0 9px',
              fontSize: '18px',
              fontWeight: 800,
              color: C.navy,
              letterSpacing: '-.02em',
              lineHeight: 1.45,
              textWrap: 'pretty',
            }}
          >
            {t('shelter.noMatchingKey.title', lang)}
          </p>
          <p
            style={{
              margin: 0,
              fontSize: '16px',
              lineHeight: 1.62,
              letterSpacing: '-.012em',
              color: C.body,
              textWrap: 'pretty',
            }}
          >
            {t('shelter.noMatchingKey.body', lang)}
          </p>
        </div>
      )}

      {dongCode !== undefined && loading && (
        <p
          role="status"
          style={{
            margin: 0,
            padding: '15px 16px',
            background: C.tealBg,
            borderRadius: '13px',
            fontSize: '16.5px',
            fontWeight: 700,
            color: C.tealText,
            letterSpacing: '-.015em',
          }}
        >
          {t('shelter.searching', lang)}
        </p>
      )}
      {dongCode !== undefined && error !== null && (
        <p
          role="alert"
          style={{
            margin: 0,
            padding: '15px 16px',
            background: C.alertBg,
            border: `1px solid ${C.alertBorder}`,
            borderRadius: '13px',
            fontSize: '16px',
            lineHeight: 1.6,
            color: C.alertText,
            textWrap: 'pretty',
          }}
        >
          {t('shelter.fetchFailedPrefix', lang)} {error}
        </p>
      )}

      {/* Location-consent card. 이 카드는 대피소 «목록 위»에 있어야 한다 —
          누르면 그 목록이 바뀌므로, 목록을 다 스크롤한 뒤에 나오는 것은
          순서가 거꾸로다. 렌더 조건(deriveLocationMode 판정 + dongCode
          가드)과 `auto`/`refused`/`card` 분기 논리는 그대로이고, 렌더
          위치만 목록 위로 옮겼다. */}
      {dongCode !== undefined &&
        deriveLocationMode(branch, profile?.consents?.location) === 'card' && (
          <div style={{ marginBottom: '14px' }}>
            <LocationConsent
              lang={lang}
              onResolved={onConsentResolved}
              onFailed={onConsentFailed}
            />
          </div>
        )}

      {dongCode !== undefined && result !== null && !loading && (
        <ShelterListView
          result={result}
          lang={lang}
          stairsOkBoolean={stairsOkBoolean}
          stairsState={stairsState}
          basis={result.response.basis}
          dongName={dongName}
          profile={profile}
          userCoord={userCoord}
        />
      )}

      {/* Kakao Map is NO LONGER rendered here unconditionally. It is rendered
          inline per shelter inside ShelterListView, only when the user taps a
          shelter with coords (and only for non-blind profiles). This defers
          SDK loading until first expand (지연 로딩). */}
    </section>
  )
}

// Split the registered-home header template on its `{dong}` placeholder so
// the dong name (a Korean proper noun) can be rendered standalone — on a
// non-Korean screen it is wrapped in a lang="ko" span so a Vietnamese screen
// reader pronounces the dong name with Korean phonetics, while the rest of
// the sentence stays Vietnamese. The text outside the placeholder is UI copy
// and stays in the screen language (resolved by t()).
const HEADER_KO = '등록하신 자택({dong}) 기준 가까운 대피소'
const HEADER_VI = 'Nơi trú ẩn gần theo địa chỉ đã đăng ký ({dong})'

function headerBeforeDong(lang: Language): string {
  const tpl = lang === 'vi' ? HEADER_VI : HEADER_KO
  return tpl.split('{dong}')[0] ?? ''
}
function headerAfterDong(lang: Language): string {
  const tpl = lang === 'vi' ? HEADER_VI : HEADER_KO
  const parts = tpl.split('{dong}')
  return parts.length > 1 ? (parts[1] ?? '') : ''
}

function ShelterListView(props: {
  result: Result
  lang: Language
  // Boolean projection of stairsState for list-sorting and the per-item
  // stairs warning: true means "treat stairs shelters as discouraged" (covers
  // both 'blocked' and 'unknown'). The copy decision uses stairsState.
  stairsOkBoolean: boolean
  stairsState: 'ok' | 'blocked' | 'unknown'
  basis: 'dongCode' | 'coordinate'
  dongName: string
  profile: Profile | null
  userCoord: { lat: number; lng: number } | null
}) {
  const {
    result,
    lang,
    stairsOkBoolean,
    stairsState,
    basis,
    dongName,
    profile,
    userCoord,
  } = props
  const { response } = result

  // v0.3: the server is the authority on exclusions. The client renders
  // `items` verbatim and only reorders for stairsOk. It does NOT filter
  // isUnderground anymore — the server already excluded those.
  const visible: Shelter[] = response.items
  const ordered: Shelter[] = stairsOkBoolean
    ? [...visible].sort((a, b) => a.distanceM - b.distanceM)
    : [
        ...visible.filter((s) => !s.hasStairs).sort(byDistance),
        ...visible.filter((s) => s.hasStairs).sort(byDistance),
      ]

  // 좌표가 있는 대피소만 지도에 표시할 수 있다. 단일 "지도로 모두 보기"
  // 버튼은 이 목록을 한 번에 지도에 그린다.
  const sheltersWithCoords: Shelter[] = ordered.filter(
    (s) => s.lat !== undefined && s.lng !== undefined,
  )

  // Inline per-shelter map expand state. blind 프로필만 항목별로 펼친다
  // (화면낭독 접근 경로). 비 blind 프로필은 목록 아래 단일 지도로 통합.
  const [openId, setOpenId] = useState<string | null>(null)
  // "지도로 모두 보기" 토글. 비 blind 프로필 전용. 대피소마다 지도 버튼이
  // 반복되는 것을 막기 위해 목록 아래 하나만 둔다. 처음 누를 때만 카카오
  // 지도 SDK 가 로드된다(loadKakaoMaps 의 promise 캐시가 중복 로드를 막는다).
  const [showAllMap, setShowAllMap] = useState<boolean>(false)
  const isBlind = profile?.vision === 'blind'

  // availability carries the freshness/outage axis:
  //   cache_only           — upstream was unreachable; this is a cached list.
  //                          dataAsOf carries the snapshot timestamp. Items
  //                          MUST be rendered (they are usable safety data).
  //   upstream_unavailable — the server could not build a list at all. items
  //                          is empty; the UI must show fallback guidance so
  //                          the user does not stay in place unaware.
  //   all_excluded         — every candidate was excluded (침수 위험·운영 중단·
  //                          가는 길 위험). items is empty; the AllExcludedNotice
  //                          renders.
  //   ok                   — normal real-time list.
  const isCacheOnly = response.availability === 'cache_only'
  const isUpstreamUnavailable =
    response.availability === 'upstream_unavailable'
  const allExcluded = response.availability === 'all_excluded'
  const totalExcluded = sumExcluded(response.excluded)

  // Locale for the cache-timestamp rendering.
  const locale = lang === 'vi' ? 'vi-VN' : 'ko-KR'

  return (
    <div>
      <p
        style={{
          margin: '0 0 12px',
          fontSize: '17px',
          fontWeight: 800,
          color: C.navy,
          letterSpacing: '-.02em',
          lineHeight: 1.5,
          textWrap: 'pretty',
        }}
      >
        {basis === 'coordinate' ? (
          t('shelter.nearbyCurrentLocation', lang)
        ) : (
          // The registered-home header embeds the dong name (a Korean proper
          // noun) as data. When the screen language is not Korean, wrap that
          // proper noun in a lang="ko" span so a Vietnamese screen reader
          // switches to the Korean pronunciation engine for the dong name
          // only — the rest of the sentence stays Vietnamese. On a Korean
          // screen the whole sentence is Korean already, so no wrap.
          <>
            {headerBeforeDong(lang)}
            {lang !== 'ko' ? <KoreanSpan>{dongName}</KoreanSpan> : dongName}
            {headerAfterDong(lang)}
          </>
        )}
      </p>

      {/* dataAsOf !== null means cached/stale data. Disclose it honestly
          so the user knows the list might not be fresh. This covers both
          cache_only (cached list with items) and upstream_unavailable
          (no items, just the timestamp of the last good snapshot). */}
      {response.dataAsOf !== null && (
        <p style={banner('warn')}>
          {t('shelter.cacheAsOf', lang, {
            when: new Date(response.dataAsOf).toLocaleString(locale),
          })}
        </p>
      )}

      {/* server-excluded facilities (underground / closed / unreachable). */}
      {totalExcluded > 0 && !allExcluded && (
        <p style={banner('alert')}>
          {t('shelter.excludedPrefix', lang, { count: totalExcluded })}
          {formatExcluded(response.excluded, lang)}
        </p>
      )}

      {/* all_excluded: every shelter was excluded by the server. */}
      {allExcluded && <AllExcludedNotice excluded={response.excluded} lang={lang} />}
      {allExcluded && (
        <NextActionNotice stairsState={stairsState} lang={lang} />
      )}

      {/* upstream_unavailable: the server could not build a list at all.
          Show fallback guidance — the user must not see a bare "no shelters"
          message that could make them stay in place. This is a normal 200,
          not an error; the network may be down but the last guidance must
          still reach the user. */}
      {isUpstreamUnavailable && (
        <p role="status" style={banner('warn')}>
          {t('shelter.degradedNotice', lang)}
        </p>
      )}
      {isUpstreamUnavailable && (
        <NextActionNotice stairsState={stairsState} lang={lang} />
      )}

      {/* cache_only with an EMPTY item list. The cached snapshot
          carried zero usable shelters for this location, but unlike
          upstream_unavailable there WAS a response — it just happened to
          contain no items. The resident must NOT be left with the bare
          cacheAsOf banner and a dead-end empty list. The next-action
          notice gives them the same honest guidance the other empty
          branches get, conditioned on stairsState (so a registration
          session with unverified stairs ability gets stairsUnknown, not
          a definitive upstairs instruction). This branch is checked
          AFTER the cacheAsOf banner so the banner still renders above
          it. Items are non-empty under cache_only in the normal case
          (they are usable safety data); this branch only fires when the
          snapshot itself was empty. */}
      {isCacheOnly && ordered.length === 0 && (
        <>
          <p
            style={{
              margin: '0 0 11px',
              fontSize: '16px',
              lineHeight: 1.62,
              color: C.body,
              textWrap: 'pretty',
            }}
          >
            {t('shelter.emptyList', lang)}
          </p>
          <NextActionNotice stairsState={stairsState} lang={lang} />
        </>
      )}

      {/* Normal empty list — availability ok but server returned 0 items.
          This is NOT upstream_unavailable (the list loaded fine, it is just
          empty) and NOT all_excluded (the server did not report exclusions)
          and NOT cache_only (the cache_only empty case is handled above). */}
      {!isCacheOnly &&
        !isUpstreamUnavailable &&
        !allExcluded &&
        ordered.length === 0 && (
          <>
            <p
              style={{
                margin: '0 0 11px',
                fontSize: '16px',
                lineHeight: 1.62,
                color: C.body,
                textWrap: 'pretty',
              }}
            >
              {t('shelter.emptyList', lang)}
            </p>
            <NextActionNotice stairsState={stairsState} lang={lang} />
          </>
        )}

      <ul
        style={{
          listStyle: 'none',
          padding: 0,
          margin: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: '9px',
        }}
      >
        {ordered.map((s) => {
          // Only shelters carrying coords can be expanded — there is nothing
          // to plot on a map otherwise. Such rows render no expand affordance
          // and never become openId.
          const hasCoord = s.lat !== undefined && s.lng !== undefined
          const isOpen = openId === s.id
          // Bearing label is language-aware; null when the contract carries
          // no bearing for this shelter.
          const dirText = s.bearing != null ? bearingLabel(s.bearing, lang) : null
          const showStairsWarning = s.hasStairs && stairsOkBoolean
          return (
            <li
              key={s.id}
              style={{
                background: C.white,
                borderRadius: '16px',
                padding: '17px 18px',
                boxShadow: SHADOW_CARD,
              }}
            >
              {/* 이름·주소는 왼쪽, 거리는 오른쪽 큰 모노 숫자. 이 화면에서
                  사용자가 비교하는 값은 거리 하나다 — 문장 안에 섞으면
                  스캔이 안 된다. */}
              <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      fontSize: '19px',
                      fontWeight: 800,
                      color: C.navy,
                      letterSpacing: '-.02em',
                      lineHeight: 1.4,
                      marginBottom: '4px',
                    }}
                  >
                    {/* Shelter name is a Korean proper noun (data, not UI copy).
                        On a non-Korean screen it must carry lang="ko" so a
                        Vietnamese screen reader switches to Korean phonetics —
                        this is the place the user has to reach, so it is the
                        single most important run on the row to pronounce right.
                        On a Korean screen the document is already lang="ko", so
                        the wrap is skipped (no duplicate-language noise). */}
                    {lang !== 'ko' ? <KoreanSpan>{s.name}</KoreanSpan> : s.name}
                  </div>
                  {dirText !== null && (
                    <div style={{ fontSize: '17px', color: '#4A6470' }}>
                      {t('shelter.direction', lang)} {dirText}
                    </div>
                  )}
                  <div
                    style={{
                      fontSize: '17px',
                      color: '#4A6470',
                      marginTop: '3px',
                      lineHeight: 1.5,
                    }}
                  >
                    {/* Address is a Korean proper noun for the same reason as the
                        shelter name above — the user has to walk to this address.
                        Same conditional-wrap rule: lang="ko" only off-Korean. */}
                    {lang !== 'ko' ? (
                      <KoreanSpan>{s.address}</KoreanSpan>
                    ) : (
                      s.address
                    )}
                  </div>
                </div>
                <div style={{ flex: 'none', textAlign: 'right' }}>
                  <div style={{ fontSize: '12.5px', color: '#4A6470' }}>
                    {t('shelter.distance', lang)}
                  </div>
                  <div
                    style={{
                      fontFamily: FONT_MONO,
                      fontSize: '19px',
                      fontWeight: 600,
                      color: C.tealText,
                      marginTop: '2px',
                    }}
                  >
                    {formatDistance(s.distanceM, lang)}
                  </div>
                </div>
              </div>

              {/* 계단 경고. 이전에는 주소 문장 뒤에 " · 계단 있음"으로 붙어
                  있어 가장 중요한 제약이 문장 중간에 묻혔다. 독립 블록으로
                  올렸고 문구는 그대로다. */}
              {showStairsWarning && (
                <div
                  style={{
                    marginTop: '11px',
                    background: C.alertBg,
                    border: `1px solid ${C.alertBorder}`,
                    borderRadius: '11px',
                    padding: '11px 13px',
                    fontSize: '17px',
                    fontWeight: 700,
                    color: C.alertText,
                    letterSpacing: '-.015em',
                    lineHeight: 1.5,
                    textWrap: 'pretty',
                  }}
                >
                  {t('shelter.hasStairs', lang)}
                </div>
              )}

              {/* 항목별 확장: blind 프로필에게만 제공한다. blind 화면은
                  지도가 없으므로 각 대피소를 펼쳐 주소·거리·방향을 문장으로
                  읽는 것이 위치를 파악하는 유일한 수단이다(화면낭독 접근 경로).
                  비 blind 프로필에서는 대신 목록 아래 단일 "지도로 모두 보기"
                  버튼으로 지도를 한 번만 보여준다 — 대피소마다 지도 버튼이
                  반복되어 화면이 길어지는 것을 줄인다. */}
              {hasCoord && isBlind && (
                <button
                  type="button"
                  onClick={() => setOpenId(isOpen ? null : s.id)}
                  aria-expanded={isOpen}
                  aria-controls={`shelter-detail-${s.id}`}
                  style={toggleButton(isOpen)}
                >
                  {isOpen
                    ? t('shelter.expand.detail.close', lang)
                    : t('shelter.expand.detail.open', lang)}
                </button>
              )}

              {/* blind 프로필의 항목별 상세 텍스트. 지도가 없는 화면에서
                  펼치면 주소·거리·방향을 완전한 문장으로 보여준다. */}
              {hasCoord && isOpen && isBlind && (
                <div id={`shelter-detail-${s.id}`} style={{ marginTop: '10px' }}>
                  <ShelterDetailBlind shelter={s} lang={lang} />
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {/* 단일 "지도로 모두 보기" 토글. 비 blind 프로필 전용 — 대피소마다
          지도 버튼이 반복되어 화면이 길어지는 것을 막기 위해 목록 아래
          하나만 둔다. 누르면 좌표가 있는 모든 대피소를 단일 지도에 한 번에
          표시한다(마커 N개, 지도 1개). 카카오 지도 SDK 는 이 버튼을 처음
          누를 때만 로드된다. blind 프로필은 지도를 쓰지 않으므로 이 영역
          자체가 나오지 않는다 — blind 의 접근 경로는 항목별 "상세 안내
          보기" 토글이다. */}
      {!isBlind && sheltersWithCoords.length > 0 && (
        <button
          type="button"
          onClick={() => setShowAllMap((v) => !v)}
          aria-expanded={showAllMap}
          aria-controls="shelter-all-map"
          style={toggleButton(showAllMap)}
        >
          {showAllMap
            ? t('shelter.expand.map.close', lang)
            : t('shelter.expand.map.open', lang)}
        </button>
      )}
      {!isBlind && showAllMap && sheltersWithCoords.length > 0 && (
        <div id="shelter-all-map" style={{ marginTop: '10px' }}>
          <ShelterMap
            shelters={sheltersWithCoords}
            userCoord={userCoord}
            lang={lang}
          />
        </div>
      )}
    </div>
  )
}

function sumExcluded(excluded: ShelterExclusion[]): number {
  return excluded.reduce((sum, e) => sum + e.count, 0)
}

// Detailed text block shown when a blind profile expands a shelter. The map
// is never mounted for blind profiles, so this is the equivalent of the
// inline map: it states address, distance and bearing in full sentences
// so a screen reader + TTS can convey the same information the map would.
function ShelterDetailBlind({
  shelter,
  lang,
}: {
  shelter: Shelter
  lang: Language
}) {
  const distLabel = formatDistance(shelter.distanceM, lang)
  // bearing is optional per contract; != null guards both undefined (absent)
  // and null, so bearingLabel never receives undefined.
  const dirLabel =
    shelter.bearing != null ? bearingLabel(shelter.bearing, lang) : null
  return (
    <div
      role="status"
      style={{
        padding: '16px 17px',
        background: C.bg,
        border: `1px solid ${C.border}`,
        borderRadius: '13px',
        fontSize: '17px',
        lineHeight: 1.65,
        letterSpacing: '-.012em',
        color: C.navy,
      }}
    >
      <p style={{ margin: '0 0 9px' }}>
        {/* The blind block relies on screen-reader + TTS, so the language
            tagging of the Korean proper nouns (name, address) matters even
            more here than on the visual row — this IS the channel. Same
            conditional-wrap rule as the visual list: lang="ko" only when
            the screen language is not Korean. */}
        <strong style={{ fontWeight: 800, letterSpacing: '-.02em' }}>
          {lang !== 'ko' ? <KoreanSpan>{shelter.name}</KoreanSpan> : shelter.name}
        </strong>
      </p>
      <p style={{ margin: '0 0 9px' }}>
        {t('shelter.blind.address', lang)}{' '}
        {lang !== 'ko' ? (
          <KoreanSpan>{shelter.address}</KoreanSpan>
        ) : (
          shelter.address
        )}
      </p>
      <p style={{ margin: '0 0 9px' }}>
        {t('shelter.blind.distance', lang)} {distLabel}
        {dirLabel !== null && (
          <>
            {' · '}
            {t('shelter.blind.direction', lang)} {dirLabel}
          </>
        )}
      </p>
      {shelter.hasStairs && (
        <p style={{ margin: 0, fontWeight: 700, color: C.alertText }}>
          {t('shelter.blind.hasStairs', lang)}
        </p>
      )}
    </div>
  )
}

// Build the " (reason N곳, reason N곳, ...)" tail for the exclusion notice.
// Language-aware via excludedReasonLabel + countUnit.
function formatExcluded(excluded: ShelterExclusion[], lang: Language): string {
  const parts = excluded.map(
    (e) => `${excludedReasonLabel(e.reason, lang)} ${e.count}${countUnit(lang)}`,
  )
  return parts.length > 0
    ? ` (${parts.join(t('shelter.allExcluded.reasonSeparator', lang))})`
    : ''
}

function byDistance(a: Shelter, b: Shelter): number {
  return a.distanceM - b.distanceM
}

// ---- all_excluded notice ---------------------------------------
//
// Renders when availability === 'all_excluded' — every shelter the server
// knows about for this location was excluded (침수 위험·운영 중단·가는 길을
// 알 수 없음). The notice has two parts, in this order:
//
//   1. A one-sentence summary of WHY the list collapsed, built from
//      `excluded[]`. Up to 3 reason buckets are named; any further buckets
//      roll up into the "others N" tail. Total count is always stated so the
//      user understands the scale.
//   2. The primary action instruction — the generic guidance line so the
//      user has a clear next step even when no shelter is available.

const EXCLUDED_SUMMARY_LIMIT = 3

interface AllExcludedNoticeProps {
  excluded: ShelterExclusion[]
  lang: Language
}

function AllExcludedNotice({ excluded, lang }: AllExcludedNoticeProps) {
  const total = sumExcluded(excluded)
  const reasonSummary = summarizeExcluded(excluded, lang)

  return (
    <div
      role="status"
      style={{
        background: C.warnBg,
        borderLeft: `4px solid ${C.warn}`,
        borderRadius: '0 12px 12px 0',
        padding: '16px 17px',
        margin: '0 0 11px',
      }}
    >
      {/* Why — the exclusion summary. Always shown so the user understands
          the list didn't fail to load; it was deliberately emptied. */}
      <p
        style={{
          margin: '0 0 11px',
          fontSize: '16px',
          lineHeight: 1.62,
          letterSpacing: '-.012em',
          color: C.warnText,
          textWrap: 'pretty',
        }}
      >
        {total > 0
          ? t('shelter.allExcluded.why', lang, {
              count: total,
              reasons: reasonSummary,
            })
          : t('shelter.allExcluded.whyNone', lang)}
      </p>

      {/* What to do — the primary action instruction. 지시는 설명보다
          무겁게. 이전에는 두 문장이 같은 크기라 무엇이 행동인지 안 보였다. */}
      <p
        style={{
          margin: 0,
          fontSize: '17.5px',
          fontWeight: 800,
          color: C.navy,
          letterSpacing: '-.02em',
          lineHeight: 1.5,
          textWrap: 'pretty',
        }}
      >
        {t('shelter.allExcluded.generic', lang)}
      </p>
    </div>
  )
}

// Build a human-readable summary of the exclusion reason buckets.
// Up to EXCLUDED_SUMMARY_LIMIT reasons are listed by name; any remaining
// buckets collapse into the "others N" tail. Returns an empty string when
// there are no buckets (caller handles that case with its own wording).
function summarizeExcluded(
  excluded: ShelterExclusion[],
  lang: Language,
): string {
  if (excluded.length === 0) return ''
  const sep = t('shelter.allExcluded.reasonSeparator', lang)
  const head = excluded
    .slice(0, EXCLUDED_SUMMARY_LIMIT)
    .map(
      (e) =>
        `${excludedReasonLabel(e.reason, lang)} ${e.count}${countUnit(lang)}`,
    )
  const tailCount = excluded
    .slice(EXCLUDED_SUMMARY_LIMIT)
    .reduce((sum, e) => sum + e.count, 0)
  if (tailCount > 0) {
    head.push(t('shelter.allExcluded.tailOthers', lang, { count: tailCount }))
  }
  return head.join(sep)
}

// Keep the ExcludedReason type reachable for callers that still reference it
// by name; this file no longer needs a local label function (the i18n module
// owns the labels now).
export type { ExcludedReason }

// ---- next-action notice (empty-list branches) -------------------------
//
// Renders when the shelter list is empty for ANY reason (upstream outage,
// all excluded, cache_only with empty snapshot, or a normal empty result).
// The resident must NOT be left with a bare "there are no shelters" line
// that could make them stay in place unaware. The next action is
// conditioned on stairsState:
//   - 'ok'      → move to higher ground / an upper floor.
//   - 'blocked' → honestly admit no action can be offered from this screen;
//     direct to chat / guardian. We do NOT hand a stairs-blocked resident
//     an upstairs instruction.
//   - 'unknown' → registration-built session; stairs ability was never
//     confirmed. We must NOT give a definitive upstairs instruction. Say
//     honestly that we don't know, and direct to chat / guardian.
//
// 톤: 이것은 «지시»다. 그래서 경고 노랑이 아니라 틸이다 — 노랑 배너들
// (캐시·장애) 바로 아래 붙는 경우가 많은데, 같은 색이면 "정보의 연속"으로
// 읽혀 행동 지시가 묻힌다.
interface NextActionNoticeProps {
  stairsState: 'ok' | 'blocked' | 'unknown'
  lang: Language
}

function NextActionNotice({
  stairsState,
  lang,
}: NextActionNoticeProps): React.ReactElement {
  const key =
    stairsState === 'ok'
      ? 'shelter.nextAction.stairsOk'
      : stairsState === 'blocked'
        ? 'shelter.nextAction.stairsBlocked'
        : 'shelter.nextAction.stairsUnknown'
  return (
    <p
      style={{
        margin: '0 0 11px',
        padding: '16px 17px',
        background: C.tealBg,
        borderLeft: `4px solid ${C.tealText}`,
        borderRadius: '0 12px 12px 0',
        fontSize: '17.5px',
        fontWeight: 700,
        color: C.navy,
        letterSpacing: '-.015em',
        lineHeight: 1.55,
        textWrap: 'pretty',
      }}
    >
      {t(key, lang)}
    </p>
  )
}
