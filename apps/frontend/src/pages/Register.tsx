// Register (/register). 보호자용 모바일 대리등록 — 소개 랜딩(/)의 CTA가
// 도착하는 화면.
//
// /ops 는 복지관·지자체 담당자용 태블릿 화면이고, 이 화면은 같은 등록을
// 보호자가 자기 폰으로 하는 경로다. 계약(Profile)은 동일하고, 묻는 순서와
// 컨트롤 크기만 폰에 맞춘다.
//
// 설계 제약 (기획서 · ADR-0004):
//   - 402px 모바일 전용. 반응형 데스크톱 레이아웃을 만들지 않는다.
//   - 3단계 마법사(기본 정보 → 대피 관련 정보 → 보호자 정보·동의·최종 확인).
//     폰에서 긴 폼을 한 화면에 쌓으면 이탈한다.
//   - 주거·이동은 select 가 아니라 큰 선택 카드. 폰에서 드롭다운은 답답하다.
//
// 안전 불변식:
//   - 행정동은 ADMIN_DONG 에서만 고른다. 코드를 직접 입력받거나 목록을
//     하드코딩하면 안 된다. 잘못된 코드는 "엉뚱한 동 경보를 받거나 자기 동
//     경보에서 누락"으로 이어지는데, 재난 상황에서 그건 곧 위해다.
//   - userId 는 crypto.getRandomValues 기반 난수 접미사를 붙인다.
//     `Date.now()` 만으로는 추측 가능해서, 값을 아는 사람이 /join?u=<userId>
//     로 남의 등록에 자기 폰 토큰을 붙일 수 있다.
//   - 개인정보 동의(consents.personal)는 필수다. 미동의 시 등록 버튼이
//     동작하지 않는다.
//   - easyText 는 항상 true 다. 묻지 않는다 — "쉬운 말이 필요하냐"고 되묻는
//     것 자체가 낙인이 된다.
//   - 이동 가능 여부(mobility)와 계단 이용 가능 여부(stairsOk)는 서로 독립된
//     질문이다. 한쪽 응답으로 다른 쪽을 자동으로 정하지 않는다 — 천천히
//     이동하지만 계단은 괜찮은 경우, 반대로 이동은 괜찮지만 계단이 어려운
//     경우가 둘 다 실재한다.
//   - 시각 지원 필요 여부는 "화면을 보기 어려우세요?" 예/아니오 단일 질문
//     으로만 묻는다. 내부적으로는 계약 타입 Vision('ok'|'low'|'blind')에
//     담아야 하므로, 예 → 'low' / 아니오 → 'ok' 로 매핑한다(Ops.tsx 의
//     저시력 2단계 정규화와 동일한 관례). 'blind' 는 이 화면에서 UI로
//     노출하지 않는다.
//   - 청력(hearing)·언어(language)는 이 화면에서 UI로 묻지 않는다. 값은
//     각각 기존 정상값 'ok', 고정값 'ko' 로 항상 채워 제출한다 — 숨겼다고
//     해서 필수 필드가 undefined 로 빠지면 저장 자체가 실패한다.
//   - 민감정보 동의(consents.sensitive)가 거짓이면 주거·이동·계단·시력·
//     청력·독거·돌봄 항목을 입력값 그대로 보내지 않고 중립 기본값으로
//     바꿔 보낸다. 동의 문구가 "맞춤 안내가 제한됩니다"라고 약속하고 있으므로,
//     그 약속을 화면 말이 아니라 보내는 데이터에서 지킨다. 언어(language)는
//     안내 언어 선택일 뿐 건강·장애 정보가 아니므로 민감 항목에서 뺀다.
//
// 실패는 조용히 넘기지 않는다: 제출이 실패하면 완료 화면으로 넘어가지 않고
// 오류를 그 자리에 띄운다. 등록이 안 됐는데 됐다고 보이면 알림이 오지 않는
// 사람을 등록됐다고 믿게 만든다.

import { useState } from 'react'
import { registerUserWithPhone } from '../api/client'
import type {
  CareSubject,
  ConsentFlags,
  Guardian,
  Hearing,
  Housing,
  Language,
  Mobility,
  Profile,
  Vision,
} from '../api/types'
import { ADMIN_DONG } from '../mocks/adminDong'
import { C, FONT_MONO } from '../lib/tokens'

// ---------------------------------------------------------------------------
// PALETTE — 현재 SAVERS 최종 팔레트로 맞춘 로컬 별칭. 새 hex 를 만들지 않고
// lib/tokens.ts 의 C.guardian* (Guardian.tsx 가 쓰는 것과 동일한 다섯 색
// 그룹 — 메인 블루/포인트 오렌지/위험 레드/배경/텍스트)를 이 화면이 읽기
// 편한 이름으로만 다시 노출한다. *Text/*Bg 변형은 새 색이 아니라 primary/
// accent/danger 각각의 AA 대비용 파생값이다(teal/tealText 페어링과 동일한
// 기법, Guardian.tsx GC 의 주석 참고).
// ---------------------------------------------------------------------------
const P = {
  primary: C.guardianPrimary,
  primaryText: C.guardianPrimaryText,
  primaryBg: C.guardianPrimaryBg,
  accent: C.guardianAccent,
  accentText: C.guardianAccentText,
  accentBg: C.guardianAccentBg,
  danger: C.guardianDanger,
  dangerText: C.guardianDangerText,
  dangerBg: C.guardianDangerBg,
  bg: C.guardianBg,
  surface: C.white,
  surfaceSoft: C.guardianSurfaceSoft,
  text: C.guardianText,
  textMuted: C.guardianTextMuted,
  line: C.guardianLine,
} as const

// 카드 그림자 — 톤을 예전 navy(#0D2B45)에서 새 기본 텍스트 잉크(#111111)로
// 바꿔 옛 테마의 색을 그림자에도 남기지 않는다.
const SHADOW_CARD = '0 6px 20px -12px rgba(17,17,17,.22)'
const ICON_BASE = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
  flex: 'none',
}

const INPUT: React.CSSProperties = {
  width: '100%',
  minHeight: '56px',
  border: `1.5px solid ${P.line}`,
  borderRadius: '13px',
  padding: '15px 16px',
  fontSize: '18px',
  color: P.text,
  background: P.surface,
  outline: 'none',
  fontFamily: 'inherit',
}

// ---------------------------------------------------------------------------
// 단계
// ---------------------------------------------------------------------------
type Step = 'who' | 'evac' | 'guardian' | 'done'

const STEPS: readonly Step[] = ['who', 'evac', 'guardian', 'done']

