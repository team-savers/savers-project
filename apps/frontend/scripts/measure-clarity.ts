// measure-clarity — 명확성 지표의 나머지 절반(용어 치환율)을 파일로 떨어뜨린다.
//
// 후속_과제.md 5번: 제출 지표를 계산하는 함수(computeSubstitutionStats,
// substituteAdminTerms, measureReadability)는 이미 src/lib/readability.ts에
// 순수 함수로 있는데 출력이 console.info뿐이라 제출용 수치를 뽑을 수단이
// 없었다. 이 스크립트는 **함수를 손대지 않고** 골든 케이스를 입력해 점수를
// JSON으로 찍는다.
//
// 입력은 ai-engine 채점기(apps/ai-engine/eval/run_grounding_eval.py)의 보고서다.
// 골든 케이스를 여기서 다시 생성하지 않는 이유: 같은 실행의 같은 문안을
// 파이썬은 근거 일치율로, 이 스크립트는 명확성으로 채점해야 "같은 제출
// 지표에 진실이 둘"이 되지 않는다(eval/README.md "명확성 지표가 절반만
// 여기 있는 이유"). 사전(ADMIN_TERMS)도 마찬가지 이유로 프론트엔드에만 있다.
//
// ⚠️ 같은 이유로 **단일 행동지침 포함률은 여기서 집계하지 않는다.** 그 지표는
// 파이썬 채점기의 directive_present가 잰다(같은 README의 분업). readability의
// hasSingleAction(사전 action 용어 기준 휴리스틱)은 케이스별 원자료로만
// 남긴다 — 두 휴리스틱이 다른 값을 내는 것은 정상이며, 요약에 올리는 순간
// 같은 KPI에 진실이 둘이 된다.
//
// 치환율은 두 기준으로 낸다:
//   - asGenerated: 생성기가 만든 문안 그대로. 생성은 근거 원문을 그대로
//     인용하는 것이 설계(ADR-0005 verbatim)라 이 값이 낮은 것이 정상이다.
//   - asDisplayed: 사용자가 실제로 보는 문안. 한국어 화면은
//     substituteAdminTerms 적용 후(EasyText·푸시 본문 둘 다 — api/client.ts
//     의 sendTestNotification도 같은 치환을 거친다), 베트남어 화면은 치환
//     사전이 없어 원문 그대로다(EasyText와 동일 분기). **KPI(≥90%)의 대상은
//     이쪽이다** — 지표가 재려는 것은 제품이 전달하는 문장의 명확성이지
//     생성기 중간 산출물이 아니다.
//
// 실행 (Node >= 22.18 — 타입 스트리핑 기본 활성):
//   cd apps/ai-engine/eval && python run_grounding_eval.py --out reports/grounding.json
//   cd apps/frontend && npm run eval:clarity -- --in ../ai-engine/eval/reports/grounding.json

import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import {
  computeSubstitutionStats,
  measureReadability,
  substituteAdminTerms,
} from '../src/lib/readability.ts'
import type { ReadabilityMetric } from '../src/lib/readability.ts'

interface GroundingSide {
  delivered: boolean
  refusalReason: string | null
  body?: string
  sourceQuotes?: string[]
}

interface GroundingCase {
  id: string
  note: string
  language?: string
  guardrailOn: GroundingSide
}

interface GroundingReport {
  generatedAt: string
  generator: string
  caseCount: number
  cases: GroundingCase[]
}

interface SubstitutionStats {
  total: number
  replaced: number
  ratio: number | null
}

interface ClarityCase {
  id: string
  language: string
  scored: boolean
  skipReason: string | null
  // KPI 대상 — 화면 표시 문안 기준 치환율.
  displayed: SubstitutionStats | null
  // 참고 — 생성 문안 그대로의 전체 측정값(hasSingleAction 포함 원자료).
  generated: ReadabilityMetric | null
}

function parseArgs(argv: string[]): { input: string; output: string } {
  const flags = new Map<string, string>()
  for (let i = 0; i < argv.length; i += 1) {
    const key = argv[i]
    if ((key === '--in' || key === '--out') && argv[i + 1] !== undefined) {
      flags.set(key, argv[i + 1] as string)
      i += 1
    }
  }
  const input = flags.get('--in')
  if (input === undefined) {
    console.error(
      '사용법: node scripts/measure-clarity.ts --in <grounding 보고서.json> [--out <출력.json>]',
    )
    process.exit(2)
  }
  const output = flags.get('--out') ?? path.join(path.dirname(input), 'clarity_report.json')
  return { input, output }
}

// measureReadability는 케이스마다 console.info 한 줄을 찍는다(화면 개발용).
// 케이스 수만큼 로그가 쌓이면 CI 로그에서 요약이 묻히므로 채점 동안만 잠근다
// — 데이터는 어차피 JSON 파일로 나간다. 함수를 고치지 않기 위한 선택이다.
function withSilencedInfo<T>(run: () => T): T {
  const original = console.info
  console.info = () => {}
  try {
    return run()
  } finally {
    console.info = original
  }
}

function aggregate(stats: SubstitutionStats[]): {
  macro: number | null
  micro: number | null
  totalTerms: number
  totalReplaced: number
  measurable: number
} {
  const measurable = stats.filter((s) => s.ratio !== null)
  const macro =
    measurable.length > 0
      ? measurable.reduce((sum, s) => sum + (s.ratio as number), 0) / measurable.length
      : null
  const totalTerms = measurable.reduce((sum, s) => sum + s.total, 0)
  const totalReplaced = measurable.reduce((sum, s) => sum + s.replaced, 0)
  const micro = totalTerms > 0 ? totalReplaced / totalTerms : null
  return { macro, micro, totalTerms, totalReplaced, measurable: measurable.length }
}

