// EasyText — 메시지 본문 카드. 화면에 보이는 단 하나의 본문을 맡는다.
//
// 역할:
//   1. children 으로 받은 message.body 를 화면에 렌더한다. 한국어 화면에서는
//      substituteAdminTerms 로 쉬운 우리말로 치환한 결과를 보여주고, 베트남어
//      화면에서는 사전이 없으므로 원문을 그대로 보여준다. 본문은 이 컴포넌트가
//      유일하게 렌더한다 — 상위(Landing)는 본문 문단을 따로 찍지 않는다.
//   2. "어려운 말 N종을 쉬운 우리말로 바꿨습니다" 고지 줄을 본문 아래 둔다.
//      치환이 하나도 없거나 베트남어 화면이면 이 줄은 숨긴다.
//   3. 읽어주기(SpeakButton)를 본문 바로 아래, 전체 폭·주 동작 색(틸 채움)으로
//      둔다. 읽어주기는 화면에 보이는 문장을 소리 내어 읽는다 — 시각 채널과
//      음성 채널이 같은 문장을 말해야 한다.
//   4. "크게 보기" / "원문 보기" 버튼을 읽어주기 아래 양분 배치한다.
//      - 크게 보기: 본문 글씨를 22px → 34px 로 키운다. 상태는 상위(Landing)가
//        갖는다 — 사용자가 실제로 읽는 본문이 이 컴포넌트 안에 있으므로, 상태
//        소유가 상위여도 본문에 직접 적용된다.
//      - 원문 보기: RAG 근거 인용(sources)을 펼치는 토글이다. 치환 전 원문을
//        보여주는 버튼이 아니다.
//   5. 문장이 둘 이상이면(단계적 노출) "다음" 버튼으로 한 번에 하나씩만
//      펼친다. 문장이 하나뿐이면 이 버튼 자체가 렌더되지 않는다(기존과
//      동일한 한 문단 렌더). 다 펼쳐도 버튼을 없애지 않고 자리와 포커스를
//      유지한 채 라벨만 바꾼다("모두 보여드렸습니다") — 언마운트하면 포커스가
//      body로 떨어지고 아래 읽어주기 버튼이 그 자리로 튀어 오탭을 유발한다
//      (PR #50 리뷰, 접근성 블로킹 코멘트). 비활성 표시는 aria-disabled로만
//      하고 실제 차단은 핸들러에서 한다 — 이유는 버튼 위 주석 참조.
//
// 단계적 노출 순서: 문장 분리(splitIntoSteps)와 행동 지침 우선 노출
// (orderStepsDirectiveFirst)은 lib/readability.ts로 옮겼다 — 순수 함수라
// 프론트엔드에 테스트 러너가 들어오면 바로 테스트할 수 있게 하기 위해서다
// (PR #50 리뷰). 지침 판별은 화면 언어에 따라 갈리므로 lang을 함께 넘긴다.
//
// i18n 범위 주의: "다음" 버튼 라벨만 lib/i18n.ts를 거친다. 이 버튼은 행동
// 지침에 도달하는 **유일한 통로**라서 읽을 수 없는 글자로 두면 지침 자체가
// 닫히지만, 같은 카드의 크게 보기·원문 보기·고지 줄은 여전히 한국어
// 하드코딩이다(이 컴포넌트의 기존 상태이며 PR #50이 만든 것이 아니다).
// 그 셋은 없어도 본문과 행동에 도달할 수 있는 보조 기능이라 우선순위가
// 다르다 — 카드 전체 i18n은 별도 후속 과제로 남긴다.
//
// 본 컴포넌트는 평가 지표 수집을 하지 않는다 — 측정은 상위에서
// measureReadability(original) 로 1회만 수행한다(한 화면 렌더당 1회).
// 여기서는 화면만 담당한다.
//
// VISUAL TREATMENT: the palette follows SAVERS tokens (lib/tokens.ts).
// Text and borders use tealText (#0B6E69, 6.09:1). Action buttons are
// color-coded by role: speak = teal fill (the card's one primary action).
// "다음"(단계적 노출)과 크게 보기는 같은 연틸 secondary 채움을 공유한다 —
// 다음 버튼은 별도 틸 채움을 새로 만들지 않고 toggleStyle('secondary', …)
// 을 그대로 재사용한다(PR #50 리뷰 — 새 버튼이 읽어주기와 같은 색이면
// "켜진 상태는 색 하나로 읽힌다"는 규칙이 흐려진다는 지적). sources = teal
// outline (reference). Touch targets are MIN_TOUCH_PX(52px). The body sits
// inside a card so the "instruction" region is visually distinct from the
// surrounding surface.