const META: Record<Step, { title: string; sub: string; count: string; bar: string }> = {
  who: { title: '기본 정보', sub: '이름과 동네', count: '1 / 3', bar: '33%' },
  evac: { title: '대피 관련 정보', sub: '안내를 정하는 정보', count: '2 / 3', bar: '67%' },
  guardian: { title: '보호자·확인', sub: '연락처와 동의', count: '3 / 3', bar: '100%' },
  done: { title: '등록 완료', sub: '', count: '완료', bar: '100%' },
}

interface FormState {
  name: string
  dongCode: string
  dongName: string
  // null = 아직 안 고름. 2단계에서 두 값 모두 필수다.
  housing: Housing | null
  mobility: Mobility | null
  // mobility 와는 독립된 값이다 — mobility 를 고른다고 자동으로 바뀌지
  // 않는다. null = 아직 안 고름(housing·mobility 와 마찬가지로 evac
  // 단계 필수). 낙관적 기본값(true)을 두면 응답하지 않아도 "계단 이용
  // 가능"으로 제출될 수 있어 null 로 시작한다. 화면에는 노출하지 않는
  // hearing/language 도 이 상태에 남아 있다: 값은 항상 기존 정상값
  // ('ok')·고정값('ko')으로 채워 제출한다.
  stairsOk: boolean | null
  vision: Vision
  hearing: Hearing
  language: Language
  livesAlone: boolean
  care: string
  gName: string
  gPhone: string
  gRel: string
  consents: ConsentFlags
}

// 동이 하나뿐이면 고를 것이 없으므로 미리 채운다. 목록이 늘어나면
// 자동으로 "선택해 주세요" 상태로 돌아간다.
const ONLY_DONG = ADMIN_DONG.length === 1 ? ADMIN_DONG[0] : null

const EMPTY_FORM: FormState = {
  name: '',
  dongCode: ONLY_DONG?.code ?? '',
  dongName: ONLY_DONG?.name ?? '',
  housing: null,
  mobility: null,
  stairsOk: null,
  vision: 'ok',
  // 화면에서 묻지 않는다 — 항상 정상값/고정값으로 제출한다.
  hearing: 'ok',
  language: 'ko',
  livesAlone: true,
  care: '',
  gName: '',
  gPhone: '',
  gRel: '',
  consents: { personal: false, sensitive: false, location: false },
}

// ---------------------------------------------------------------------------
// userId — Ops.tsx 와 동일한 방식. 타임스탬프만으로는 추측 가능하므로
// crypto.getRandomValues 기반 난수 접미사를 붙인다. randomUUID 는 secure
// context 전용이라 LAN 주소에서 undefined 가 되어 등록 버튼이 즉사하므로
// 쓰지 않는다.
// ---------------------------------------------------------------------------
function randomIdSuffix(): string {
  const buf = new Uint8Array(10)
  crypto.getRandomValues(buf)
  let out = ''
  for (let i = 0; i < buf.length; i += 1) {
    out += buf[i].toString(16).padStart(2, '0')
  }
  return out
}

const PHONE_RE = /^\d{2,3}-\d{3,4}-\d{4}$/

// ---------------------------------------------------------------------------
// 민감정보 미동의 시 «특기사항 없음» 에 해당하는 중립 기본값.
// consents.sensitive 가 거짓이면 아래 항목들을 입력값 대신 이 값으로 바꿔
// 보낸다. 필드를 빼는 것이 아니라 값만 중립값으로 덮어쓴다 — Profile 의 필수
// 필드 구조는 그대로 유지된다.
//
// language 는 안내 언어(한국어·베트남어) 선택이지 건강·장애 정보가 아니므로
// 이 목록에서 제외한다. 외국인 노동자 지원은 민감정보 동의와 무관해야 한다.
// ---------------------------------------------------------------------------
const NEUTRAL_HOUSING: Housing = 'normal'
const NEUTRAL_MOBILITY: Mobility = 'ok'
const NEUTRAL_STAIRS_OK = true
const NEUTRAL_VISION: Vision = 'ok'
const NEUTRAL_HEARING: Hearing = 'ok'
const NEUTRAL_LIVES_ALONE = false
const NEUTRAL_CARE: CareSubject | null = null

// ---------------------------------------------------------------------------
// 라디오 그룹
//
// WAI-ARIA APG roving tabindex: 선택이 없으면 첫 항목이 tab 진입점이고,
// 그룹 안 이동은 화살표 + Home/End 다. 모든 항목에 tabIndex 0 을 주면
// tab 키로 그룹을 빠져나가는 데 항목 수만큼 눌러야 한다.
// ---------------------------------------------------------------------------
interface Choice<T> {
  value: T
  label: string
  desc?: string
}

interface RadioGroupProps<T> {
  idPrefix: string
  labelId: string
  options: ReadonlyArray<Choice<T>>
  value: T | null
  onChange: (v: T) => void
  // 'card' = 큰 선택 카드(설명 포함), 'row' = 한 줄, 'inline' = 가로 2분할
  variant?: 'card' | 'row' | 'inline'
}