function main(): number {
  const { input, output } = parseArgs(process.argv.slice(2))
  const report = JSON.parse(fs.readFileSync(input, 'utf-8')) as GroundingReport

  if (!Array.isArray(report.cases)) {
    console.error(`입력이 grounding 보고서 형태가 아닙니다: ${input}`)
    return 2
  }

  const cases: ClarityCase[] = report.cases.map((c) => {
    const language = c.language ?? 'ko'
    const on = c.guardrailOn
    if (!on?.delivered) {
      // 거절은 결함이 아니라 설계된 결과다(근거 없으면 생성 안 함). 명확성은
      // 전달된 문안의 속성이므로 거절 케이스는 채점 대상이 아니고, 0점으로
      // 세면 지표가 오염된다.
      return {
        id: c.id,
        language,
        scored: false,
        skipReason: `refused: ${on?.refusalReason ?? 'unknown'}`,
        displayed: null,
        generated: null,
      }
    }
    if (typeof on.body !== 'string' || !Array.isArray(on.sourceQuotes)) {
      return {
        id: c.id,
        language,
        scored: false,
        skipReason: 'report has no body/sourceQuotes — run_grounding_eval.py가 구버전',
        displayed: null,
        generated: null,
      }
    }
    const body = on.body
    const quotes = on.sourceQuotes
    // 화면 표시 문안 재현 — EasyText·클라이언트 푸시와 같은 분기: 한국어만
    // 치환하고 베트남어는 원문 그대로(사전이 한국어 전용).
    const displayedBody = language === 'vi' ? body : substituteAdminTerms(body).plain
    return withSilencedInfo(() => ({
      id: c.id,
      language,
      scored: true,
      skipReason: null,
      displayed: computeSubstitutionStats(displayedBody, quotes),
      generated: measureReadability(body, quotes),
    }))
  })

  const scored = cases.filter((c) => c.scored)
  const displayed = aggregate(scored.map((c) => c.displayed as SubstitutionStats))
  const generated = aggregate(
    scored.map((c) => (c.generated as ReadabilityMetric).substitutionRatio),
  )

  // 표시 문안에 그래도 남는 어려운 말 — 사전 보강 대상을 바로 보여준다.
  // (치환 후에도 남는 것은 사전에 없는 용어이거나 vi 화면의 한국어 문안이다.)
  const remaining = new Map<string, number>()
  for (const c of scored) {
    for (const term of (c.generated as ReadabilityMetric).adminTermsFound) {
      remaining.set(term, (remaining.get(term) ?? 0) + 1)
    }
  }

  const clarityReport = {
    generatedAt: new Date().toISOString(),
    input: {
      path: input,
      generatedAt: report.generatedAt,
      generator: report.generator,
      caseCount: report.caseCount,
    },
    // 단일 행동지침 포함률은 여기 없다 — apps/ai-engine/eval의 directive_present
    // 가 잰다(분업 근거는 파일 헤더 주석).
    summary: {
      scoredCases: scored.length,
      skippedCases: cases.length - scored.length,
      substitutionRatioDisplayed: {
        macro: displayed.macro,
        micro: displayed.micro,
        totalTerms: displayed.totalTerms,
        totalReplaced: displayed.totalReplaced,
        measurableCases: displayed.measurable,
      },
      substitutionRatioGenerated: {
        macro: generated.macro,
        micro: generated.micro,
        totalTerms: generated.totalTerms,
        totalReplaced: generated.totalReplaced,
        measurableCases: generated.measurable,
      },
      remainingAdminTermsInBody: [...remaining.entries()]
        .sort((a, b) => b[1] - a[1])
        .map(([term, count]) => ({ term, count })),
    },
    cases,
  }

  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, `${JSON.stringify(clarityReport, null, 2)}\n`, 'utf-8')

  const pct = (v: number | null): string => (v === null ? '측정 불가' : `${(v * 100).toFixed(1)}%`)
  console.log(`케이스 ${cases.length}건 (채점 ${scored.length} · 스킵 ${cases.length - scored.length})`)
  console.log(
    `  용어 치환율 · 화면 표시 문안   ${pct(displayed.micro)}  (${displayed.totalReplaced}/${displayed.totalTerms} · 목표 >= 90% · KPI)`,
  )
  console.log(
    `  용어 치환율 · 생성 문안 그대로 ${pct(generated.micro)}  (${generated.totalReplaced}/${generated.totalTerms} · 참고 — verbatim 인용이 설계라 낮은 게 정상)`,
  )
  console.log('  단일 행동지침 포함률: apps/ai-engine/eval 채점기(directive_present)가 잽니다.')
  console.log(`  보고서: ${output}`)
  if (report.generator === 'StubGenerator') {
    // 채점기 README와 같은 정직성 원칙: 스텁 문안의 수치를 실측처럼 인용하면
    // 안 된다. Exit Criteria S1-E3의 "1차 측정치(잠정)" 라벨이 이 상태다.
    console.log(
      '  ⚠️ 입력 문안이 StubGenerator 산출입니다 — 실생성(HyperCLOVA X) 전까지 잠정치로만 인용하세요.',
    )
  }
  return 0
}

process.exit(main())
