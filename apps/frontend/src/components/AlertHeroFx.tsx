// AlertHeroFx — /a 히어로 배경의 비·번개 연출.
//
// 왜 canvas 인가: CSS repeating-linear-gradient 로 빗줄기 패턴을 만들면
// 무아레가 생기고 스크롤 중 눈이 아프다. 파티클을 직접 그리면 간격이
// 불규칙해져 그 문제가 사라진다.
//
// 배터리가 핵심 제약이다. 재난 상황에서 폰 배터리를 깎는 애니메이션은
// 그 자체로 위해다. 그래서:
//   - 30fps 상한. rAF 콜백에서 프레임 간격이 32ms 미만이면 그냥 리턴한다.
//   - 빗방울을 오프스크린 캔버스에 «한 번» 그려두고 drawImage 로 재사용한다.
//     매 프레임 path 를 새로 그리면 CPU 를 훨씬 많이 쓴다.
//   - IntersectionObserver + visibilitychange 로 화면 밖이거나 탭이
//     백그라운드면 rAF 를 취소한다.
//   - devicePixelRatio 상한 2. 3x 폰에서 픽셀 수가 2.25배로 뛴다.
//
// 광과민성(WCAG 2.3.1): 번개는 6.2초 주기이고 한 번에 400ms 안에서 끝난다.
// 초당 0.16회로 상한(초당 3회)의 20분의 1이다. 최대 알파도 0.3 으로 눌러
// 화면이 하얗게 번쩍이지 않는다. prefers-reduced-motion 이면 루프를 아예
// 시작하지 않고 정적 1프레임만 그린다 — "느리게"가 아니라 "없이"다.
//
// aria-hidden: 순수 장식이다. 화면낭독기가 읽을 것이 없다.
//
// TODO(재난 유형): 지금은 항상 비를 그린다. 계약에서 재난 유형을 읽을 수
// 있게 되면 `variant` 를 그 값에 연결해야 한다 — 지진 경보에 비가 내리면
// 화면이 거짓말을 하는 것이다. hazardMatch 는 화면 표시 대상이 아니라고
// 표시돼 있어 여기서 쓰지 않았다.

import { useEffect, useRef } from 'react'

interface Props {
  // 현재는 'rain' 하나뿐. 위 TODO 참조.
  variant?: 'rain'
}

interface Drop {
  x: number
  y: number
  // 낙하 속도(px/s)
  v: number
  len: number
  th: number
  al: number
  // 수평 드리프트 계수
  dx: number
}

// 원경/중경/근경 3층. 층마다 속도·길이·투명도가 달라 깊이가 생긴다.
const LAYERS = [
  { n: 44, len: 24, th: 1, al: 0.07, dx: -5, v: 210 },
  { n: 30, len: 36, th: 1.3, al: 0.095, dx: -8, v: 370 },
  { n: 15, len: 52, th: 2, al: 0.12, dx: -12, v: 600 },
] as const

const LIGHTNING_PERIOD_MS = 6200
const LIGHTNING_DURATION_MS = 400
const LIGHTNING_MAX_ALPHA = 0.3

