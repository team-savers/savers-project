import { useCallback, useRef, useState } from 'react'
import { api } from '../api/client'
import type { UserActionEventType } from '../api/types'

type EventType = Exclude<UserActionEventType, 'next_guidance_requested'>

interface Attempt {
  key: string
  type: EventType
}

export interface ActionFailure {
  retry: () => void
  continueWithoutRecord?: () => void
}

function createKey(type: EventType): string {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  const suffix = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
  return `evacuation.${type}.${suffix}`
}

export function useEvacuationActionFlow(token: string) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [failure, setFailure] = useState<ActionFailure | null>(null)
  const pendingRef = useRef(false)
  const generation = useRef(0)

  const post = useCallback(
    (attempt: Attempt) => api.postSessionEvent(token, { type: attempt.type, payload: {} }, attempt.key),
    [token],
  )

  const run = useCallback((
    types: EventType[],
    onSuccess: () => void,
    continueWithoutRecord?: () => void,
    attempts = types.map((type) => ({ type, key: createKey(type) })),
  ) => {
    if (pendingRef.current) return
    pendingRef.current = true
    setPending(true)
    setError(null)
    setFailure(null)
    const requestGeneration = ++generation.current

    void (async () => {
      try {
        for (const attempt of attempts) await post(attempt)
        if (generation.current === requestGeneration) onSuccess()
      } catch (cause) {
        if (generation.current !== requestGeneration) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setFailure({
          retry: () => run(types, onSuccess, continueWithoutRecord, attempts),
          ...(continueWithoutRecord === undefined ? {} : { continueWithoutRecord }),
        })
      } finally {
        if (generation.current === requestGeneration) {
          pendingRef.current = false
          setPending(false)
        }
      }
    })()
  }, [post])

  const recordBestEffort = useCallback((type: EventType) => {
    const attempt = { type, key: createKey(type) }
    void post(attempt).catch(() => undefined)
  }, [post])

  const clearFailure = useCallback(() => {
    setError(null)
    setFailure(null)
  }, [])

  return {
    pending,
    pendingRef,
    error,
    failure,
    run,
    recordBestEffort,
    clearFailure,
  }
}
