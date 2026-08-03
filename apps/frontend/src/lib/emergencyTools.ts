// Client-only "비상 도구" helpers — Wake Lock, vibration, Web Share, siren.
// Every function here wraps a real browser API and feature-detects before
// calling it; none of these have (or need) a backend counterpart — they are
// pure device capabilities, not data the server produces or stores.

import type { Shelter } from '../api/types'

/** Vibrates if the device/browser supports it (Android Chrome; iOS Safari does not). Silently no-ops otherwise. */
export function vibrateSafe(pattern: number | number[]): void {
  if (typeof navigator.vibrate === 'function') {
    navigator.vibrate(pattern)
  }
}

export type ShareResult = 'shared' | 'copied' | 'cancelled' | 'unavailable'

/**
 * Shares (or, failing that, copies) a plain-text line naming the shelter the
 * person is heading to. Deliberately text-only — no raw GPS coordinates are
 * composed here, only the shelter name/address already shown on screen.
 * Both navigator.share and the share-target picker require a user gesture,
 * so this must be called directly from a click handler, not automatically.
 */
export async function shareShelterInfo(shelter: Shelter | null): Promise<ShareResult> {
  const text =
    shelter !== null
      ? `[SAVERS] 지금 ${shelter.name}(${shelter.address})으로 대피 중입니다.`
      : '[SAVERS] 지금 대피 중입니다.'

  if (typeof navigator.share === 'function') {
    try {
      await navigator.share({ text })
      return 'shared'
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return 'cancelled'
      // Non-cancel failure (e.g. share sheet unavailable) — fall through to clipboard.
    }
  }
  if (typeof navigator.clipboard?.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return 'copied'
    } catch {
      return 'unavailable'
    }
  }
  return 'unavailable'
}

/** A single continuous tone via Web Audio — a loud, attention-getting alert sound, started/stopped by explicit user tap (autoplay policies forbid starting audio without a gesture anyway). */
export class Siren {
  private handle: { ctx: AudioContext; osc: OscillatorNode } | null = null

  get isPlaying(): boolean {
    return this.handle !== null
  }

  start(): boolean {
    if (this.handle !== null) return true
    try {
      const ctx = new AudioContext()
      const osc = ctx.createOscillator()
      const gain = ctx.createGain()
      osc.type = 'square'
      osc.frequency.value = 880
      gain.gain.value = 0.2
      osc.connect(gain)
      gain.connect(ctx.destination)
      osc.start()
      this.handle = { ctx, osc }
      return true
    } catch {
      return false
    }
  }

  stop(): void {
    if (this.handle === null) return
    this.handle.osc.stop()
    void this.handle.ctx.close()
    this.handle = null
  }
}