function RadioGroup<T extends string | boolean>({
  idPrefix,
  labelId,
  options,
  value,
  onChange,
  variant = 'row',
}: RadioGroupProps<T>): React.ReactElement {
  const selectedIndex = options.findIndex((o) => o.value === value)

  function onKeyDown(e: React.KeyboardEvent, i: number): void {
    let next: number | null = null
    if (e.key === 'ArrowDown' || e.key === 'ArrowRight') next = (i + 1) % options.length
    else if (e.key === 'ArrowUp' || e.key === 'ArrowLeft')
      next = (i - 1 + options.length) % options.length
    else if (e.key === 'Home') next = 0
    else if (e.key === 'End') next = options.length - 1
    if (next === null) return
    e.preventDefault()
    onChange(options[next].value)
    // 포커스를 새 항목으로 옮긴다. setTimeout 0 은 리렌더 뒤에 DOM 이
    // 존재하는 것을 보장하기 위한 것.
    window.setTimeout(() => {
      document.getElementById(`${idPrefix}-${next}`)?.focus()
    }, 0)
  }

  return (
    <div
      role="radiogroup"
      aria-labelledby={labelId}
      style={{
        display: 'flex',
        flexDirection: variant === 'inline' ? 'row' : 'column',
        gap: variant === 'inline' ? '9px' : '10px',
      }}
    >
      {options.map((o, i) => {
        const on = o.value === value
        const tabIndex = on || (selectedIndex === -1 && i === 0) ? 0 : -1
        return (
          <button
            key={String(o.value)}
            type="button"
            role="radio"
            id={`${idPrefix}-${i}`}
            aria-checked={on}
            tabIndex={tabIndex}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            style={{
              flex: variant === 'inline' ? 1 : undefined,
              width: variant === 'inline' ? undefined : '100%',
              minHeight: variant === 'card' ? '64px' : '56px',
              background: on ? P.primaryBg : P.surface,
              border: `2px solid ${on ? P.primary : P.line}`,
              borderRadius: variant === 'card' ? '15px' : '13px',
              padding: variant === 'inline' ? '13px 10px' : '15px 17px',
              fontFamily: 'inherit',
              cursor: 'pointer',
              textAlign: variant === 'inline' ? 'center' : 'left',
              display: 'flex',
              alignItems: 'center',
              justifyContent: variant === 'inline' ? 'center' : 'flex-start',
              gap: '13px',
            }}
          >
            {variant !== 'inline' && (
              <span
                aria-hidden="true"
                style={{
                  width: '24px',
                  height: '24px',
                  borderRadius: '50%',
                  border: `2.5px solid ${on ? P.primary : P.line}`,
                  background: on ? P.primary : P.surface,
                  flex: 'none',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                }}
              >
                {on && (
                  <svg
                    viewBox="0 0 24 24"
                    style={{ ...ICON_BASE, width: 13, height: 13, strokeWidth: 3.5, color: P.surface }}
                  >
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                )}
              </span>
            )}
            <span style={{ flex: 1 }}>
              <span
                style={{
                  display: 'block',
                  fontSize: variant === 'card' ? '18px' : '16.5px',
                  fontWeight: variant === 'card' ? 800 : 700,
                  color: on ? P.primaryText : P.text,
                  letterSpacing: '-.02em',
                }}
              >
                {o.label}
              </span>
              {o.desc !== undefined && (
                <span
                  style={{
                    display: 'block',
                    fontSize: '15px',
                    color: P.textMuted,
                    marginTop: '3px',
                    lineHeight: 1.45,
                  }}
                >
                  {o.desc}
                </span>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}

function Card({
  children,
  accent,
}: {
  children: React.ReactNode
  accent?: string
}): React.ReactElement {
  return (
    <div
      style={{
        background: C.white,
        borderRadius: '18px',
        borderTop: accent !== undefined ? `4px solid ${accent}` : undefined,
        padding: '19px 20px',
        boxShadow: SHADOW_CARD,
      }}
    >
      {children}
    </div>
  )
}

function GroupTitle({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <div
      id={id}
      style={{
        fontSize: '17.5px',
        fontWeight: 800,
        color: P.text,
        letterSpacing: '-.02em',
        marginBottom: '12px',
      }}
    >
      {children}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 라벨 (요약 화면용). i18n.ts 에 동일한 표시 헬퍼가 있으면 그쪽을 쓰는 것이
// 맞다 — 여기서는 이 화면이 쓰는 조합만 최소로 둔다.
// ---------------------------------------------------------------------------
const HOUSING_LABEL: Record<Housing, string> = {
  banjiha: '반지하',
  lowland: '저지대',
  normal: '그 밖의 집',
}
const MOBILITY_LABEL: Record<Mobility, string> = {
  ok: '혼자 이동할 수 있음',
  slow: '천천히 이동함',
  assisted: '이동에 도움 필요',
}
// stairsOk 는 mobility 와 독립된 값이라 요약에서도 따로 보여준다.
const STAIRS_LABEL = { yes: '이용 가능', no: '어려움 (계단 없는 곳으로)' } as const

// ---------------------------------------------------------------------------
// Register
// ---------------------------------------------------------------------------
export function Register(): React.ReactElement {
  const [step, setStep] = useState<Step>('who')
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  function set<K extends keyof FormState>(key: K, value: FormState[K]): void {
    setForm((f) => ({ ...f, [key]: value }))
    setError(null)
  }

  function setConsent(key: keyof ConsentFlags, value: boolean): void {
    setForm((f) => ({ ...f, consents: { ...f.consents, [key]: value } }))
    setError(null)
  }

  function validate(current: Step): string | null {
    if (current === 'who') {
      if (form.name.trim() === '') return '등록하실 분의 성함을 적어 주세요.'
      if (form.dongCode.trim() === '') return '사시는 동네를 골라 주세요.'
    }
    if (current === 'evac') {
      if (form.housing === null) return '어디에 사시는지 골라 주세요.'
      if (form.mobility === null) return '혼자 이동할 수 있는지 골라 주세요.'
      if (form.stairsOk === null) return '계단 이용이 어려운지 골라 주세요.'
    }
    if (current === 'guardian') {
      // 비상 연락처는 셋 다 비우거나 셋 다 채우거나여야 한다. 일부만 채우면
      // 급할 때 연락할 수 없는 반쪽 정보가 저장된다.
      const filled = [form.gName, form.gPhone, form.gRel].filter(
        (x) => x.trim() !== '',
      )
      if (filled.length > 0 && filled.length < 3)
        return '비상 연락처는 이름·연락처·관계를 모두 적거나 모두 비워 주세요.'
      const gp = form.gPhone.trim()
      if (gp !== '' && !PHONE_RE.test(gp))
        return '비상 연락처를 010-0000-0000 형태로 적어 주세요.'
      if (!form.consents.personal)
        return '개인정보 수집에 동의해 주셔야 등록할 수 있습니다.'
    }
    return null
  }

  async function submit(): Promise<void> {
    const err = validate('guardian')
    if (err !== null) {
      setError(err)
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const guardian: Guardian | null =
        form.gName.trim() === '' &&
        form.gPhone.trim() === '' &&
        form.gRel.trim() === ''
          ? null
          : {
              name: form.gName.trim(),
              phone: form.gPhone.trim(),
              relation: form.gRel.trim(),
            }
      const care: CareSubject | null =
        form.care.trim() === '' ? null : form.care.trim()

      // 민감정보 동의(consents.sensitive)가 거짓이면, 아래 항목들을 사용자가
      // 입력한 값 그대로 보내지 않고 «특기사항 없음» 중립 기본값으로 바꿔
      // 보낸다. 화면의 동의 문구가 "맞춤 안내가 제한됩니다"라고 약속하고
      // 있으므로, 그 약속을 데이터에서 지킨다. 입력 자체를 막지는 않는다 —
      // 사용자는 계속 입력할 수 있고, 보낼 때 걸러진다.
      //
      // 민감 항목: housing(주거) · mobility(이동) · stairsOk(계단) ·
      //   vision(시력) · hearing(청력) · livesAlone(독거) · care(돌봄).
      // language(안내 언어)는 건강·장애 정보가 아니라 안내 언어 선택이므로
      // 제외한다.
      const sensitiveOk = form.consents.sensitive
      const profile: Profile = {
        userId: `reg-${Date.now()}-${randomIdSuffix()}`,
        name: form.name.trim(),
        dongCode: form.dongCode.trim(),
        dongName: form.dongName.trim(),
        housing: sensitiveOk ? (form.housing ?? NEUTRAL_HOUSING) : NEUTRAL_HOUSING,
        mobility: sensitiveOk ? (form.mobility ?? NEUTRAL_MOBILITY) : NEUTRAL_MOBILITY,
        // validate('evac') 을 통과했으면 null 일 수 없다 — housing/mobility
        // 와 같은 방식으로 ?? 폴백만 두어 타입을 좁힌다.
        stairsOk: sensitiveOk ? (form.stairsOk ?? NEUTRAL_STAIRS_OK) : NEUTRAL_STAIRS_OK,
        // 항상 true. 파일 상단 주석 참조.
        easyText: true,
        vision: sensitiveOk ? form.vision : NEUTRAL_VISION,
        hearing: sensitiveOk ? form.hearing : NEUTRAL_HEARING,
        language: form.language,
        livesAlone: sensitiveOk ? form.livesAlone : NEUTRAL_LIVES_ALONE,
        care: sensitiveOk ? care : NEUTRAL_CARE,
        guardian,
        // 이 화면은 소개 랜딩에서 들어온 보호자 경로다.
        registeredBy: 'guardian',
        consents: { ...form.consents },
      }
      // 이 화면은 피보호자 본인 휴대폰 번호를 더 이상 입력받지 않는다 —
      // registerUserWithPhone 은 그대로 재사용하되 두 번째 인자는 항상
      // null 이다(당사자 폰 연결은 별도 QR/join 절차에서 이루어진다).
      await registerUserWithPhone(profile, null)
      setStep('done')
    } catch (e) {
      // 실패를 완료로 위장하지 않는다. 알림이 오지 않을 사람을 등록됐다고
      // 믿게 만드는 것이 이 화면에서 가장 위험한 실패다.
      setError(
        e instanceof Error
          ? `등록하지 못했습니다. ${e.message}`
          : '등록하지 못했습니다. 잠시 후 다시 시도해 주세요.',
      )
    } finally {
      setSubmitting(false)
    }
  }

  function next(): void {
    const err = validate(step)
    if (err !== null) {
      setError(err)
      return
    }
    if (step === 'guardian') {
      void submit()
      return
    }
    const i = STEPS.indexOf(step)
    setStep(STEPS[Math.min(i + 1, STEPS.length - 1)])
    setError(null)
  }

  function back(): void {
    const i = STEPS.indexOf(step)
    setStep(STEPS[Math.max(i - 1, 0)])
    setError(null)
  }

  const meta = META[step]
  const guardianText =
    form.gName.trim() === '' && form.gPhone.trim() === '' && form.gRel.trim() === ''
      ? '없음'
      : [form.gName.trim(), form.gPhone.trim(), form.gRel.trim()]
          .filter((x) => x !== '')
          .join(' · ')

  const summary: ReadonlyArray<{ k: string; v: string; warn?: boolean }> = [
    { k: '성함', v: form.name.trim() || '—' },
    { k: '동네', v: form.dongName || '—' },
    {
      k: '집',
      v: form.housing === null ? '—' : HOUSING_LABEL[form.housing],
      warn: form.housing === 'banjiha' || form.housing === 'lowland',
    },
    {
      k: '이동',
      v: form.mobility === null ? '—' : MOBILITY_LABEL[form.mobility],
      warn: form.mobility !== null && form.mobility !== 'ok',
    },
    {
      // validate('evac') 을 통과하면 null 일 수 없지만, 렌더 함수가 잘못된
      // 의미("예" 또는 "아니오")를 표시하지 않도록 미응답 표시를 따로 둔다.
      k: '계단',
      v:
        form.stairsOk === null
          ? '—'
          : form.stairsOk
            ? STAIRS_LABEL.yes
            : STAIRS_LABEL.no,
      warn: form.stairsOk === false,
    },
    { k: '화면', v: form.vision === 'low' ? '보기 어려움 (도움 필요)' : '잘 보임' },
    { k: '독거', v: form.livesAlone ? '혼자 사심' : '같이 사는 사람 있음' },
    { k: '돌봄', v: form.care.trim() || '없음' },
    { k: '비상 연락', v: guardianText, warn: guardianText === '없음' },
    { k: '쉬운 말', v: '항상 사용 (기본값)' },
    { k: '등록 주체', v: '보호자가 대신 등록' },
  ]

  return (
    <main
      style={{
        width: '100%',
        maxWidth: '402px',
        margin: '0 auto',
        background: P.bg,
        minHeight: '100vh',
        // 한글은 단어 중간에서 끊지 않는다.
        wordBreak: 'keep-all',
        overflowWrap: 'break-word',
      }}
    >
      {/* ===================== 상단 고정 ===================== */}
      {/* 헤더 배경은 새 팔레트에 없는 예전 navy(#0D2B45) 대신 기본 텍스트
          잉크(#111111, P.text)를 쓴 중립 짙은 배경이다 — 메인 블루는 진행
          표시 채움·CTA·선택 상태처럼 실제 인터랙션 신호에만 쓰고, 헤더
          배경까지 파랗게 칠하면 그 위 진행바 채움(P.primary)이 안 보이게
          된다. */}
      <div
        style={{
          background: P.text,
          color: C.white,
          padding: '20px 22px 22px',
          position: 'sticky',
          top: 0,
          zIndex: 20,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            marginBottom: '16px',
          }}
        >
          {step === 'who' ? (
            // 1단계의 뒤로는 소개 랜딩으로 돌아간다. 죽은 버튼을 두지 않는다.
            <a
              href="/"
              aria-label="세이버스 소개로 돌아가기"
              style={{
                width: '40px',
                height: '40px',
                background: 'rgba(255,255,255,.12)',
                borderRadius: '12px',
                color: C.white,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none',
                textDecoration: 'none',
              }}
            >
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 20, height: 20 }}>
                <path d="m15 18-6-6 6-6" />
              </svg>
            </a>
          ) : step !== 'done' ? (
            <button
              type="button"
              onClick={back}
              aria-label="이전 단계로"
              style={{
                width: '40px',
                height: '40px',
                background: 'rgba(255,255,255,.12)',
                border: 'none',
                borderRadius: '12px',
                color: C.white,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flex: 'none',
              }}
            >
              <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 20, height: 20 }}>
                <path d="m15 18-6-6 6-6" />
              </svg>
            </button>
          ) : (
            <span style={{ width: '40px', flex: 'none' }} />
          )}

          <div style={{ flex: 1 }}>
            <div
              style={{
                fontSize: '17px',
                fontWeight: 800,
                letterSpacing: '-.015em',
              }}
            >
              {meta.title}
            </div>
            {meta.sub !== '' && (
              <div
                style={{
                  fontSize: '13px',
                  color: 'rgba(255,255,255,.62)',
                  marginTop: '1px',
                }}
              >
                {meta.sub}
              </div>
            )}
          </div>

          <span
            style={{
              fontFamily: FONT_MONO,
              fontSize: '13px',
              fontWeight: 600,
              color: P.primary,
              flex: 'none',
            }}
          >
            {meta.count}
          </span>
        </div>

        <div
          role="progressbar"
          aria-valuemin={1}
          aria-valuemax={3}
          // done 은 STEPS 의 4번째 항목이라 +1 이 4 가 되어 valuemax(3)을
          // 넘는다. clamp 만으로 최소 수정한다 — done 에서 바를 숨기는
          // 레이아웃 변경은 이번 리뷰 대응 범위 밖이다.
          aria-valuenow={Math.min(STEPS.indexOf(step) + 1, 3)}
          aria-label="등록 진행 상황"
          style={{
            height: '6px',
            borderRadius: '4px',
            background: 'rgba(255,255,255,.16)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: meta.bar,
              height: '100%',
              borderRadius: '4px',
              background: P.primary,
              transition: 'width .35s cubic-bezier(.22,.7,.3,1)',
            }}
          />
        </div>
      </div>

      {/* ===================== 1 · 누구를 ===================== */}
      {step === 'who' && (
        <div style={{ padding: '24px 22px 130px' }}>
          <h1
            style={{
              fontSize: '25px',
              fontWeight: 800,
              color: P.text,
              letterSpacing: '-.025em',
              lineHeight: 1.35,
              margin: '0 0 11px',
              textWrap: 'pretty',
            }}
          >
            누구를 등록하시나요?
          </h1>
          <p
            style={{
              fontSize: '17px',
              lineHeight: 1.62,
              color: P.textMuted,
              margin: '0 0 22px',
              textWrap: 'pretty',
            }}
          >
            등록하실 분의 이름과 사시는 동네만 있으면 됩니다.
          </p>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <Card>
              <label
                htmlFor="reg-name"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '7px',
                  fontSize: '16px',
                  fontWeight: 700,
                  color: P.text,
                  marginBottom: '9px',
                }}
              >
                성함
                <span
                  style={{
                    background: P.accentBg,
                    color: P.accentText,
                    borderRadius: '6px',
                    padding: '2px 7px',
                    fontSize: '12.5px',
                  }}
                >
                  꼭 필요
                </span>
              </label>
              <input
                id="reg-name"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="예: 김순자"
                autoComplete="name"
                style={INPUT}
              />
            </Card>

            <Card>
              <label
                htmlFor="reg-dong"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '7px',
                  fontSize: '16px',
                  fontWeight: 700,
                  color: P.text,
                  marginBottom: '5px',
                }}
              >
                사시는 동네
                <span
                  style={{
                    background: P.accentBg,
                    color: P.accentText,
                    borderRadius: '6px',
                    padding: '2px 7px',
                    fontSize: '12.5px',
                  }}
                >
                  꼭 필요
                </span>
              </label>
              <div
                style={{
                  fontSize: '15px',
                  color: P.textMuted,
                  lineHeight: 1.5,
                  marginBottom: '11px',
                }}
              >
                이 동네에 경보가 내리면 맞춤 안내를 만듭니다.
              </div>
              {/* 목록은 ADMIN_DONG 이 유일한 출처다. 하드코딩하면 잘못된
                  행정동 코드가 올라갈 수 있다. */}
              <select
                id="reg-dong"
                value={form.dongCode}
                onChange={(e) => {
                  const code = e.target.value
                  const d = ADMIN_DONG.find((x) => x.code === code)
                  setForm((f) => ({
                    ...f,
                    dongCode: code,
                    dongName: d?.name ?? '',
                  }))
                  setError(null)
                }}
                style={{
                  ...INPUT,
                  borderColor: form.dongCode === '' ? P.line : P.primary,
                }}
              >
                <option value="">선택해 주세요</option>
                {ADMIN_DONG.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.name}
                  </option>
                ))}
              </select>
              {ADMIN_DONG.length === 1 && (
                <div
                  style={{
                    fontSize: '14.5px',
                    lineHeight: 1.55,
                    color: P.textMuted,
                    marginTop: '10px',
                    textWrap: 'pretty',
                  }}
                >
                  지금은 관악구 {ADMIN_DONG[0].name}에서만 이용하실 수 있습니다.
                  다른 동네는 준비 중입니다.
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* ===================== 2 · 대피 관련 정보 =====================
          housing·mobility(필수) + stairsOk·vision·livesAlone·care(기본값
          있음, 필수 아님)를 한 단계에 모은다. mobility 와 stairsOk 는 서로
          독립 질문이다. hearing·language 는 이 화면에서 UI로 묻지 않는다
          — hearing 은 EMPTY_FORM 의 정상값('ok'), language 는 고정값
          ('ko') 그대로 제출된다(파일 상단 안전 불변식 참고). */}
      {step === 'evac' && (
        <div style={{ padding: '24px 22px 130px' }}>
          {/* "주의"성 안내(오류 아님) — 위험 레드가 아니라 포인트 오렌지로 표시. */}
          <div
            style={{
              background: P.accentBg,
              borderRadius: '14px',
              padding: '15px 17px',
              marginBottom: '20px',
              display: 'flex',
              gap: '11px',
            }}
          >
            <svg
              viewBox="0 0 24 24"
              style={{
                ...ICON_BASE,
                width: 19,
                height: 19,
                color: P.accentText,
                marginTop: '2px',
              }}
            >
              <path d="m21.7 18-8-14a2 2 0 0 0-3.4 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.7-3Z" />
              <path d="M12 9v4M12 17h.01" />
            </svg>
            <div
              style={{
                fontSize: '15.5px',
                lineHeight: 1.6,
                color: P.accentText,
                textWrap: 'pretty',
              }}
            >
              <b>이 두 가지가 안내 내용을 바꿉니다.</b> 나머지보다 신중히 골라
              주세요.
            </div>
          </div>

          <div
            id="reg-housing-label"
            style={{
              fontSize: '20px',
              fontWeight: 800,
              color: P.text,
              letterSpacing: '-.02em',
              marginBottom: '13px',
            }}
          >
            어디에 사세요?
          </div>
          <div style={{ marginBottom: '28px' }}>
            <RadioGroup<Housing>
              idPrefix="reg-housing"
              labelId="reg-housing-label"
              variant="card"
              value={form.housing}
              onChange={(v) => set('housing', v)}
              options={[
                { value: 'banjiha', label: '반지하', desc: '물이 가장 먼저 차는 곳입니다' },
                { value: 'lowland', label: '저지대', desc: '주변보다 낮아 물이 모입니다' },
                { value: 'normal', label: '그 밖의 집', desc: '반지하도 저지대도 아닙니다' },
              ]}
            />
          </div>

          <div
            id="reg-mobility-label"
            style={{
              fontSize: '20px',
              fontWeight: 800,
              color: P.text,
              letterSpacing: '-.02em',
              marginBottom: '6px',
            }}
          >
            혼자 이동하기 어려우신가요?
          </div>
          <div
            style={{
              fontSize: '15.5px',
              color: P.textMuted,
              lineHeight: 1.55,
              marginBottom: '13px',
            }}
          >
            이동이 어려우면 도움 받기 쉬운 안내를 먼저 드립니다.
          </div>
          <RadioGroup<Mobility>
            idPrefix="reg-mobility"
            labelId="reg-mobility-label"
            value={form.mobility}
            onChange={(v) => set('mobility', v)}
            options={[
              { value: 'ok', label: '혼자 이동할 수 있어요' },
              { value: 'slow', label: '천천히 이동해요' },
              { value: 'assisted', label: '이동에 도움이 필요해요' },
            ]}
          />

          {/* mobility 와는 독립된 질문이다 — 이동은 괜찮아도 계단만
              어려운 경우, 반대로 천천히 이동해도 계단은 괜찮은 경우가
              둘 다 있다. 한쪽 응답이 다른 쪽을 자동으로 정하지 않는다. */}
          <div
            id="reg-stairs-label"
            style={{
              fontSize: '20px',
              fontWeight: 800,
              color: P.text,
              letterSpacing: '-.02em',
              marginBottom: '6px',
              marginTop: '28px',
            }}
          >
            계단 이용이 어려우신가요?
          </div>
          <div
            style={{
              fontSize: '15.5px',
              color: P.textMuted,
              lineHeight: 1.55,
              marginBottom: '13px',
            }}
          >
            계단이 어려우면 계단 없는 대피소를 먼저 알려드립니다.
          </div>
          <RadioGroup<boolean>
            idPrefix="reg-stairs"
            labelId="reg-stairs-label"
            variant="inline"
            value={form.stairsOk === null ? null : !form.stairsOk}
            onChange={(difficult) => set('stairsOk', !difficult)}
            options={[
              { value: false, label: '아니오' },
              { value: true, label: '예' },
            ]}
          />

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '28px' }}>
            <Card>
              <GroupTitle id="reg-vision-label">화면을 보기 어려우세요?</GroupTitle>
              {/* 계약 타입 Vision 은 'ok'|'low'|'blind' 세 값이지만, 이
                  화면은 예/아니오 단일 질문만 노출한다. 예 → 'low',
                  아니오 → 'ok' 로 매핑한다 — Ops.tsx 의 저시력 2단계
                  정규화와 동일한 관례다. 'blind' 는 이 화면에서 고르지
                  않는다(별도 저시력 세부 UI 없음). */}
              <RadioGroup<boolean>
                idPrefix="reg-vision"
                labelId="reg-vision-label"
                variant="inline"
                value={form.vision !== 'ok'}
                onChange={(hard) => set('vision', hard ? 'low' : 'ok')}
                options={[
                  { value: false, label: '아니오' },
                  { value: true, label: '예' },
                ]}
              />
            </Card>

            <Card>
              <GroupTitle id="reg-alone-label">혼자 사세요?</GroupTitle>
              <RadioGroup<boolean>
                idPrefix="reg-alone"
                labelId="reg-alone-label"
                variant="inline"
                value={form.livesAlone}
                onChange={(v) => set('livesAlone', v)}
                options={[
                  { value: true, label: '혼자 살아요' },
                  { value: false, label: '같이 사는 사람 있어요' },
                ]}
              />
            </Card>

            <Card>
              <label
                htmlFor="reg-care"
                style={{
                  display: 'block',
                  fontSize: '17.5px',
                  fontWeight: 800,
                  color: P.text,
                  letterSpacing: '-.02em',
                  marginBottom: '6px',
                }}
              >
                돌봐야 하는 분이 같이 있나요?
              </label>
              <div
                style={{
                  fontSize: '15px',
                  color: P.textMuted,
                  lineHeight: 1.5,
                  marginBottom: '11px',
                }}
              >
                구조를 요청할 때 함께 알립니다. 없으면 비워 두세요.
              </div>
              <input
                id="reg-care"
                value={form.care}
                onChange={(e) => set('care', e.target.value)}
                placeholder="예: 영유아, 와상 가족"
                style={INPUT}
              />
            </Card>

            {/* 쉬운 말은 질문이 아니다. 되묻는 것 자체가 낙인이 된다. */}
            <div
              style={{
                background: P.primaryBg,
                borderRadius: '18px',
                padding: '19px 20px',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  marginBottom: '7px',
                }}
              >
                <span
                  style={{
                    width: '28px',
                    height: '28px',
                    borderRadius: '9px',
                    background: P.primary,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flex: 'none',
                    color: C.white,
                  }}
                >
                  <svg viewBox="0 0 24 24" style={{ ...ICON_BASE, width: 16, height: 16 }}>
                    <path d="M20 6 9 17l-5-5" />
                  </svg>
                </span>
                <span
                  style={{
                    fontSize: '17px',
                    fontWeight: 800,
                    color: P.text,
                    letterSpacing: '-.02em',
                  }}
                >
                  쉬운 말은 늘 켜져 있어요
                </span>
              </div>
              <div
                style={{
                  fontSize: '15.5px',
                  lineHeight: 1.6,
                  color: P.primaryText,
                  textWrap: 'pretty',
                }}
              >
                따로 고르실 필요 없습니다. 안내는 언제나 쉬운 말로 갑니다.
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ===================== 3 · 보호자 정보 · 동의 · 최종 확인 =====================
          구 'care' 단계의 비상 연락처 카드 + 구 'confirm' 단계(요약·동의·
          안내)를 한 단계로 합쳤다. */}
      {step === 'guardian' && (
        <div style={{ padding: '24px 22px 130px' }}>
          <h1
            style={{
              fontSize: '25px',
              fontWeight: 800,
              color: P.text,
              letterSpacing: '-.025em',
              lineHeight: 1.35,
              margin: '0 0 11px',
              textWrap: 'pretty',
            }}
          >
            보호자 정보와 최종 확인
          </h1>
          <p
            style={{
              fontSize: '17px',
              lineHeight: 1.62,
              color: P.textMuted,
              margin: '0 0 22px',
              textWrap: 'pretty',
            }}
          >
            급할 때 연락할 사람을 남기고, 입력한 내용이 맞는지 확인해 주세요.
          </p>

          {/* 비상 연락처. 랜딩에서 온 사람이 곧 보호자이므로 여기서 받지
              않으면 전원 guardian: null 로 등록되고, 수신 화면의 보호자
              호출 경로가 통째로 사라진다. */}
          <Card accent={P.primary}>
            <div
              style={{
                fontSize: '17.5px',
                fontWeight: 800,
                color: P.text,
                letterSpacing: '-.02em',
                marginBottom: '6px',
              }}
            >
              급할 때 연락할 사람
            </div>
            <div
              style={{
                fontSize: '15px',
                color: P.textMuted,
                lineHeight: 1.55,
                marginBottom: '14px',
                textWrap: 'pretty',
              }}
            >
              보통은 <b style={{ color: P.text }}>등록하시는 본인</b>입니다.
              어르신이 움직이지 못할 때 이 번호로 알립니다.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <input
                value={form.gName}
                onChange={(e) => set('gName', e.target.value)}
                placeholder="이름 (예: 이영희)"
                aria-label="비상 연락처 이름"
                style={INPUT}
              />
              <input
                type="tel"
                inputMode="numeric"
                value={form.gPhone}
                onChange={(e) => set('gPhone', e.target.value)}
                placeholder="연락처 (010-0000-0000)"
                aria-label="비상 연락처 번호"
                style={INPUT}
              />
              <input
                value={form.gRel}
                onChange={(e) => set('gRel', e.target.value)}
                placeholder="관계 (예: 딸)"
                aria-label="비상 연락처 관계"
                style={INPUT}
              />
            </div>
          </Card>

          <div style={{ marginTop: '20px', marginBottom: '11px' }}>
            <div
              style={{
                fontSize: '20px',
                fontWeight: 800,
                color: P.text,
                letterSpacing: '-.02em',
                marginBottom: '9px',
              }}
            >
              입력하신 내용
            </div>
            <div
              style={{
                fontSize: '15.5px',
                color: P.textMuted,
                lineHeight: 1.55,
                textWrap: 'pretty',
              }}
            >
              잘못된 곳이 있으면 위 화살표로 돌아가 고쳐 주세요.
            </div>
          </div>

          <div
            style={{
              background: C.white,
              borderRadius: '18px',
              padding: '6px 20px',
              boxShadow: SHADOW_CARD,
              marginBottom: '14px',
            }}
          >
            {summary.map((s, i) => (
              <div
                key={s.k}
                style={{
                  display: 'flex',
                  gap: '14px',
                  padding: '15px 0',
                  borderBottom:
                    i === summary.length - 1 ? 'none' : `1px solid ${P.line}`,
                }}
              >
                <span
                  style={{
                    fontSize: '15.5px',
                    fontWeight: 700,
                    color: P.textMuted,
                    width: '96px',
                    flex: 'none',
                  }}
                >
                  {s.k}
                </span>
                <span
                  style={{
                    fontSize: '17px',
                    fontWeight: 600,
                    // 요약의 "주의" 표시는 오류가 아니라 포인트다 —
                    // 위험 레드가 아니라 포인트 오렌지를 쓴다.
                    color: s.warn === true ? P.accentText : P.text,
                    flex: 1,
                    lineHeight: 1.45,
                  }}
                >
                  {s.v}
                </span>
              </div>
            ))}
          </div>

          {/* 3단계 분리 동의. personal 은 필수 — 미동의 시 등록 불가.
              sensitive 가 거짓이면 주거·이동·계단·시력·청력·독거·돌봄이
              중립값으로 바뀌어 보내지므로 맞춤 안내가 줄어드는 것은 사실이다. */}
          <div
            style={{
              background: C.white,
              border: `1.5px solid ${P.line}`,
              borderRadius: '18px',
              padding: '19px 20px',
              marginBottom: '14px',
            }}
          >
            <div
              style={{
                fontSize: '17px',
                fontWeight: 800,
                color: P.text,
                letterSpacing: '-.02em',
                marginBottom: '14px',
              }}
            >
              동의해 주세요
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <ConsentRow
                id="reg-consent-personal"
                checked={form.consents.personal}
                onChange={(v) => setConsent('personal', v)}
                required
                title="개인정보 수집 (필수)"
                body="성함·연락처·사는 곳을 알림을 보내기 위해 씁니다."
              />
              <ConsentRow
                id="reg-consent-sensitive"
                checked={form.consents.sensitive}
                onChange={(v) => setConsent('sensitive', v)}
                title="건강·장애 정보 수집 (선택)"
                body="동의하지 않으셔도 등록됩니다. 다만 주거·이동·계단·시력·청력·독거·돌봄 정보가 빠지고 기본 안내로 갑니다."
              />
              <ConsentRow
                id="reg-consent-location"
                checked={form.consents.location}
                onChange={(v) => setConsent('location', v)}
                title="위치 정보 이용 (선택)"
                body="알림을 열 때 1회만 확인하고 저장하지 않습니다. 동의하지 않으시면 등록한 동네 기준으로만 안내합니다."
              />
            </div>
          </div>

          <div
            style={{
              background: C.white,
              border: `1.5px solid ${P.line}`,
              borderRadius: '18px',
              padding: '19px 20px',
            }}
          >
            <div
              style={{
                fontSize: '16.5px',
                fontWeight: 800,
                color: P.text,
                letterSpacing: '-.02em',
                marginBottom: '12px',
              }}
            >
              등록하시면 이렇게 됩니다
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '11px' }}>
              {[
                '평소에는 아무 연락도 가지 않습니다.',
                '동네에 경보가 내리면 맞춤 안내를 만들어 드립니다.',
                '비용은 들지 않고, 언제든 그만두실 수 있습니다.',
              ].map((line, i) => (
                <div key={line} style={{ display: 'flex', gap: '11px', alignItems: 'flex-start' }}>
                  <span
                    style={{
                      width: '22px',
                      height: '22px',
                      borderRadius: '50%',
                      background: P.primaryBg,
                      color: P.primaryText,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: '12.5px',
                      fontWeight: 800,
                      flex: 'none',
                      marginTop: '2px',
                    }}
                  >
                    {i + 1}
                  </span>
                  <span
                    style={{
                      fontSize: '16px',
                      lineHeight: 1.55,
                      color: P.textMuted,
                      textWrap: 'pretty',
                    }}
                  >
                    {line}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ===================== 완료 ===================== */}
      {step === 'done' && (
        <div style={{ padding: '44px 22px 60px', textAlign: 'center' }} role="status">
          <div
            style={{
              width: '96px',
              height: '96px',
              borderRadius: '50%',
              // 새 팔레트엔 별도 성공-초록이 없다 — 완료 표시도 메인 블루로
              // 통일한다(예전 초록 C.safe 제거).
              background: P.primary,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 26px',
              boxShadow: '0 14px 32px -14px rgba(24,119,242,.6)',
            }}
          >
            <svg
              viewBox="0 0 24 24"
              style={{ ...ICON_BASE, width: 46, height: 46, strokeWidth: 2.6, color: C.white }}
            >
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </div>
          <h1
            style={{
              fontSize: '27px',
              fontWeight: 800,
              color: P.text,
              letterSpacing: '-.025em',
              lineHeight: 1.35,
              margin: '0 0 13px',
              textWrap: 'pretty',
            }}
          >
            {form.name.trim() || '회원'}님, 등록됐습니다
          </h1>
          <p
            style={{
              fontSize: '17.5px',
              lineHeight: 1.62,
              color: P.textMuted,
              margin: '0 0 30px',
              textWrap: 'pretty',
            }}
          >
            {form.name.trim() || '회원'}님의 정보가 등록됐습니다. 이제{' '}
            {form.dongName || '등록한 동네'}에 경보가 내리면 맞춤 안내를
            만들 수 있습니다.
          </p>

          {/* 등록 완료 화면이 "경보가 내리면 바로 알려드립니다"라고
              약속했지만, 이 화면은 보호자 폰에서 돌아가는 대리등록 경로라
              당사자 폰에 알림이 닿는 데 필요한 연결(QR 코드로 당사자 폰을
              이 등록에 묶는 절차)이 끝나지 않는다. 알림 전송 자체는 동작하나
              이 화면만 거쳐 온 등록은 아직 도착할 폰이 연결돼 있지 않다.
              이 카드는 그 간극을 정직하게 말한다 — 지금 만들어진 안내는
              담당자가 직접 확인하거나, 당사자 폰 연결 뒤 쓸 수 있다.
              "알림 켜는 방법 보기" 같은 이 화면에서는 작동하지 않는 버튼을
              두지 않는다. */}
          <div
            style={{
              background: C.white,
              borderRadius: '18px',
              padding: '22px 20px',
              boxShadow: SHADOW_CARD,
              textAlign: 'left',
              marginBottom: '14px',
            }}
          >
            <div
              style={{
                fontSize: '17px',
                fontWeight: 800,
                color: P.text,
                letterSpacing: '-.02em',
                marginBottom: '9px',
              }}
            >
              알림 전송은 아직 준비 중입니다
            </div>
            <div
              style={{
                fontSize: '16.5px',
                lineHeight: 1.62,
                color: P.textMuted,
                textWrap: 'pretty',
              }}
            >
              지금은 등록된 정보로 맞춤 안내를 만드는 단계까지 동작합니다.
              재난 알림이 자동으로 폰으로 도착하게 하는 기능은 준비 중이며,
              완료되면 등록하신 분께 따로 안내드리겠습니다.
            </div>
          </div>

          <button
            type="button"
            onClick={() => {
              setForm(EMPTY_FORM)
              setStep('who')
              setError(null)
            }}
            style={{
              width: '100%',
              minHeight: '56px',
              background: C.white,
              border: `1.5px solid ${P.primary}`,
              color: P.primaryText,
              borderRadius: '14px',
              padding: '15px',
              fontFamily: 'inherit',
              fontSize: '17px',
              fontWeight: 700,
              cursor: 'pointer',
            }}
          >
            한 분 더 등록하기
          </button>

          <a
            href="/"
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '100%',
              minHeight: '48px',
              marginTop: '12px',
              background: 'none',
              border: 'none',
              color: P.textMuted,
              borderRadius: '14px',
              padding: '13px',
              fontFamily: 'inherit',
              fontSize: '16.5px',
              fontWeight: 600,
              textDecoration: 'underline',
              textUnderlineOffset: '4px',
              cursor: 'pointer',
            }}
          >
            처음 화면으로
          </a>
        </div>
      )}

      {/* ===================== 하단 고정 ===================== */}
      {step !== 'done' && (
        <div
          style={{
            position: 'sticky',
            bottom: 0,
            padding: '14px 22px 22px',
            // 페이지 배경(P.bg = #F8F9FA)과 이어지는 그라데이션 — 예전
            // 배경색(#F4F8F7) 대신 새 배경색의 rgb 로 톤을 맞춘다.
            background:
              'linear-gradient(180deg,rgba(248,249,250,0),rgba(248,249,250,.97) 34%)',
          }}
        >
          {error !== null && (
            <div
              role="alert"
              style={{
                background: P.dangerBg,
                border: `1.5px solid ${P.danger}`,
                borderRadius: '13px',
                padding: '13px 15px',
                marginBottom: '11px',
                fontSize: '16px',
                fontWeight: 700,
                color: P.dangerText,
                letterSpacing: '-.015em',
                textWrap: 'pretty',
              }}
            >
              {error}
            </div>
          )}
          <button
            type="button"
            onClick={next}
            disabled={submitting}
            style={{
              width: '100%',
              minHeight: '62px',
              background: submitting ? P.textMuted : P.primary,
              color: C.white,
              border: 'none',
              borderRadius: '16px',
              padding: '18px',
              fontFamily: 'inherit',
              fontSize: '19px',
              fontWeight: 800,
              letterSpacing: '-.02em',
              cursor: submitting ? 'progress' : 'pointer',
              boxShadow: submitting
                ? 'none'
                : '0 12px 28px -12px rgba(24,119,242,.55)',
            }}
          >
            {submitting
              ? '등록하는 중…'
              : step === 'guardian'
                ? '이대로 등록하기'
                : '다음'}
          </button>
        </div>
      )}
    </main>
  )
}

