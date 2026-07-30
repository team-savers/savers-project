// /ops 등록 대시보드 전용 스타일 상수.
//
// Ops.tsx 는 2,200줄이라 전체 교체가 위험하다. 그래서 스타일만 이 모듈로
// 빼고, Ops.tsx 에서는 «상수 이름을 그대로 유지한 채» 값만 여기로 위임한다.
// 로직·JSX 구조는 손대지 않는다.
//
// 태블릿 예외: /ops 는 이 프로젝트의 유일한 비모바일 화면이다(복지관·지자체
// 담당자용). 다른 화면은 402px 모바일 전용이다(ADR-0004).
//
// 대비 규칙은 tokens.ts 와 동일: 텍스트·테두리는 C.tealText(#0B6E69),
// C.teal(#0E8C86)은 면·아이콘 배경 전용.

import type { CSSProperties } from 'react'
import { C, FONT_MONO, SHADOW_CARD } from './tokens'

// ---- 화면 폭 ----------------------------------------------------------
//
// 소스는 960px 였다. 시안은 1000px 다. 카드 안쪽 폭은 1000px − 좌우
// 바디 패딩 32px × 2 = 936px 이다. 현황 표의 고정 6열(이름·연락처·세이버스
// 등록·발송 상태·마지막 발송 시각·알림 열람 응답)과 작업 열 하한을 합쳐도
// 936px 을 넘지 않도록 열 폭을 잡는다 — 그래야 1000px 셸에서 가로 스크롤이
// 생기지 않는다. 표는 항상 opsTableScroll 래퍼 안에 있어 936px 미만의 좁은
// 화면(태블릿 세로 등)에서는 잘리지 않고 스크롤된다.
export const OPS_WIDTH = '1000px'

// 표의 최소 폭. 이보다 좁아지면 가로 스크롤이 생긴다. 카드 안쪽 폭이
// 936px(=1000px − 좌우 바디 패딩 32px × 2)인데, 거기에 꽉 맞추면 1px 만
// 어긋나도 스크롤이 생긴다. 여유를 두고 908px 로 잡는다. 고정 6열 합
// 632px + 작업 열 하한 260px = 892px 로 그 안에 들어온다.
export const OPS_TABLE_MIN_WIDTH = '908px'

// 현황 표 7열. 헤더 순서대로 대응한다:
//   이름 · 연락처 · 세이버스 등록 · 발송 상태 · 마지막 발송 시각 ·
//   알림 열람 응답 · 비고/발송/삭제
// 고정 6열 합 632px + 작업 열 하한 260px = 892px. 카드 안쪽 폭 936px 안에
// 들어가 1000px 셸에서 가로 스크롤이 생기지 않는다.
//   - 세이버스 등록 96px : 「세이버스 등록」 배지가 한 줄로 들어간다.
//   - 마지막 발송 시각 116px : `20:38:29` 같은 시각이 한 줄에 들어간다.
//     시각 칸의 whiteSpace:nowrap(아래 선언부)과 함께 잡아야 접히지 않는다.
//   - 연락처 150px : 전화번호가 한 줄에 들어간다(이보다 줄이면 두 줄로
//     접힌다).
//   - 작업 열 minmax(260px,1fr) : 1000px 셸에서는 약 304px 까지 벌어지고,
//     좁은 화면에서는 260px 하한 아래로는 줄지 않아 스크롤 래퍼가 동작한다.
export const OPS_TABLE_COLUMNS =
  ' 84px 150px 96px 96px 116px 86px minmax(260px,1fr)';

// ---- 셸 --------------------------------------------------------------

// 바깥 컨테이너. `justify-content: safe center` 가 핵심이다 — 그냥
// `center` 면 넘친 폭을 좌우로 균등 분배하는데 scrollLeft 는 음수가 될 수
// 없어서 «왼쪽 오버플로에 도달할 방법이 없다». safe 는 넘칠 때만 시작
// 정렬로 전환한다.
export const opsOuter: CSSProperties = {
  padding: '40px 32px 80px',
  display: 'flex',
  justifyContent: 'safe center',
  overflowX: 'auto',
  background: '#DDE1E6',
  minHeight: '100vh',
}

