// Design tokens for SAVERS.
//
// Single source of truth for colour, typography, spacing, radii, and shadow
// values. Screens consume these as plain inline-style objects — no styling
// library is used.
//
// COLOUR TABLE. `C` is the canonical colour table: every hex literal in the
// project lives here exactly once. The older `color` export (kept for the
// screens and helpers that still read it) is derived from `C` below, so the
// two can never drift. New screens should import `C` directly.
//
// Contrast rules (WCAG AA 4.5:1):
//   - The teal used for TEXT and BORDERS is always `tealText` (#0B6E69,
//     6.09:1). `teal` (#0E8C86) is for FILLS and ICONS only — drawing text or
//     a border in it is an accessibility defect.
//   - `tertiary` (#667586) is the lightest grey permitted for body text.

import type { CSSProperties } from 'react'

// ---------------------------------------------------------------------------
// COLOUR — canonical table. Hex values are lowercase by JS/TS convention; they
// are equivalent to the design bundle's uppercase notation.
// ---------------------------------------------------------------------------

/**
 * Canonical colour table. Hex literals live here exactly once; every other
 * colour export in this file is derived from these values.
 */
export const C = {
  /** Base navy — header background, emphasis text, dark cards. */
  navy: '#0D2B45',
  /** Page and input-field background. */
  bg: '#F4F8F7',

  /** Teal — FILL / ICON use only. Lower contrast than `tealText`; never text or borders. */
  teal: '#0E8C86',
  /** Teal — TEXT / BORDER use only (passes AA against light surfaces). */
  tealText: '#0B6E69',
  /** Deep teal — body copy on light-teal surfaces, pressed teal states. */
  tealDeep: '#0B6058',

  /** Mint accent — used ON navy (accent) and for progress bars. */
  mint: '#5FC9AE',
  /** Pale mint — light mint text on navy (lower contrast than `mint`). */
  mintPale: '#9FE3D0',
  /** Light-teal background — quote blocks, secondary buttons. */
  tealBg: '#E6F4F1',

  /** Safety confirmed — completion / success. */
  safe: '#0B7A5C',

  /** Alert / urgent. */
  alert: '#D6293E',
  /** Alert strong — warning text, pressed states. */
  alertDeep: '#B3182B',
  /** Alert body text — darkest red, used for copy inside alert banners. */
  alertText: '#9B1024',
  /** Alert soft / border pairing — light background and border for danger blocks. */
  alertBg: '#FBE4E7',
  alertBorder: '#E9A0AA',

  /** Caution (yellow) border — the non-red warning tone. */
  warn: '#E2B93B',
  /** Caution banner background. */
  warnBg: '#FCF8E9',
  /** Caution banner body text. */
  warnText: '#6B4E00',

  /**
   * Hazard-sign yellow — 과속방지턱/건널목 표지판 톤. Primary surface for
   * high-urgency screens (evacuation flow). Chosen over saturated red as the
   * DOMINANT colour deliberately: red-everywhere reads as sirens/panic, which
   * works against staying calm enough to follow instructions. Red (`alert`)
   * is reserved for small, genuinely critical accents only (a warning dot, a
   * stairs-blocked tag) — never a full-screen or full-button fill.
   */
  hazard: '#F2B705',
  /** Ink on `hazard` — near-black, the hazard-sign contrast convention. */
  hazardInk: '#1A1A1A',

  /** Body secondary text. */
  body: '#4E5968',
  /** Tertiary text — MINIMUM lightness. No grey lighter than this anywhere. */
  tertiary: '#667586',

  /** Borders — inputs and card separators. */
  border: '#C9D6D4',
  /** Neutral surface — BEFORE / comparison blocks, subtle card separation. */
  greyBg: '#F2F4F7',
  /** Card surface. */
  white: '#FFFFFF',
} as const

/**
 * Legacy colour export. Kept so existing screens/helpers that read `color.*`
 * keep working; every value is derived from `C` so the two tables cannot
 * drift. Prefer `C` in new code.
 */
export const color = {
  navy: C.navy,
  canvas: C.bg,

  teal: C.teal,
  tealInk: C.tealText,
  tealDeep: C.tealDeep,

  mint: C.mint,
  mintPale: C.mintPale,
  tealMist: C.tealBg,

  success: C.safe,

  danger: C.alert,
  dangerStrong: C.alertDeep,
  dangerSoft: C.alertBg,
  dangerBorder: C.alertBorder,

  muted: C.body,
  faint: C.tertiary,

  border: C.border,
  greyBg: C.greyBg,
  white: C.white,
} as const

// ---------------------------------------------------------------------------
// ALERT LEVELS
// ---------------------------------------------------------------------------

