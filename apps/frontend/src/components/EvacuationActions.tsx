import { useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Language, Profile, UserActionEventType } from '../api/types'
import { t } from '../lib/i18n'
import { C, SHADOW_CARD, touchTarget } from '../lib/tokens'

type Stage = 'choice' | 'help' | 'guidance' | 'route' | 'arrived'
type EmptyPayloadEventType = Exclude<UserActionEventType, 'next_guidance_requested'>

interface EventAttempt {
  key: string
  promise: Promise<void> | null
  succeeded: boolean
}

interface Props {
  token: string
  guardian: Profile['guardian']
  shelterContent: ReactNode
  lang: Language
}

function createIdempotencyKey(type: UserActionEventType): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const suffix = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `evacuation.${type}.${suffix}`
}

export function EvacuationActions({ token, guardian, shelterContent, lang }: Props) {
  const [stage, setStage] = useState<Stage>('choice')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const attempts = useRef(new Map<EmptyPayloadEventType, EventAttempt>())
  const call119Attempt = useRef<EventAttempt | null>(null)
  const retryAction = useRef<(() => Promise<void>) | null>(null)
  const continueAction = useRef<(() => void) | null>(null)

  const postAttempt = (type: EmptyPayloadEventType, attempt: EventAttempt): Promise<void> => {
    if (attempt.succeeded) return Promise.resolve()
    if (attempt.promise !== null) return attempt.promise
    const request = api
      .postSessionEvent(token, { type, payload: {} }, attempt.key)
      .then(() => {
        attempt.succeeded = true
      })
      .finally(() => {
        attempt.promise = null
    })
    attempt.promise = request
    return request
  }

  const record = (type: EmptyPayloadEventType): Promise<void> => {
    const previous = attempts.current.get(type)
    const attempt: EventAttempt = previous ?? {
      key: createIdempotencyKey(type),
      promise: null,
      succeeded: false,
    }
    attempts.current.set(type, attempt)
    return postAttempt(type, attempt)
  }

  const record119 = (): Promise<void> => {
    if (call119Attempt.current === null || call119Attempt.current.succeeded) {
      call119Attempt.current = {
        key: createIdempotencyKey('emergency_call_119_selected'),
        promise: null,
        succeeded: false,
      }
    }
    return postAttempt('emergency_call_119_selected', call119Attempt.current)
  }

  const run = async (action: () => Promise<void>, continueWithoutRecord: (() => void) | null = null) => {
    if (pending) return
    retryAction.current = action
    continueAction.current = continueWithoutRecord
    setPending(true)
    setError(null)
    try {
      await action()
      retryAction.current = null
      continueAction.current = null
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setPending(false)
    }
  }

  const chooseHelp = () =>
    run(async () => {
      await record('help_request_selected')
      setStage('help')
    })

  const returnFromHelp = () => {
    attempts.current.delete('help_request_selected')
    setStage('choice')
  }

  const continueToGuidance = () => {
    setError(null)
    retryAction.current = null
    continueAction.current = null
    setStage('guidance')
  }

  const chooseEvacuation = () =>
    run(
      async () => {
        await record('direct_evacuation_selected')
        await record('evacuation_guidance_viewed')
        setStage('guidance')
      },
      continueToGuidance,
    )

  const startRoute = () =>
    run(async () => {
      await record('route_guidance_started')
      setStage('route')
    })

  const confirmArrival = () =>
    run(async () => {
      await record('arrival_confirmed_by_user')
      setStage('arrived')
    })

  const card: React.CSSProperties = {
    marginBottom: '16px',
    padding: '20px',
    borderRadius: '18px',
    background: C.white,
    boxShadow: SHADOW_CARD,
  }
  const primary: React.CSSProperties = {
    width: '100%',
    minHeight: `${touchTarget.ctaMin}px`,
    padding: '14px 16px',
    border: 'none',
    borderRadius: '14px',
    background: C.navy,
    color: C.white,
    font: 'inherit',
    fontSize: '17px',
    fontWeight: 800,
    cursor: pending ? 'default' : 'pointer',
    opacity: pending ? 0.65 : 1,
  }
  const secondary: React.CSSProperties = {
    ...primary,
    marginTop: '10px',
    border: `2px solid ${C.border}`,
    background: C.white,
    color: C.navy,
  }

  const failure = error !== null && (
    <div
      role="alert"
      style={{ marginBottom: '14px', padding: '14px', border: `2px solid ${C.alertBorder}`, borderRadius: '12px' }}
    >
      <p style={{ margin: '0 0 12px', color: C.body, lineHeight: 1.55 }}>
        {t('evacuation.event.failure', lang)}
      </p>
      <button
        type="button"
        disabled={pending}
        onClick={() => {
          const action = retryAction.current
          const continuation = continueAction.current
          if (action !== null) void run(action, continuation)
        }}
        style={primary}
      >
        {pending ? t('evacuation.event.retrying', lang) : t('evacuation.event.retry', lang)}
      </button>
      {continueAction.current !== null && (
        <button type="button" disabled={pending} onClick={continueAction.current} style={secondary}>
          {t('evacuation.event.continueGuidance', lang)}
        </button>
      )}
    </div>
  )

  if (stage === 'choice') {
    return (
      <section style={card} aria-labelledby="evacuation-choice-title">
        <h2 id="evacuation-choice-title" style={{ margin: '0 0 8px', color: C.navy, fontSize: '22px' }}>
          {t('evacuation.choice.title', lang)}
        </h2>
        <p style={{ margin: '0 0 16px', color: C.body, lineHeight: 1.55 }}>
          {t('evacuation.choice.body', lang)}
        </p>
        {failure}
        <button type="button" disabled={pending} onClick={() => void chooseHelp()} style={primary}>
          {t('evacuation.choice.help', lang)}
        </button>
        <button type="button" disabled={pending} onClick={() => void chooseEvacuation()} style={secondary}>
          {t('evacuation.choice.direct', lang)}
        </button>
      </section>
    )
  }

  if (stage === 'help') {
    return (
      <section style={card} aria-labelledby="evacuation-help-title">
        <h2 id="evacuation-help-title" style={{ margin: '0 0 8px', color: C.navy, fontSize: '22px' }}>
          {t('evacuation.help.title', lang)}
        </h2>
        <p style={{ margin: '0 0 16px', color: C.body, lineHeight: 1.55 }}>
          {t('evacuation.help.body', lang)}
        </p>
        <a
          href="tel:119"
          onClick={() => {
            void record119().catch(() => undefined)
          }}
          style={{ ...primary, display: 'grid', boxSizing: 'border-box', placeItems: 'center', textDecoration: 'none' }}
        >
          {t('evacuation.help.call119', lang)}
        </a>
        {guardian !== null && (
          <a
            href={`tel:${guardian.phone}`}
            style={{ ...secondary, display: 'grid', boxSizing: 'border-box', placeItems: 'center', textDecoration: 'none' }}
          >
            {t('evacuation.help.callGuardian', lang)}
          </a>
        )}
        <button type="button" onClick={returnFromHelp} style={secondary}>
          {t('evacuation.help.back', lang)}
        </button>
      </section>
    )
  }

  if (stage === 'guidance' || stage === 'route') {
    return (
      <>
        {stage === 'route' ? (
          <section style={card} aria-labelledby="evacuation-route-title">
            <h2 id="evacuation-route-title" style={{ margin: '0 0 8px', color: C.navy, fontSize: '22px' }}>
              {t('evacuation.route.title', lang)}
            </h2>
            <p style={{ margin: 0, color: C.body, lineHeight: 1.55 }}>
              {t('evacuation.route.body', lang)}
            </p>
          </section>
        ) : null}
        {shelterContent}
        <section style={card}>
          {failure}
          {stage === 'guidance' ? (
            <button type="button" disabled={pending} onClick={() => void startRoute()} style={primary}>
              {t('evacuation.route.start', lang)}
            </button>
          ) : (
            <button type="button" disabled={pending} onClick={() => void confirmArrival()} style={primary}>
              {t('evacuation.arrival.confirm', lang)}
            </button>
          )}
        </section>
      </>
    )
  }

  return (
    <section style={card} aria-labelledby="evacuation-arrived-title">
      <h2 id="evacuation-arrived-title" style={{ margin: '0 0 8px', color: C.tealText, fontSize: '22px' }}>
        {t('evacuation.arrival.title', lang)}
      </h2>
      <p style={{ margin: 0, color: C.body, lineHeight: 1.55 }}>
        {t('evacuation.arrival.body', lang)}
      </p>
    </section>
  )
}