// 카드. `flex: none` 이 없으면 flex 아이템이 축소되어 1000px 이 유지되지
// 않는다(폭이 줄면 고정 5열이 작업 열을 짜부순다).
export const opsCard: CSSProperties = {
  width: OPS_WIDTH,
  flex: 'none',
  background: C.bg,
  borderRadius: '20px',
  boxShadow: '0 24px 60px -30px rgba(13,43,69,.42)',
  overflow: 'hidden',
  fontFamily: "'Pretendard', system-ui, sans-serif",
  wordBreak: 'keep-all',
  overflowWrap: 'break-word',
}

export const opsHeader: CSSProperties = {
  background: C.navy,
  color: C.white,
  padding: '26px 32px',
}

export const opsBody: CSSProperties = {
  padding: '24px 32px 36px',
}

// ---- 탭 --------------------------------------------------------------

export const opsTabList: CSSProperties = {
  display: 'flex',
  gap: '4px',
  background: C.white,
  padding: '0 32px',
  borderBottom: `1px solid ${C.border}`,
}

export const opsTabBtn: CSSProperties = {
  minHeight: '52px',
  padding: '0 18px',
  fontFamily: 'inherit',
  fontSize: '17px',
  letterSpacing: '-.015em',
  cursor: 'pointer',
  background: 'none',
  borderTop: 'none',
  borderLeft: 'none',
  borderRight: 'none',
  borderBottom: '3px solid transparent',
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
}

// 활성/비활성 탭의 색. Ops.tsx 의 인라인 spread 자리에 그대로 넣는다.
export function opsTabState(selected: boolean): CSSProperties {
  return {
    borderBottomColor: selected ? C.tealText : 'transparent',
    color: selected ? C.tealText : C.body,
    fontWeight: selected ? 800 : 600,
  }
}

// 탭 옆 개수 배지.
export function opsTabCount(selected: boolean): CSSProperties {
  return {
    background: selected ? C.tealText : '#E4EAE9',
    color: selected ? C.white : C.body,
    borderRadius: '20px',
    padding: '2px 9px',
    fontSize: '13px',
    fontWeight: 700,
  }
}

// ---- 폼 --------------------------------------------------------------

// 입력. 소스는 0.5rem 패딩에 높이 지정이 없어서 실측 34px 였다 — 터치
// 타깃 미달이다. 50px 로 올렸다.
export const opsInput: CSSProperties = {
  width: '100%',
  minHeight: '50px',
  boxSizing: 'border-box',
  border: `1.5px solid ${C.border}`,
  borderRadius: '11px',
  padding: '13px 14px',
  fontFamily: 'inherit',
  fontSize: '16.5px',
  color: C.navy,
  background: C.bg,
  outline: 'none',
}

// 질문 카드(fieldset). 소스는 1px #ddd 였다 — 흰 배경 위에서 거의 안 보인다.
// 흰 카드 + 그림자로 바꿔 "카드 묶음"이 읽히게 했다.
export const opsCardStyle: CSSProperties = {
  border: 'none',
  borderRadius: '16px',
  padding: '20px 22px',
  margin: 0,
  // fieldset 은 기본 min-width: min-content 라 그리드 안에서 안 줄어든다.
  minWidth: 0,
  background: C.white,
  boxShadow: SHADOW_CARD,
}

// fieldset 안의 <legend>.
//
// 브라우저는 legend 자리에 «테두리 노치»를 파낸다. opsSectionNavy 처럼
// borderTop 이 있으면 그 4px 선이 legend 앞뒤에서 끊겨 이상한 모양이 된다.
// `float: left; width: 100%` 가 legend 를 일반 블록처럼 만들어 노치를
// 없애는 표준 우회법이다. 뒤따르는 내용이 float 를 물지 않도록 부모에서
// clear 하는 대신, legend 자체에 아래 여백을 주고 다음 형제에 clear 를
// 걸지 않아도 되게 padding-top 으로 흐름을 정리한다.
export const opsLegend: CSSProperties = {
  float: 'left',
  width: '100%',
  padding: 0,
  fontSize: '18px',
  fontWeight: 800,
  color: C.navy,
  letterSpacing: '-.02em',
  lineHeight: 1.45,
  marginBottom: '8px',
}