/**
 * Disaster-special four-step scale (행안부 체계). Each step is a single hex
 * used for chips, banners, and accents tied to a special-report severity.
 *
 * `LEVEL` keys the steps in Korean (the labels users see); `alertLevel` is the
 * same values keyed in English for code that predates the Korean-keyed table.
 * The hex literals live once, in `LEVEL`; `alertLevel` is derived from it.
 */
export const LEVEL = {
  관심: '#1E6FD9',
  주의: '#F2B417',
  경계: '#EE7A21',
  심각: '#D6293E',
} as const

export const alertLevel = {
  concern: LEVEL.관심,
  caution: LEVEL.주의,
  boundary: LEVEL.경계,
  severe: LEVEL.심각,
} as const

// ---------------------------------------------------------------------------
// TYPOGRAPHY
// ---------------------------------------------------------------------------

/**
 * Font family stacks. `system-ui` MUST come last so the app still renders
 * legibly when the CDN font cannot be reached (offline is a hard constraint).
 */
export const fontFamily = {
  // Body and headings.
  sans: "'Pretendard', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  // Labels and timestamps.
  mono: "'IBM Plex Mono', ui-monospace, 'SFMono-Regular', Menlo, Consolas, monospace",
} as const

/** Monospace font stack, as a plain string for inline styles. */
export const FONT_MONO = fontFamily.mono

export interface TextStyle {
  readonly fontSize: string;
  readonly fontWeight: number;
  readonly lineHeight: number;
  readonly letterSpacing: string;
}

/**
 * Type scale. Body is the default reading style; bodyLarge is the "크게 보기"
 * (large-text) variant for accessibility. Sizes follow the design brief's
 * ranges — the lower bound of each range is used as the canonical value.
 */
export const text = {
  // Screen title (h1).
  display: {
    fontSize: '25px',
    fontWeight: 800,
    lineHeight: 1.34,
    letterSpacing: '-0.025em',
  },
  // Section title.
  title: {
    fontSize: '19px',
    fontWeight: 800,
    lineHeight: 1.4,
    letterSpacing: '-0.02em',
  },
  // Card title.
  heading: {
    fontSize: '19px',
    fontWeight: 800,
    lineHeight: 1.4,
    letterSpacing: '-0.02em',
  },
  // Body — default reading size. Minimum body text is 16px; this is 22px
  // (고령 사용자 기준 본문을 한 단계 올렸다).
  body: {
    fontSize: '22px',
    fontWeight: 600,
    lineHeight: 1.6,
    letterSpacing: '-0.015em',
  },
  // Body, 크게 보기 variant for seniors / low vision.
  bodyLarge: {
    fontSize: '34px',
    fontWeight: 600,
    lineHeight: 1.56,
    letterSpacing: '-0.015em',
  },
  // Supporting description / secondary copy.
  caption: {
    fontSize: '17px',
    fontWeight: 400,
    lineHeight: 1.6,
    letterSpacing: '-0.012em',
  },
  // Label / timestamp (mono).
  label: {
    fontSize: '11px',
    fontWeight: 600,
    lineHeight: 1.4,
    letterSpacing: '0.12em',
  },
} as const satisfies Record<string, TextStyle>;

// ---------------------------------------------------------------------------
// SPACE, RADIUS, SHADOW
// ---------------------------------------------------------------------------

/** Spacing scale (px). Mobile side gutters use 20–24px (see `gutter`). */
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  base: 16,
  lg: 20,
  xl: 24,
  xxl: 32,
} as const;

/** Mobile left/right page gutter (20–24px range). */
export const gutter = 20;

/** Corner radii. */
export const radius = {
  card: 16, // 16–22px
  button: 11, // 11–16px
  chip: 20, // pill-shaped chips
} as const;

// Shadow literals live once here; the `shadow` object below is derived so the
// card shadow and the standalone `SHADOW_CARD` constant cannot diverge.
export const SHADOW_CARD = '0 6px 20px -10px rgba(13,43,69,.22)'
export const SHADOW_CTA_TEAL = '0 12px 28px -12px rgba(11,110,105,.55)'
export const SHADOW_CTA_NAVY = '0 10px 28px -12px rgba(13,43,69,.6)'

/** Shadows. */
export const shadow = {
  // Cards.
  card: SHADOW_CARD,
  // High-emphasis (injury) CTA — teal-tinted.
  cta: SHADOW_CTA_TEAL,
} as const;

/** Minimum tap-target sizes (px). Primary CTAs run 56–62px. */
export const touchTarget = {
  minimum: 48,
  ctaMin: 56,
  ctaMax: 62,
} as const;

/**
 * SVG icon common style. Set `color` on the element to choose the stroke
 * colour.
 */
export const ICON: CSSProperties = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  flex: 'none',
}

/**
 * Mobile screen width. The single source of the "402px mobile-only" constraint
 * (ADR-0004). `/ops` is the tablet exception and does not use this value.
 */
export const MOBILE_WIDTH = '402px'