import { useMemo, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { orderStepsDirectiveFirst, splitIntoSteps, substituteAdminTerms } from '../lib/readability'
import type { Language, Source } from '../api/types'
import { t } from '../lib/i18n'
import { SpeakButton } from './SpeakButton'
import { C, SHADOW_CARD } from '../lib/tokens'

interface Props {
  // 원문 메시지 본문. children 으로 받되 문자열만 허용한다 —
  // 본 컴포넌트는 문자열을 치환해야 하므로 JSX 조각은 받지 않는다.
  children: string
  // UI 언어. 한국어 화면에서만 쉬운 말 치환을 적용한다. 베트남어 화면에서는
  // 사전이 없으므로 원문을 그대로 본문으로 보여주고 고지 줄도 숨긴다.
  lang: Language
  // RAG 원문 인용문 목록. 비어 있으면 "원문 보기" 버튼이 렌더되지 않는다.
  // undefined 로 생략 가능하며, 그 경우에도 버튼은 렌더되지 않는다.
  sources?: readonly Source[]
  // 글자 크기 확대 여부. 상위(Landing)가 보유하며, 본문이 같은 크기로
  // 커지기 위해 props 로 내려받는다. 기본 false.
  large?: boolean
  // "크게 보기" 버튼을 눌렀을 때 상위에게 알릴 콜백. 상위의 large 상태를
  // 토글하는 용도다. 이 컴포넌트 안에서 large 를 바꾸지 않는다.
  onToggleLarge?: () => void
}

// 큰 글씨 토글이 켜졌을 때의 본문 폰트 크기(px).
const LARGE_FONT_PX = 34

// 기본 본문 폰트 크기(px). 고령 사용자 기본 본문 권장치.
const BASE_FONT_PX = 22

// 터치 영역 최소 높이(px). WCAG 2.5.5 권장(44px)보다 높게 잡는다 — 이 화면의
// 주 사용자가 고령·저시력이다.
const MIN_TOUCH_PX = 52

// 버튼 위계.
//   primary   — 틸 채움. 이 카드의 주 동작(읽어주기).
//   secondary — 연틸 채움. 보조 동작(글씨 크기).
//   outline   — 흰 배경 + 틸 테두리. 참고 동작(근거 원문).
// 켜진 상태는 어느 위계든 네이비 채움으로 수렴한다 — "지금 켜져 있다"가
// 색 하나로 읽혀야 한다.
type Rank = 'primary' | 'secondary' | 'outline'

function toggleStyle(rank: Rank, active: boolean): CSSProperties {
  const base: CSSProperties = {
    minHeight: `${MIN_TOUCH_PX}px`,
    padding: '14px 12px',
    fontFamily: 'inherit',
    fontSize: '17px',
    fontWeight: 700,
    letterSpacing: '-.015em',
    borderRadius: '13px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '8px',
  }
  if (active) {
    return {
      ...base,
      background: C.navy,
      color: C.white,
      border: `2px solid ${C.navy}`,
    }
  }
  if (rank === 'primary') {
    return {
      ...base,
      background: C.tealText,
      color: C.white,
      border: `2px solid ${C.tealText}`,
      boxShadow: '0 8px 20px -12px rgba(11,110,105,.5)',
    }
  }
  if (rank === 'secondary') {
    return {
      ...base,
      background: C.tealBg,
      color: C.tealText,
      border: `2px solid ${C.tealBg}`,
    }
  }
  return {
    ...base,
    background: C.white,
    color: C.tealText,
    // 아우트라인 버튼의 테두리는 흰 카드 위에서 3:1 이상이어야 한다
    // (WCAG 1.4.11 비텍스트 대비). 연틸 계열로는 3:1 을 못 맞춘다.
    border: `2px solid ${C.tealText}`,
  }
}

export function EasyText({
  children,
  lang,
  sources,
  large,
  onToggleLarge,
}: Props): ReactNode {
  // 글자 크기 상태는 상위(Landing)가 보유. 이 컴포넌트는 large 값을 props 로
  // 받아 본문의 크기에 그대로 적용한다. undefined 방어로 기본 false.
  const largeActive = large === true
  // "원문 보기" 토글. 기본은 닫힘(false). sources 가 있을 때만 의미가 있다.
  const [showSources, setShowSources] = useState<boolean>(false)

  // 한국어 화면에서만 본문을 쉬운 말로 치환한다. 베트남어 사전은 없으므로
  // 베트남어 화면에서는 원문을 그대로 본문으로 쓴다.
  const { plain, replaced } = useMemo(
    () => (lang === 'vi' ? { plain: children, replaced: [] } : substituteAdminTerms(children)),
    [children, lang],
  )

  // 단계적 노출. steps.length <= 1 이면 문장을 쪼갤 필요가 없어 기존과 동일한
  // 한 문단 렌더로 폴백한다(hasSteps === false 분기). orderStepsDirectiveFirst
  // 가 행동 지침 문장을 맨 앞으로 옮긴다 — 원문이 "상황 설명 → 행동 지침"
  // 순서라도 첫 화면에 행동 지침이 없는 일이 없게 한다(PR #50 리뷰).
  // lang 을 넘기는 이유: 지침 어미가 언어마다 달라, 한국어 어미만 보면
  // 베트남어 본문에서 지침을 못 찾고 행동 문장이 탭 뒤로 숨는다(같은 리뷰).
  const steps = useMemo(() => orderStepsDirectiveFirst(splitIntoSteps(plain), lang), [plain, lang])
  const hasSteps = steps.length > 1
  const [revealedCount, setRevealedCount] = useState<number>(1)
  // 본문이 바뀌면(새 알림 도착 등) 처음부터 다시 보여준다. 이전 알림을 다
  // 펼쳐본 상태로 다음 알림을 맞으면 안 된다 — 새 지침은 항상 1문장부터.
  // 렌더 중에 조정한다(useEffect가 아니라) — effect는 페인트 이후에 돌기
  // 때문에, 새 본문 문장들이 이전 revealedCount로 먼저 한 프레임 그려졌다가
  // 1문장으로 접히는 깜빡임이 생긴다(PR #50 리뷰 버그 코멘트).
  const [prevPlain, setPrevPlain] = useState(plain)
  if (prevPlain !== plain) {
    setPrevPlain(plain)
    setRevealedCount(1)
  }
  const visibleSteps = hasSteps ? steps.slice(0, revealedCount) : [plain]
  const allRevealed = !hasSteps || revealedCount >= steps.length

  const bodyStyle: CSSProperties = {
    fontSize: largeActive ? `${LARGE_FONT_PX}px` : `${BASE_FONT_PX}px`,
    lineHeight: largeActive ? 1.48 : 1.58,
    letterSpacing: '-.015em',
    fontWeight: 600,
    margin: 0,
    color: '#141A20',
    textWrap: 'pretty',
  }

  // undefined-safe source list. sources 가 undefined 이거나 빈 배열이면
  // 빈 배열로 정규화하여 이후 분기(null-guard)를 단순하게 만든다.
  const sourceList: readonly Source[] = sources ?? []
  const hasSources = sourceList.length > 0

  // 음성으로 낭독할 문자열. 화면에 보이는 본문과 같은 문장을 읽어야 한다 —
  // 시각 채널과 음성 채널이 다른 문장을 말하면 접근성 결함이 된다. 단계적
  // 노출 중에는 "화면에 보이는 것"이 전체 본문이 아니라 지금까지 펼친
  // 문장들이므로, 아직 안 보여준 뒷문장을 미리 읽어버리면 안 된다.
  const spokenText = visibleSteps.join(' ')

  return (
    <div
      style={{
        background: C.white,
        borderRadius: '18px',
        padding: '22px 16px',
        boxShadow: SHADOW_CARD,
      }}
    >
      {/* 본문. 이 영역이 화면에 보이는 유일한 본문이다. 한국어 화면에서는
          원문(message.body)을 쉬운 우리말로 치환한 결과를, 베트남어 화면에서는
          서버 문안 원문을 그대로 보여준다. 글자 크기는 large 상태를 따른다.
          문장이 여럿이면(hasSteps) 한 번에 하나씩 펼치고, 한 문장뿐이면
          기존과 동일하게 통째로 보여준다. aria-live 컨테이너가 문단 전체를
          감싸므로 "다음" 탭으로 새 문장이 추가될 때 화면낭독기가 그 문장만
          알린다. */}
      <div aria-live="polite" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {visibleSteps.map((step, i) => (
          <p key={i} style={bodyStyle}>
            {step}
          </p>
        ))}
      </div>

      {/* "다음" 버튼. 문장이 둘 이상일 때만 렌더한다. 한 번 누를 때마다
          문장 하나씩만 늘린다 — 여러 개를 한꺼번에 펼치면 애초에 쪼갠
          의미가 없다. 다 펼쳐도 언마운트하지 않고 자리와 포커스를 유지한
          채 라벨만 바꾼다(PR #50 리뷰 접근성 코멘트 — 언마운트하면 포커스가
          body로 떨어지고 아래 읽어주기 버튼이 그 자리로 튀어 오탭을
          유발한다).
          ⚠️ `disabled` 를 쓰지 않고 `aria-disabled` 만 쓴다. `disabled` 는
          누른 그 순간 브라우저가 포커스를 body 로 되돌리는 명세 동작이 있어
          (키보드·화면낭독기 사용자는 읽던 위치를 잃고 다음 Tab 이 문서 맨
          위에서 다시 시작한다), 레이아웃만 잡아둬도 포커스 유실은 그대로
          남는다. 게다가 `disabled` 요소는 탭 순서에서 빠져 바뀐 라벨을
          화면낭독기가 읽어줄 방법이 없어진다. 그래서 비활성은 표시만 하고
          실제 차단은 핸들러에서 한다(PR #50 리뷰 2라운드, 머지 전 필수).
          스타일은 크게 보기와 같은 toggleStyle('secondary', …)를 재사용해
          "다음"이 읽어주기(주 동작)처럼 보이지 않게 한다. */}
      {hasSteps && (
        <button
          type="button"
          onClick={() => {
            if (allRevealed) return
            setRevealedCount((n) => Math.min(n + 1, steps.length))
          }}
          aria-disabled={allRevealed}
          style={{
            ...toggleStyle('secondary', false),
            width: '100%',
            marginTop: '10px',
            // 다 펼친 상태는 채움만 낮추고 글자 대비는 유지한다. opacity 를
            // 버튼 전체에 걸면 라벨이 2.5:1 로 떨어지는데, 이 라벨은
            // "끝났다"를 알리는 상태 메시지라 읽혀야 한다 — disabled 를
            // 버리고 탭 순서에 남긴 이유가 정확히 그것이다(PR #50 3라운드).
            ...(allRevealed
              ? { background: C.white, border: `2px solid ${C.tealBg}`, cursor: 'default' }
              : {}),
          }}
        >
          {allRevealed
            ? t('easyText.allRevealed', lang)
            : t('easyText.next', lang, { current: revealedCount, total: steps.length })}
        </button>
      )}

      {/* 고지 줄 — "어려운 말 N종을 쉬운 우리말로 바꿨습니다". 문장이 바뀌었다는
          안내다. 치환이 하나도 없거나 베트남어 화면이면 숨긴다. N 은 치환된
          어려운 말의 종류 수다. */}
      {replaced.length > 0 && (
        <p
          style={{
            margin: '10px 0 0',
            fontSize: '17px',
            lineHeight: 1.6,
            color: C.tealDeep,
          }}
        >
          어려운 말 {replaced.length}종을 쉬운 우리말로 바꿨습니다.
        </p>
      )}

      {/* 읽어주기. 본문 바로 아래, 전체 폭·주 동작 색(틸 채움). 화면에 보이는
          본문과 같은 문장을 소리 내어 읽는다. */}
      <div style={{ marginTop: '14px' }}>
        <SpeakButton text={spokenText} lang={lang} block />
      </div>

      {/* 보조 버튼 2개. 읽어주기 아래 양분 배치한다. hasSources 가 false 면
          "크게 보기"가 줄 전체를 차지한다. */}
      <div
        style={{
          marginTop: '10px',
          display: 'grid',
          gridTemplateColumns: hasSources ? '1fr 1fr' : '1fr',
          gap: '10px',
        }}
      >
        {/* 큰 글씨 토글. aria-pressed 로 켜짐/꺼짐. 상위의 large 상태를
            토글한다 — 이 컴포넌트 안에서 상태를 바꾸지 않는다. 콜백이 없을
            때는 클릭이 무시된다(상위가 상태를 들고 있지 않은 비정상 경로). */}
        <button
          type="button"
          onClick={() => onToggleLarge?.()}
          aria-pressed={largeActive}
          style={toggleStyle('secondary', largeActive)}
        >
          {largeActive ? '작게 보기' : '크게 보기'}
        </button>

        {/* 원문 보기 토글. RAG 근거 인용(sources)을 펼친다. sources 가 있을 때만
            렌더. 개별 source 단위 토글은 금지 — 전체가 한 번에 펼쳐진다. */}
        {hasSources && (
          <button
            type="button"
            onClick={() => setShowSources((v) => !v)}
            aria-pressed={showSources}
            style={toggleStyle('outline', showSources)}
          >
            {showSources ? '원문 닫기' : '원문 보기'}
          </button>
        )}
      </div>

      {/* 근거 원문 인용문. showSources 가 켜졌을 때 모두 펼쳐진다.
          title 이 있으면 title + quote, 없으면 quote 만 표시. */}
      {hasSources && showSources && (
        <ul
          aria-label="이 안내의 원문"
          style={{
            listStyle: 'none',
            padding: 0,
            margin: '14px 0 0',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
          }}
        >
          {sourceList.map((s, i) => (
            <li
              key={i}
              style={{
                background: C.tealBg,
                // 좌측 바는 "이건 우리가 쓴 문장이 아니라 인용"이라는 표시다.
                borderLeft: `4px solid ${C.tealText}`,
                borderRadius: '0 12px 12px 0',
                padding: '15px 16px',
              }}
            >
              {s.title !== '' && (
                <div
                  style={{
                    fontSize: '13px',
                    fontWeight: 700,
                    color: C.tealText,
                    marginBottom: '7px',
                  }}
                >
                  {s.title}
                </div>
              )}
              <div
                style={{
                  fontSize: '17px',
                  lineHeight: 1.62,
                  letterSpacing: '-.012em',
                  color: C.navy,
                  textWrap: 'pretty',
                }}
              >
                {s.quote}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