// legend 가 float 되면 다음 형제가 같은 줄로 올라온다. fieldset 의 첫
// 컨텐츠 래퍼에 이걸 씌워 흐름을 끊는다.
export const opsAfterLegend: CSSProperties = {
  clear: 'both',
}

// 섹션 상단 액센트. 본인 정보=네이비, 비상 연락처=민트. 두 섹션이 색으로
// 구분되어 "어디까지가 본인 정보인지"가 보인다.
export const opsSectionNavy: CSSProperties = {
  ...opsCardStyle,
  borderTop: `4px solid ${C.navy}`,
}
export const opsSectionMint: CSSProperties = {
  ...opsCardStyle,
  borderTop: `4px solid ${C.mint}`,
}

// legend / 질문 문장.
export const opsPrompt: CSSProperties = {
  fontSize: '18px',
  fontWeight: 800,
  color: C.navy,
  letterSpacing: '-.02em',
  lineHeight: 1.45,
  marginBottom: '6px',
}

// 질문 아래 설명 한 줄. 소스는 0.85rem(≈13.6px) #555 였다 — 이 화면의
// 본문 하한(15px)에 미달이었다.
export const opsHint: CSSProperties = {
  fontSize: '15px',
  lineHeight: 1.55,
  color: C.body,
  margin: '0 0 13px',
  textWrap: 'pretty',
}

// 2열 질문 그리드.
export const opsGrid2: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: '14px',
}

// 3열(비상 연락처 이름·연락처·관계).
export const opsGrid3: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr 1fr',
  gap: '16px',
}

// 섹션 라벨.
//
// ⚠️ 여기에 FONT_MONO + letterSpacing .14em 을 쓰면 안 된다. IBM Plex Mono
// 에는 한글 글리프가 없어서 폰트는 폴백되고 «자간만 남는다» — "일 곱 가 지
// 질 문" 처럼 글자가 벌어져 깨진 것처럼 보인다. 모노+넓은 자간은 라틴
// 문자·숫자 라벨(예: SETTINGS, LV.4)에만 쓴다.
export const opsSectionLabel: CSSProperties = {
  fontSize: '13px',
  fontWeight: 700,
  letterSpacing: '-.005em',
  color: C.tealText,
  margin: '28px 0 14px',
}

// ---- 버튼 -------------------------------------------------------------
//
// 위계: primary=틸 채움(등록하기), outline=흰 배경+틸 테두리(세부 정보),
// danger=흰 배경+붉은 테두리(삭제), disabled=회색 채움.
type BtnRank = 'primary' | 'outline' | 'danger' | 'safe'

// 작업 열 전용 버튼 기반. 표의 가장 오른쪽 칸에 들어가는 버튼(세부 정보·
// 알림 보내기·폰 미연결·결과 미확인·발송 중·삭제)은 폭이 좁아 글자가 두 줄로
// 접히면 세로로 길어지고 가로도 낭비된다. 줄바꿈을 막고, 여백과 글자 크기를
// 한 단계 줄인다. 터치 타깃 하한(44px)은 유지한다.
export const opsActionBtnBase: CSSProperties = {
  minHeight: '44px',
  padding: '10px 10px',
  fontFamily: 'inherit',
  fontSize: '14px',
  fontWeight: 800,
  letterSpacing: '-.015em',
  borderRadius: '11px',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: '6px',
  whiteSpace: 'nowrap',
}