// ---------------------------------------------------------------------------
// 동의 한 줄. label 로 전체를 감싸 체크박스 밖을 눌러도 토글된다 — 폰에서
// 24px 체크박스만 정확히 누르게 하면 안 된다.
// ---------------------------------------------------------------------------
function ConsentRow({
  id,
  checked,
  onChange,
  title,
  body,
  required = false,
}: {
  id: string
  checked: boolean
  onChange: (v: boolean) => void
  title: string
  body: string
  required?: boolean
}): React.ReactElement {
  return (
    <label
      htmlFor={id}
      style={{
        display: 'flex',
        gap: '12px',
        alignItems: 'flex-start',
        background: checked ? P.primaryBg : P.bg,
        border: `1.5px solid ${checked ? P.primary : P.line}`,
        borderRadius: '13px',
        padding: '14px 15px',
        cursor: 'pointer',
        minHeight: '56px',
      }}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        required={required}
        onChange={(e) => onChange(e.target.checked)}
        style={{
          width: '24px',
          height: '24px',
          accentColor: P.primary,
          margin: '1px 0 0',
          flex: 'none',
        }}
      />
      <span>
        <span
          style={{
            display: 'block',
            fontSize: '16.5px',
            fontWeight: 700,
            color: P.text,
            letterSpacing: '-.015em',
            marginBottom: '3px',
          }}
        >
          {title}
        </span>
        <span
          style={{
            display: 'block',
            fontSize: '15px',
            lineHeight: 1.55,
            color: P.textMuted,
            textWrap: 'pretty',
          }}
        >
          {body}
        </span>
      </span>
    </label>
  )
}