export function AlertHeroFx({ variant = 'rain' }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    if (variant !== 'rain') return
    const canvas = canvasRef.current
    if (canvas === null) return
    const ctx = canvas.getContext('2d')
    if (ctx === null) return
    // `const ctx` narrowing from the null check above is not carried into the
    // nested function closures (draw/resize) below — TS sees the union again
    // inside those closures. Re-bind to a fresh const typed as non-null so the
    // closures capture a value TS knows is CanvasRenderingContext2D.
    const g: CanvasRenderingContext2D = ctx

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    let width = 0
    let height = 0
    let drops: Drop[] = []
    let raf: number | null = null
    let last = 0
    const t0 = performance.now()
    // 빗방울 스프라이트 캐시. 키는 (길이, 굵기, 드리프트) 조합.
    const sprites = new Map<string, HTMLCanvasElement>()

    function spawn(): void {
      const rand = (a: number, b: number) => a + Math.random() * (b - a)
      const next: Drop[] = []
      for (const layer of LAYERS) {
        for (let i = 0; i < layer.n; i += 1) {
          next.push({
            x: rand(-30, width + 30),
            y: rand(-height, height),
            v: layer.v * rand(0.85, 1.15),
            len: Math.round(layer.len * rand(0.8, 1.2)),
            th: layer.th,
            al: layer.al * rand(0.7, 1.2),
            dx: layer.dx,
          })
        }
      }
      drops = next
    }

    // 빗방울 하나를 오프스크린 캔버스에 그려 캐시한다. 양 끝이 투명해지는
    // 그라디언트라 선분이 공중에 떠 있는 것처럼 보인다.
    function sprite(len: number, th: number, dx: number): HTMLCanvasElement {
      const key = `${len}_${th}_${dx}`
      const hit = sprites.get(key)
      if (hit !== undefined) return hit
      const pad = Math.ceil(th) + 1
      const w = Math.ceil(Math.abs(dx)) + pad * 2
      const h = Math.max(2, len)
      const c = document.createElement('canvas')
      c.width = w
      c.height = h
      const g = c.getContext('2d')
      if (g !== null) {
        const grad = g.createLinearGradient(0, 0, 0, h)
        grad.addColorStop(0, 'rgba(255,255,255,0)')
        grad.addColorStop(0.42, 'rgba(255,255,255,1)')
        grad.addColorStop(1, 'rgba(255,255,255,0)')
        g.strokeStyle = grad
        g.lineWidth = th
        g.lineCap = 'round'
        g.beginPath()
        g.moveTo(w - pad, 0)
        g.lineTo(w - pad + dx, h)
        g.stroke()
      }
      sprites.set(key, c)
      return c
    }

    function draw(dt: number, now: number): void {
      if (width === 0 || height === 0) return
      g.clearRect(0, 0, width, height)

      for (const p of drops) {
        p.y += p.v * dt
        p.x += (p.dx * p.v * dt) / 600
        if (p.y > height) {
          p.y = -p.len - Math.random() * 50
          p.x = Math.random() * (width + 60) - 30
        }
        const s = sprite(p.len, p.th, p.dx)
        g.globalAlpha = p.al
        g.drawImage(s, p.x, p.y, s.width, p.len)
      }
      g.globalAlpha = 1

      // 하단 페이드. 히어로 아래쪽 텍스트 위에 빗줄기가 겹치면 읽기 어려워
      // 진다. destination-out 으로 아래로 갈수록 지운다.
      g.globalCompositeOperation = 'destination-out'
      const mask = g.createLinearGradient(0, height * 0.24, 0, height * 0.6)
      mask.addColorStop(0, 'rgba(0,0,0,0)')
      mask.addColorStop(1, 'rgba(0,0,0,.7)')
      g.fillStyle = mask
      g.fillRect(0, height * 0.24, width, height * 0.76)
      g.globalCompositeOperation = 'source-over'

      if (reduced) return

      // 번개. 한 주기에서 400ms 만 살아 있다. 두 번 치는 모양(80ms 상승 →
      // 급강하 → 재점화 → 감쇠)이라 실제 낙뢰처럼 보인다.
      const phase = (now - t0) % LIGHTNING_PERIOD_MS
      if (phase > LIGHTNING_DURATION_MS) return
      let a: number
      if (phase < 80) a = phase / 80
      else if (phase < 140) a = 1 - ((phase - 80) / 60) * 0.88
      else if (phase < 220) a = 0.12 + (1 - (phase - 140) / 80) * 0.46
      else a = Math.max(0, ((LIGHTNING_DURATION_MS - phase) / 180) * 0.16)
      if (a <= 0.02) return
      g.globalAlpha = Math.min(a * LIGHTNING_MAX_ALPHA, LIGHTNING_MAX_ALPHA)
      const flash = g.createLinearGradient(0, 0, 0, height * 0.78)
      flash.addColorStop(0, 'rgba(255,255,255,1)')
      flash.addColorStop(1, 'rgba(255,255,255,0)')
      g.fillStyle = flash
      g.fillRect(0, 0, width, height * 0.78)
      g.globalAlpha = 1
    }

    function resize(): void {
      const el = canvasRef.current
      if (el === null) return
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const w = el.clientWidth
      const h = el.clientHeight
      if (w === 0 || h === 0) return
      if (w === width && h === height) return
      el.width = Math.round(w * dpr)
      el.height = Math.round(h * dpr)
      g.setTransform(dpr, 0, 0, dpr, 0, 0)
      width = w
      height = h
      spawn()
      if (reduced) draw(0, performance.now())
    }

    function loop(now: number): void {
      raf = window.requestAnimationFrame(loop)
      if (last === 0) {
        last = now
        return
      }
      const gap = now - last
      // 30fps 상한. 120Hz 폰에서 4프레임 중 1프레임만 그린다.
      if (gap < 32) return
      last = now
      draw(Math.min(gap, 64) / 1000, now)
    }

    function start(): void {
      if (reduced || raf !== null) return
      last = 0
      raf = window.requestAnimationFrame(loop)
    }
    function stop(): void {
      if (raf === null) return
      window.cancelAnimationFrame(raf)
      raf = null
    }

    const onResize = () => resize()
    const onVisibility = () => (document.hidden ? stop() : start())

    window.addEventListener('resize', onResize)
    document.addEventListener('visibilitychange', onVisibility)

    let ro: ResizeObserver | null = null
    if ('ResizeObserver' in window) {
      ro = new ResizeObserver(() => resize())
      ro.observe(canvas)
    }

    let io: IntersectionObserver | null = null
    if ('IntersectionObserver' in window) {
      io = new IntersectionObserver(
        (entries) => (entries[0].isIntersecting ? start() : stop()),
        { threshold: 0 },
      )
      io.observe(canvas)
    }

    resize()
    if (reduced) {
      draw(0, performance.now())
    } else {
      start()
    }

    return () => {
      stop()
      window.removeEventListener('resize', onResize)
      document.removeEventListener('visibilitychange', onVisibility)
      if (ro !== null) ro.disconnect()
      if (io !== null) io.disconnect()
      sprites.clear()
    }
  }, [variant])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
      }}
    />
  )
}