export function opsBtn(rank: BtnRank, disabled = false): CSSProperties {
  const base: CSSProperties = {
    minHeight: '48px',
    padding: '12px 14px',
    fontFamily: 'inherit',
    fontSize: '15.5px',
    fontWeight: 800,
    letterSpacing: '-.015em',
    borderRadius: '12px',
    cursor: disabled ? 'not-allowed' : 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '7px',
    whiteSpace: 'nowrap',
  }
  if (disabled) {
    return {
      ...base,
      background: '#E4EAE9',
      color: '#5B6673',
      border: 'none',
    }
  }
  if (rank === 'primary') {
    return {
      ...base,
      background: C.tealText,
      color: C.white,
      border: 'none',
      boxShadow: '0 12px 28px -12px rgba(11,110,105,.5)',
    }
  }
  if (rank === 'safe') {
    return { ...base, background: C.safe, color: C.white, border: 'none' }
  }
  if (rank === 'danger') {
    return {
      ...base,
      background: C.white,
      color: C.alertDeep,
      border: `1.5px solid ${C.alertBorder}`,
    }
  }
  return {
    ...base,
    background: C.white,
    color: C.tealText,
    // 아우트라인 테두리는 흰 카드 위에서 3:1 이상이어야 한다(WCAG 1.4.11).
    // 연틸 계열로는 못 맞춘다.
    border: `1.5px solid ${C.tealText}`,
  }
}

// 제출 버튼(전체 폭, 62px).
export const opsSubmitBtn: CSSProperties = {
  ...opsBtn('primary'),
  width: '100%',
  minHeight: '62px',
  marginTop: '22px',
  fontSize: '19px',
  letterSpacing: '-.02em',
  borderRadius: '15px',
}

// ---- 표 --------------------------------------------------------------

// 가로 스크롤 래퍼. 표가 카드보다 넓어질 때만 스크롤이 생긴다.
export const opsTableScroll: CSSProperties = {
  overflowX: 'auto',
  borderRadius: '16px',
  boxShadow: SHADOW_CARD,
}

export const opsTableInner: CSSProperties = {
  background: C.white,
  borderRadius: '16px',
  overflow: 'hidden',
  minWidth: OPS_TABLE_MIN_WIDTH,
}

// 헤더 행. 소스의 th 는 0.9rem·회색 하단선이었다 — 네이비 밴드로 바꿔
// 헤더와 본문이 확실히 갈린다.
export const opsTh: CSSProperties = {
  padding: '15px 16px',
  fontSize: '14px',
  fontWeight: 700,
  letterSpacing: '-.01em',
  color: C.white,
  background: C.navy,
  textAlign: 'left',
}

// 데이터 셀. 0.9rem(≈14.4px) → 15~16px.
export const opsTd: CSSProperties = {
  padding: '16px',
  fontSize: '15px',
  color: C.body,
  borderBottom: '1px solid #E4EAE9',
  verticalAlign: 'top',
}

// 이름 셀만 강조 — 담당자가 행을 찾는 기준이다.
export const opsTdName: CSSProperties = {
  ...opsTd,
  fontSize: '16px',
  fontWeight: 700,
  color: C.navy,
}

// 연락처·시각은 모노. 숫자 열을 세로로 훑을 수 있다.
// `whiteSpace: nowrap` 으로 시각이 `20:38:2`/`9` 처럼 글자 단위로 쪼개지는
// 것을 막는다 — 접히면 한눈에 못 읽는다. 연락처 열(150px)·시각 열(116px)이
// nowrap 기준으로 폭을 잡았으므로 같은 줄에 들어온다.
export const opsTdMono: CSSProperties = {
  ...opsTd,
  fontFamily: FONT_MONO,
  whiteSpace: 'nowrap',
}

// 폰 연결 배지.
export function opsTokenBadge(hasToken: boolean): CSSProperties {
  return {
    display: 'inline-block',
    background: hasToken ? '#E4F3EC' : '#F2F4F7',
    color: hasToken ? '#0B5B45' : '#5B6673',
    border: `1px solid ${hasToken ? C.safe : '#C6CDD6'}`,
    borderRadius: '20px',
    padding: '5px 11px',
    fontSize: '13.5px',
    fontWeight: 700,
  }
}

