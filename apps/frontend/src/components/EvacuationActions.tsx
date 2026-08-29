import { useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Profile, UserActionEventType } from '../api/types'
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
}

function createIdempotencyKey(type: UserActionEventType): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const suffix = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `evacuation.${type}.${suffix}`
}

export function EvacuationActions({ token, guardian, shelterContent }: Props) {
  const [stage, setStage] = useState<Stage>('choice')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const attempts = useRef(new Map<EmptyPayloadEventType, EventAttempt>())
  const call119Attempt = useRef<EventAttempt | null>(null)
  const retryAction = useRef<(() => Promise<void>) | null>(null)

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

  const run = async (action: () => Promise<void>) => {
    if (pending) return
    retryAction.current = action
    setPending(true)
    setError(null)
    try {
      await action()
      retryAction.current = null
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

  const chooseEvacuation = () =>
    run(async () => {
      await record('direct_evacuation_selected')
      await record('evacuation_guidance_viewed')
      setStage('guidance')
    })

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
    <div role="alert" style={{ ...card, border: `2px solid ${C.alertBorder}` }}>
      <p style={{ margin: '0 0 12px', color: C.body, lineHeight: 1.55 }}>
        행동 기록을 저장하지 못했습니다. 다시 시도해 주세요.
      </p>
      <button
        type="button"
        disabled={pending}
        onClick={() => retryAction.current !== null && void run(retryAction.current)}
        style={primary}
      >
        {pending ? '다시 시도하는 중…' : '다시 시도'}
      </button>
    </div>
  )

  if (failure) return failure

  if (stage === 'choice') {
    return (
      <section style={card} aria-labelledby="evacuation-choice-title">
        <h2 id="evacuation-choice-title" style={{ margin: '0 0 8px', color: C.navy, fontSize: '22px' }}>
          지금 어떻게 하시겠어요?
        </h2>
        <p style={{ margin: '0 0 16px', color: C.body, lineHeight: 1.55 }}>
          필요한 행동을 선택해 주세요.
        </p>
        <button type="button" disabled={pending} onClick={() => void chooseHelp()} style={primary}>
          도움이 필요해요
        </button>
        <button type="button" disabled={pending} onClick={() => void chooseEvacuation()} style={secondary}>
          혼자서 대피할게요
        </button>
      </section>
    )
  }

  if (stage === 'help') {
    return (
      <section style={card} aria-labelledby="evacuation-help-title">
        <h2 id="evacuation-help-title" style={{ margin: '0 0 8px', color: C.navy, fontSize: '22px' }}>
          아래 번호로 직접 전화하세요
        </h2>
        <p style={{ margin: '0 0 16px', color: C.body, lineHeight: 1.55 }}>
          자동으로 신고되거나 위치가 공유되지 않습니다.
        </p>
        <a
          href="tel:119"
          onClick={() => {
            void record119().catch(() => undefined)
          }}
          style={{ ...primary, display: 'grid', boxSizing: 'border-box', placeItems: 'center', textDecoration: 'none' }}
        >
          119 전화하기
        </a>
        {guardian !== null && (
          <a
            href={`tel:${guardian.phone}`}
            style={{ ...secondary, display: 'grid', boxSizing: 'border-box', placeItems: 'center', textDecoration: 'none' }}
          >
            보호자에게 전화하기
          </a>
        )}
        <button type="button" onClick={returnFromHelp} style={secondary}>
          이전으로
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
              경로 안내
            </h2>
            <p style={{ margin: 0, color: C.body, lineHeight: 1.55 }}>
              현재는 대피소 위치와 거리 안내만 제공합니다. 이동 중 공식 재난 안내를 함께 확인하세요.
            </p>
          </section>
        ) : null}
        {shelterContent}
        <section style={card}>
          {stage === 'guidance' ? (
            <button type="button" disabled={pending} onClick={() => void startRoute()} style={primary}>
              경로 확인하기
            </button>
          ) : (
            <button type="button" disabled={pending} onClick={() => void confirmArrival()} style={primary}>
              도착했어요
            </button>
          )}
        </section>
      </>
    )
  }

  return (
    <section style={card} aria-labelledby="evacuation-arrived-title">
      <h2 id="evacuation-arrived-title" style={{ margin: '0 0 8px', color: C.tealText, fontSize: '22px' }}>
        도착을 기록했습니다
      </h2>
      <p style={{ margin: 0, color: C.body, lineHeight: 1.55 }}>
        보호자가 현재 세션의 도착 기록을 확인할 수 있습니다.
      </p>
    </section>
  )
}