// 발송 상태 텍스트 색.
//
// 'unconfirmed' 를 «주의 노랑»으로 따로 뺀 것이 중요하다. 이 상태는 실패가
// 아니다 — 브라우저가 요청을 끊었을 뿐 서버는 이미 보냈을 수 있다. 붉게
// 하면 운영자가 "안 갔구나" 하고 다시 보내려 하는데, 그게 정확히 막아야
// 하는 행동이다. 회색으로 하면 not_sent 와 구분이 안 된다.
export function opsSendColor(state: string): string {
  if (state === 'sent') return '#0B5B45'
  if (state === 'failed') return C.alertDeep
  if (state === 'unconfirmed') return C.warnText
  return C.body
}

// 'unconfirmed' 행의 발송 버튼. 잠긴 버튼이지만 «회색 죽은 버튼»이 아니라
// 주의 톤이어야 한다 — 토큰 없음(발송 불가)과 결과 미확인(재발송 금지)은
// 원인이 다르고, 운영자가 해야 할 일도 다르다(전자는 QR 스캔, 후자는
// 새로고침).
export const opsBtnUnconfirmed: CSSProperties = {
  minHeight: '48px',
  padding: '12px 14px',
  fontFamily: 'inherit',
  fontSize: '15.5px',
  fontWeight: 800,
  letterSpacing: '-.015em',
  borderRadius: '12px',
  cursor: 'not-allowed',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: '7px',
  whiteSpace: 'nowrap',
  background: C.warnBg,
  color: C.warnText,
  border: `1.5px solid ${C.warn}`,
}

// 「건강·장애·생활 정보는 저장하지 않아…」 안내. 소스는 0.8rem(≈12.8px)
// 이었는데, 이건 «개인정보 최소수집이라는 약속이 지켜졌다는 증거»다.
// 각주 크기로 두면 그 사실이 전달되지 않는다. 15px + 좌측 바로 올렸다.
export const opsNotStoredNote: CSSProperties = {
  margin: '0 0 12px',
  fontSize: '15px',
  lineHeight: 1.6,
  letterSpacing: '-.012em',
  color: C.warnText,
  background: C.warnBg,
  borderLeft: `4px solid ${C.warn}`,
  borderRadius: '0 10px 10px 0',
  padding: '12px 14px',
  textWrap: 'pretty',
}

// 「미저장」 값 자체의 표시. 실제 값과 시각적으로 달라야 한다 — 중립
// 기본값을 사실처럼 보여주면 운영자가 잘못 판단한다(예: 계단 불가자를
// 가능으로 읽는다).
export const opsNotStoredValue: CSSProperties = {
  fontSize: '14.5px',
  fontStyle: 'italic',
  color: C.tertiary,
}

// 세부 정보 <dl> 2열 그리드. 소스 구조(max-content 1fr)를 유지한다.
export const opsDetailList: CSSProperties = {
  margin: '0',
  display: 'grid',
  gridTemplateColumns: 'max-content 1fr',
  columnGap: '20px',
  rowGap: '9px',
  fontSize: '14.5px',
  lineHeight: 1.55,
}

export const opsDetailKey: CSSProperties = {
  fontWeight: 700,
  color: C.body,
}

export const opsDetailVal: CSSProperties = {
  color: C.navy,
  margin: 0,
}

// <summary> 토글. 44 → 52px.
export const opsSummary: CSSProperties = {
  cursor: 'pointer',
  minHeight: '52px',
  display: 'flex',
  alignItems: 'center',
  fontSize: '15.5px',
  fontWeight: 700,
  color: C.tealText,
  letterSpacing: '-.015em',
}

// 행 펼침(세부 정보) 영역의 «바깥 상자»만 담당한다. 안쪽 2열 그리드는
// opsDetailList 다 — 소스의 <dl> 구조를 그대로 두기 위해 분리했다.
export const opsRowDetail: CSSProperties = {
  background: C.bg,
  borderTop: '1px solid #E4EAE9',
  padding: '18px 20px',
}

// ---- QR 패널 ----------------------------------------------------------

export const opsQrWrapper: CSSProperties = {
  background: C.white,
  borderRadius: '16px',
  padding: '22px 24px',
  marginBottom: '20px',
  display: 'flex',
  gap: '24px',
  alignItems: 'center',
  flexWrap: 'wrap',
  boxShadow: SHADOW_CARD,
  border: 'none',
}

// QR 캔버스를 감싸는 네이비 액자. 흰 여백(quiet zone)이 확보되어 스캔이
// 안정적이다.
export const opsQrFrame: CSSProperties = {
  width: '170px',
  height: '170px',
  background: C.navy,
  borderRadius: '12px',
  padding: '10px',
  flex: 'none',
}

// ---- 토스트 -----------------------------------------------------------

export function opsToast(ok: boolean): CSSProperties {
  return {
    margin: '20px 32px 0',
    background: ok ? '#E4F3EC' : C.alertBg,
    border: `1.5px solid ${ok ? C.safe : C.alert}`,
    borderRadius: '14px',
    padding: '16px 18px',
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    fontSize: '16.5px',
    fontWeight: 700,
    color: ok ? '#0B5B45' : C.alertText,
    letterSpacing: '-.015em',
  }
}

// ---- 삭제 확인 다이얼로그 ---------------------------------------------

export const opsDialogBackdrop: CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(13,43,69,.55)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1100,
  padding: '24px',
}

export const opsDialogCard: CSSProperties = {
  background: C.white,
  borderRadius: '18px',
  padding: '26px 28px',
  maxWidth: '440px',
  width: '100%',
  borderTop: `5px solid ${C.alert}`,
}

// ---- 세부 정보 다이얼로그 ---------------------------------------------
//
// 행 단위 세부 정보를 넓게 보여주는 팝업. 삭제 확인 모달보다 넓고 안에서
// 스크롤된다 — 세부 정보 항목(사는 곳·주거·이동·시력·청력·언어·독거·돌봄·
// 비상 연락처·동의)이 표의 좁은 마지막 열에 다 들어가지 않기 때문이다.
// 화면 밖으로 넘치지 않도록 maxHeight: 80vh 와 내부 overflowY: auto 를 줬다.

export const opsRowDetailDialogCard: CSSProperties = {
  background: C.white,
  borderRadius: '18px',
  maxWidth: '620px',
  width: '100%',
  maxHeight: '80vh',
  display: 'flex',
  flexDirection: 'column',
  borderTop: `5px solid ${C.tealText}`,
  overflow: 'hidden',
}

export const opsRowDetailDialogHeader: CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '16px',
  padding: '22px 26px 14px',
  borderBottom: `1px solid #E4EAE9`,
}

export const opsRowDetailDialogTitle: CSSProperties = {
  margin: 0,
  fontSize: '19px',
  fontWeight: 800,
  letterSpacing: '-.02em',
  color: C.navy,
}

// 닫기 버튼. 터치 타깃 48px 이상.
export const opsRowDetailDialogCloseBtn: CSSProperties = {
  minHeight: '48px',
  minWidth: '72px',
  padding: '12px 18px',
  fontFamily: 'inherit',
  fontSize: '16px',
  fontWeight: 800,
  letterSpacing: '-.015em',
  borderRadius: '12px',
  cursor: 'pointer',
  background: C.white,
  color: C.tealText,
  border: `1.5px solid ${C.tealText}`,
  flex: 'none',
}

// 본문 영역. 내용이 길면 이 영역 안에서 스크롤된다 — 팝업 전체가 아니라
// 본문만 스크롤되므로 헤더(제목·닫기)는 항상 보인다.
export const opsRowDetailDialogBody: CSSProperties = {
  overflowY: 'auto',
  padding: '0 26px 26px',
}
