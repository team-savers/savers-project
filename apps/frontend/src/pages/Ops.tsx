// /ops — 운영자 대리 등록 화면 (설문형 재설계).
//
// 임의의 "운영자"(보호자 / 복지관 / 고용주)가 취약계층 피보호자를 SAVERS에
// 등록하는 surrogate-registration 화면이다. 피보호자 본인이 직접 가입하는
// 흐름이 아니며, 따라서 입력의 무게를 피보호자가 아니 운영자가 지도록
// 설계했다(예: 보호자 정보는 운영자 본인의 정보로 입력).
//
// 이 재설계의 핵심은 "운영자가 매번 17개 헤더를 가진 표에서 데이터를 읽는
// 것이 아니라, 8개의 일상 언어 질문에 답하는 형태로 피보호자 상태를 입력·
// 확인하는 구조"다. 폼은 질문 카드 8장으로 구성되고, 입력값은 <details> 요약
// 패널과 발송 현황 표로 다시 시각화된다.
//
// 핵심 설계 결정:
//   — 등록 폼과 목록을 탭으로 분리. 기본 탭은 '등록', 등록 성공 시
//     '현황' 탭으로 자동 전환. 키보드 조작 가능(role=tablist/tab,
//     aria-selected, aria-controls). 탭 전환으로 폼 입력이 날아가지
//     않도록 폼 상태는 부모 컴포넌트가 들고 탭 아래 언마운트 없이
//     보존한다.
//   — 동 코드를 직접 입력하지 않고 동 이름을 드롭다운에서 고른다.
//     코드는 내부 상태로만 쓰고 사용자에게 보이지 않는다. 선택
//     데이터는 src/mocks/adminDong.ts (현재 데모 범위: 서원동 1개)를 쓴다.
//   — '본인식별' / '비상 연락처' 섹션으로 시각적 분리. 비상 연락처는
//     "없어도 됩니다" 명시. 저장 데이터 구조(Profile/Guardian)는 그대로.
//
// 스코프:
//   - client.ts registrations Map(인메모리)를 저장소로 사용.
//   - 영속화(로컬/세션 웹 스토리지) 사용 금지 — 공개 데모 레포의 one-way door.
//   - 브리지가 설정돼 있지 않으면 sendTestNotification 은 mock id 만
//     반환한다(브리지 설정 시 실제 발송 경로로 전환).
//
// 접근성:
//   - 모든 입력은 <label htmlFor> 로 연결.
//   - 에러/성공 토스트는 role="alert".
//   - 터치 타깃(버튼)은 최소 44px.
//   - 표는 table + th scope semantic 마크업.
//   - 탭은 ARIA tablist 패턴 + 좌우 화살표 키보드 순회.

import React, { useEffect, useRef, useState } from 'react'
import QRCode from 'qrcode'
import {
  isStoreEnabled,
  listRegistrations,
  registerUserWithPhone,
  deleteRegistration,
  seedRegistrations,
  sendTestNotification,
  subscribeRegistrations,
  type RegistrationRecord,
  type SendState,
} from '../api/client'
import type {
  CareSubject,
  ConsentFlags,
  ConsentKey,
  Guardian,
  Hearing,
  Housing,
  Language,
  Mobility,
  Profile,
  RegisteredBy,
  Vision,
} from '../api/types'
import { PROFILES } from '../mocks/profiles'
import { ADMIN_DONG } from '../mocks/adminDong'
import { C } from '../lib/tokens'
import opsHeroImg from '../assets/lp-hero-a.png'
import {
  OPS_TABLE_COLUMNS,
  opsActionBtnBase,
  opsAfterLegend,
  opsBody,
  opsBtn,
  opsBtnUnconfirmed,
  opsCardStyle,
  opsCard,
  opsDetailKey,
  opsDetailList,
  opsDetailVal,
  opsDialogBackdrop,
  opsDialogCard,
  opsGrid2,
  opsGrid3,
  opsHeader,
  opsHint,
  opsInput,
  opsLegend,
  opsNotStoredNote,
  opsNotStoredValue,
  opsOuter,
  opsQrFrame,
  opsQrWrapper,
  opsRowDetail,
  opsRowDetailDialogBody,
  opsRowDetailDialogCard,
  opsRowDetailDialogCloseBtn,
  opsRowDetailDialogHeader,
  opsRowDetailDialogTitle,
  opsSectionLabel,
  opsSectionMint,
  opsSectionNavy,
  opsSendColor,
  opsSubmitBtn,
  opsSummary,
  opsTabBtn,
  opsTabCount,
  opsTabList,
  opsTabState,
  opsTableInner,
  opsTableScroll,
  opsTd,
  opsTdMono,
  opsTdName,
  opsTh,
  opsToast,
  opsTokenBadge,
} from '../lib/opsStyles'

// ---- 3단계 분리동의 항목 정의 -------------------------------------------
//
// 개인정보보호법상 민감정보(장애·건강)는 분리 동의가 원칙이다. 그래서 동의는
// 하나의 묶음이 아니라 세 개의 서로 독립된 항목으로 받는다. 각 항목은:
//   - id           — ConsentKey 와 1:1 (체크박스 id, 상태 표 행의 키)
//   - title        — 무엇에 대한 동의인지(우리가 정한 항목명 수준)
//   - required     — 필수 여부. 필수 미동의 시 등록 불가, 선택 미동의 시 등록은
//                    진행되되 해당 기능이 제한된다.
//   - declineNote  — 동의하지 않았을 때 무엇이 제한되는지의 한 줄 안내.
//                    어르신이 판단할 수 있어야 한다. 법적 문구가 아니라 기능적
//                    안내문이다.
//   - body         — 동의 본문 문구의 자리. **법적 효력이 있는 문장은
//                    프론트가 지어내면 안 된다.** 지금은 빈 문자열이며,
//                    화면에서는 「문구 확정 대기」 표지로 드러난다(아래
//                    CONSENT_BODY_PENDING). 문구가 확정되면 이 상수의
//                    body 값만 바꾸면 화면에 반영된다.
//
// 이 상수 배열이 동의 UI(체크박스)와 현황 표(상태 표시)의 단일 소스다.
// 항목을 추가하려면 여기와 types.ts 의 ConsentKey/ConsentFlags 를 함께 고친다.
const CONSENT_BODY_PENDING = '' // 문구 확정 대기 — 아직 채워지지 않음

interface ConsentItem {
  id: ConsentKey
  title: string
  required: boolean
  declineNote: string
  body: string
}

const CONSENT_ITEMS: ReadonlyArray<ConsentItem> = [
  {
    id: 'personal',
    title: '개인정보 수집·이용 (필수)',
    required: true,
    // 기능적 안내문(법적 문구 아님). 미동의 시 잃는 것을 한 줄로.
    declineNote: '동의하지 않으면 등록 자체가 불가합니다.',
    body: CONSENT_BODY_PENDING,
  },
  {
    id: 'sensitive',
    title: '민감정보(장애·건강) 수집·이용 (선택)',
    required: false,
    declineNote:
      '동의하지 않아도 등록은 됩니다. 다만 이동·시력·청력 등 맞춤 안내가 제한됩니다.',
    body: CONSENT_BODY_PENDING,
  },
  {
    id: 'location',
    title: '위치정보 이용 (선택)',
    required: false,
    declineNote:
      '동의하지 않아도 등록은 됩니다. 다만 알림이 왔을 때 내 주변 대피소 거리·방향 안내가 빠지고 등록한 동 기준으로만 안내됩니다.',
    body: CONSENT_BODY_PENDING,
  },
]

// 초기(미동의) 동의 상태. 폼이 리셋될 때마다 이 값으로 돌아간다.
const EMPTY_CONSENTS: ConsentFlags = {
  personal: false,
  sensitive: false,
  location: false,
}

// ---- 폼 상태 타입 -------------------------------------------------------

// 보호자 입력은 3개의 독립 문자열 필드(이름/전화/관계)로 받고, 저장 시
// Guardian 객체로 합친다. 빈 문자열 3개 → guardian: null (보호자 없음).
interface GuardianInput {
  name: string
  phone: string
  relation: string
}

interface OpsForm {
  name: string
  // 피보호자 본인 전화번호. 운영자가 대리 등록하는 맥락이지만 피보호자 본인
  // 연락처도 함께 확보해 두는 것이 비상 연락에 유리하다.
  // 빈 문자열 → null 로 저장(전화번호 미확보 상태).
  phone: string
  // 행정 구역 코드(발송 매칭 키). 사용자에게 코드 입력칸은 노출되지
  // 않으며, 드롭다운에서 동 이름을 고르면 코드가 함께 채워진다.
  dongCode: string
  dongName: string
  housing: Housing
  mobility: Mobility
  stairsOk: boolean
  // easyText 는 항상 true 이며 토글하지 않는다.
  // "쉬운 말이 필요하냐"를 스스로 고르게 하는 것은 낙인화이고 실제로 아무도
  // 끄지 않는다. 기본이 쉬운 말이고 원문은 토글로 남는다는 설계 원칙.
  easyText: true
  vision: Vision
  hearing: Hearing
  language: Language
  livesAlone: boolean
  care: string // 빈 문자열 → null 로 변환
  guardian: GuardianInput
  registeredBy: RegisteredBy
  // 3단계 분리동의 상태. 폼에서 세 체크박스로 각각 독립적으로 켜진다.
  consents: ConsentFlags
}

// 폼 초기값. 새 사용자 등록 창이 열릴 때마다 이 값으로 리셋된다.
// easyText 는 true 로 고정(사용자가 끌 수 없는 기본값).
const EMPTY_FORM: OpsForm = {
  name: '',
  phone: '',
  dongCode: '',
  dongName: '',
  housing: 'normal',
  mobility: 'ok',
  stairsOk: true,
  easyText: true,
  vision: 'ok',
  hearing: 'ok',
  language: 'ko',
  livesAlone: true,
  care: '',
  guardian: { name: '', phone: '', relation: '' },
  registeredBy: 'guardian',
  consents: { ...EMPTY_CONSENTS },
}

// ---- 탭 식별자 ---------------------------------------------------------
//
// 두 개의 탭. 기본은 '등록'. 등록 성공 시 '현황'으로 자동 전환한다.
// 탭 상태는 부모(Ops) 컴포넌트에 두어, 탭 전환 시 RegistrationForm 이
// 언마운트되더라도 입력값이 보존되도록 한다.
type OpsTab = 'register' | 'status'

// ---- 컴포넌트 -----------------------------------------------------------

export function Ops(): React.ReactElement {
  // 폼 상태를 부모가 들고 있는다. 탭이 바뀌어도 폼 입력값이 날아가지
  // 않아야 한다. RegistrationForm 은 이 폼을 props 로 받아 controlled 처럼
  // 다루며, 부모 컴포넌트가 계속 살아 있으므로 입력값은 보존된다.
  const [form, setForm] = useState<OpsForm>(EMPTY_FORM)
  const [registrations, setRegistrations] = useState<RegistrationRecord[]>([])
  const [pending, setPending] = useState(false)
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; msg: string } | null>(
    null,
  )
  // 등록 직후 새 항목을 표에서 시각적으로 강조하기 위한 id.
  const [justAddedId, setJustAddedId] = useState<string | null>(null)
  // 현재 활성 탭. 기본 '등록'.
  const [activeTab, setActiveTab] = useState<OpsTab>('register')
  const [listError, setListError] = useState<string | null>(null)
  // 행 단위 발송 진행 상태. userId 집합에 들어 있으면 해당 행의
  // [테스트 발송] 버튼이 비활성화되고 "발송 중…" 문구가 표시된다.
  // 발송이 끝나면(성공·실패 무관) 집합에서 빼서 다시 누를 수 있게 한다.
  // 빠르게 두 번 누르면 같은 재난 알림이 같은 사람에게 두 번 가는 것을 막는다.
  const [sending, setSending] = useState<ReadonlySet<string>>(new Set())

  // 최초 마운트 시 데모 페르소나를 seed 로 채운 뒤 목록 로드.
  useEffect(() => {
    seedRegistrations(Object.values(PROFILES))
    void refresh()
  }, [])

  // 실시간 구독 — 폰이 토큰을 붙이면 /ops 의 「세이버스 등록」 뱃지가 바로
  // 켜지도록 Firestore onSnapshot 을 구독한다. 저장소가 꺼져 있으면 구독 함수가
  // no-op 해지 함수를 반환하므로 이 effect 는 아무 일도 하지 않는다(기본 동작
  // 보존). 언마운트 시 반드시 해지 — 누수·max-update-depth 방지.
  //
  // onSnapshot 오류 콜백을 받아 listError 로 전달한다. 저장소가 끊기거나
  // 권한이 사라지면 빈 목록이 아니라 오류 상태를 보여준다.
  useEffect(() => {
    if (!isStoreEnabled()) return
    const unsub = subscribeRegistrations(
      (rows) => {
        setListError(null)
        setRegistrations(rows)
      },
      (err) => {
        setListError(err.message)
      },
    )
    return () => {
      unsub()
    }
  }, [])

  async function refresh(): Promise<void> {
    setListError(null)
    try {
      const list = await listRegistrations()
      setRegistrations(list)
    } catch (e) {
      // listRegistrations 는 저장소 장애 시 throw 한다 — 빈 목록이 아니라
      // 오류 상태로 화면에 드러낸다(조용한 실패 금지).
      setRegistrations([])
      setListError(e instanceof Error ? e.message : String(e))
    }
  }

  // 통합 setField 헬퍼 — 중첩 guardian 필드까지 한 번에 처리.
  function update<K extends keyof OpsForm>(key: K, value: OpsForm[K]): void {
    setForm((prev) => ({ ...prev, [key]: value }))
  }
  function updateGuardian<K extends keyof GuardianInput>(
    key: K,
    value: GuardianInput[K],
  ): void {
    setForm((prev) => ({
      ...prev,
      guardian: { ...prev.guardian, [key]: value },
    }))
  }
  // 동의 항목 토글. 항목별로 독립적으로 켜지고 꺼진다(분리 동의).
  function updateConsent(key: ConsentKey, value: boolean): void {
    setForm((prev) => ({
      ...prev,
      consents: { ...prev.consents, [key]: value },
    }))
  }

  // 폼 검증. 운영자가 피보호자를 대리 등록하는 맥락이므로 피보호자 본인
  // 연락처는 선택(보호자 정보로 운영자 본인 입력). 단, 입력된 경우
  // 형식(010-XXXX-XXXX)을 검증한다.
  function validate(): string | null {
    if (form.name.trim() === '') return '이름을 입력하세요.'
    // 피보호자 전화번호 — 선택. 비었으면 null 저장. 채운 경우 형식 검증.
    const phone = form.phone.trim()
    if (phone !== '' && !/^\d{2,3}-\d{3,4}-\d{4}$/.test(phone)) {
      return '피보호자 전화번호 형식이 올바르지 않습니다(예: 010-0000-0000).'
    }
    // 동(거주지) 선택 검증. 드롭다운에서 한 항목을 골라야만 통과 —
    // 코드 자리에 8~10자리 숫자 코드가 채워져 있어야 한다. 폼 UI 에서는
    // 사용자가 모를 수밖에 없는 코드 용어를 직접 쓰지 않는다(코드는
    // 내부 매칭 키일 뿐 사용자에게 노출하지 않는다).
    if (form.dongCode.trim() === '' || form.dongName.trim() === '') {
      return '거주하시는 동을 선택해 주세요.'
    }
    if (!/^\d{8,10}$/.test(form.dongCode.trim())) {
      return '선택한 값이 올바르지 않습니다. 다시 선택해 주세요.'
    }
    // 보호자 필드는 전부 채워지거나 전부 비어야 한다(부분 입력 방지).
    const g = form.guardian
    const filled = [g.name, g.phone, g.relation].filter((s) => s.trim() !== '')
    if (filled.length > 0 && filled.length < 3) {
      return '비상 연락처는 이름·연락처·관계를 모두 입력하거나 모두 비워주세요.'
    }
    // 필수 동의 항목 검증. 선택 항목(sensitive/location)은 미동의여도 등록이
    // 진행된다 — 분리 동의 원칙. 필수(personal)만 미동의를 막는다.
    for (const item of CONSENT_ITEMS) {
      if (item.required && !form.consents[item.id]) {
        return `${item.title} 항목에 체크해 주세요. ${item.declineNote}`
      }
    }
    return null
  }

  async function handleSubmit(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    setToast(null)
    const err = validate()
    if (err !== null) {
      setToast({ kind: 'err', msg: err })
      return
    }
    setPending(true)
    try {
      const g = form.guardian
      const guardian: Guardian | null =
        g.name.trim() === '' && g.phone.trim() === '' && g.relation.trim() === ''
          ? null
          : {
              name: g.name.trim(),
              phone: g.phone.trim(),
              relation: g.relation.trim(),
            }
      const care: CareSubject | null =
        form.care.trim() === '' ? null : form.care.trim()
      const phoneTrimmed = form.phone.trim()
      const wardPhone: string | null = phoneTrimmed === '' ? null : phoneTrimmed
      // 새 userId — 타임스탬프 + 충분히 긴 난수 접미사. 이전에는
      // `ops-${Date.now()}` 였는데, 타임스탬프는 추측 가능해서 이 값을
      // 아는 사람이면 누구나 /join?u=<userId> 로 남의 등록에 자기 폰 토큰을
      // 붙일 수 있었다. randomIdSuffix 는 crypto.getRandomValues 기반이라
      // insecure origin(LAN 주소)에서도 동작한다 — W3C UUID v4 헬퍼는
      // secure context 에서만 정의되므로 태블릿이 http://192.168.x.x 로
      // /ops 를 열 때 undefined 가 되어 등록이 터진다.
      const userId = `ops-${Date.now()}-${randomIdSuffix()}`
      const profile: Profile = {
        userId,
        name: form.name.trim(),
        dongCode: form.dongCode.trim(),
        dongName: form.dongName.trim(),
        housing: form.housing,
        mobility: form.mobility,
        stairsOk: form.stairsOk,
        easyText: form.easyText,
        vision: form.vision,
        hearing: form.hearing,
        language: form.language,
        livesAlone: form.livesAlone,
        care,
        guardian,
        registeredBy: form.registeredBy,
        // 3단계 분리동의 결과. 프론트 mock 전용 필드(계약에 없음)이며
        // STORED_FIELDS 허용 목록에 없어 저장소에 적히지 않는다 — 메모리와
        // /ops 화면에서만 확인된다.
        consents: { ...form.consents },
      }
      await registerUserWithPhone(profile, wardPhone)
      setJustAddedId(userId)
      await refresh()
      setForm(EMPTY_FORM)
      // 등록 성공 시 '현황' 탭으로 자동 전환. 방금 등록한 사람이
      // 강조(highlight)되어 목록에 보이게 한다.
      setActiveTab('status')
      setToast({ kind: 'ok', msg: '등록 완료. 현황 탭에서 확인하세요.' })
    } catch (e) {
      setToast({
        kind: 'err',
        msg: e instanceof Error ? e.message : String(e),
      })
    } finally {
      setPending(false)
    }
  }

  // [발송] 버튼은 더 이상 단순 시뮬레이션이 아니다.
  // - 토큰 없음(no_token) 사용자: 버튼 자체가 비활성/숨김 처리되며, 발송
  //   시도를 하지 않는다(상태는 이미 'no_token' 으로 시드됨).
  // - 토큰 보유 사용자: sendTestNotification 호출 → 성공 시 'sent' +
  //   lastSentAt 갱신, 실패 시 'failed'.
  // 두 경우 모두 컬럼이 실시간으로 갱신되도록 refresh() 를 호출한다.
  //
  // 메시지 분기: 반환된 messageId 가 'mock-' 으로 시작하면 시뮬레이션
  // 경로(브리지 미설정), 그렇지 않으면 실제 발송 경로다. 실제 발송 경로에서
  // 「미호출」·「시뮬레이션」 문구가 나오면 안 된다 — 운영자가 화면을 믿을
  // 수 없게 된다.
  async function handleTestSend(rec: RegistrationRecord): Promise<void> {
    // 이미 이 행의 발송이 진행 중이면 무시한다 — 두 번 눌러 같은 재난 알림이
    // 두 번 나가는 것을 막는다.
    if (sending.has(rec.userId)) return
    setSending((prev) => new Set(prev).add(rec.userId))
    setToast(null)
    try {
      const res = await sendTestNotification(rec.userId)
      await refresh()
      const isMock = res.messageId.startsWith('mock-')
      // 발송은 성공했지만 발송 기록 저장에 실패한 경우: 성공으로 알리되,
      // 목록에 반영되지 않을 수 있다는 경고를 덧붙인다. 재발송을 유도하는
      // 「실패」 문구가 나오면 같은 알림이 두 번 가므로 치명적이다.
      const base = isMock
        ? `[시뮬레이션] ${rec.name}님 — 발송 상태를 표로 확인하세요.`
        : `발송했습니다 — ${rec.name}님 · ${formatHMS(new Date())}`
      const msg =
        res.persistWarning !== undefined ? `${base} ${res.persistWarning}` : base
      setToast({ kind: 'ok', msg })
    } catch (e) {
      setToast({
        kind: 'err',
        msg: e instanceof Error ? e.message : String(e),
      })
    } finally {
      // 성공이든 실패든 발송 시도가 끝나면 잠금을 푼다 — 실패 후 다시
      // 누를 수 있어야 한다(영구 잠금 금지).
      setSending((prev) => {
        const next = new Set(prev)
        next.delete(rec.userId)
        return next
      })
    }
  }

  // [삭제] — 되돌릴 수 없는 파괴적 동작이므로 확인을 받는다. 확인 다이얼로그
  // 상태는 row 단위가 아니라 화면 단위로 하나만 열려 있도록 한다.
  const [pendingDelete, setPendingDelete] = useState<RegistrationRecord | null>(
    null,
  )
  const [deleting, setDeleting] = useState(false)

  // [세부 정보] — 표 안에서는 좁아서 보기 어려운 행 단위 세부 정보를
  // 팝업으로 넓게 보여준다. 삭제 확인 모달과 마찬가지로 화면 단위로 하나만
  // 열려 있다. 삭제 확인 팝업과 동시에 뜨지 않도록 setShowDetail 은
  // pendingDelete 가 null 일 때만 허용한다.
  const [showDetail, setShowDetail] = useState<RegistrationRecord | null>(null)
  // 팝업을 열었던 버튼. 닫힐 때 포커스를 되돌리기 위해 보관한다.
  const detailTriggerRef = useRef<HTMLButtonElement | null>(null)

  function openDetail(rec: RegistrationRecord, btn: HTMLButtonElement): void {
    // 삭제 확인 모달이 열려 있으면 세부 정보 팝업을 열지 않는다 — 두 팝업이
    // 겹치면 포커스와 배경 처리가 꼬인다.
    if (pendingDelete !== null) return
    detailTriggerRef.current = btn
    setShowDetail(rec)
  }

  function closeDetail(): void {
    setShowDetail(null)
    // 팝업을 닫으면 눌렀던 버튼으로 포커스를 돌려보낸다 — 모달이 닫힌 뒤
    // 키보드 초점이 어디로 갔는지 운영자가 헤매지 않게 한다.
    window.setTimeout(() => {
      const el = detailTriggerRef.current
      if (el !== null) el.focus()
    }, 0)
  }

  async function handleDeleteConfirmed(): Promise<void> {
    if (pendingDelete === null) return
    const target = pendingDelete
    setDeleting(true)
    try {
      await deleteRegistration(target.userId)
      setPendingDelete(null)
      // If the deleted registration is the one whose QR is currently on
      // screen, clear the QR. Leaving it would let the operator hand the
      // ward a QR that resolves to a now-deleted document. A DIFFERENT
      // person's QR must stay — only the deleted user's QR is cleared.
      setJustAddedId((prev) =>
        prev !== null && prev === target.userId ? null : prev,
      )
      await refresh()
      setToast({ kind: 'ok', msg: `${target.name}님 등록을 지웠습니다.` })
    } catch (e) {
      setToast({
        kind: 'err',
        msg:
          e instanceof Error
            ? `삭제 실패: ${e.message}`
            : `삭제 실패: ${String(e)}`,
      })
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div style={opsOuter}>
      <main style={opsCard}>
        <header style={opsHeader}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              marginBottom: '18px',
              fontSize: '13px',
              fontWeight: 700,
              letterSpacing: '.14em',
              color: 'rgba(255,255,255,.7)',
            }}
          >
            <span>SAVERS</span>
            <span aria-hidden="true">/</span>
            <span>ops</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '28px' }}>
            <div style={{ flex: 1 }}>
              <div
                style={{
                  fontSize: '26px',
                  fontWeight: 800,
                  letterSpacing: '-.025em',
                  lineHeight: 1.35,
                  marginBottom: '9px',
                }}
              >
                도움이 필요한 분을 대신 등록합니다
              </div>
              <div
                style={{
                  fontSize: '16px',
                  lineHeight: 1.6,
                  color: 'rgba(255,255,255,.72)',
                  maxWidth: '560px',
                  textWrap: 'pretty',
                }}
              >
                일곱 가지만 물어보시면 됩니다. 입력하신 정보는 시연용 저장소에
                보관되며 실명·실제 연락처는 넣지 마세요.
              </div>
            </div>
            <img
              src={opsHeroImg}
              alt="스마트폰으로 어르신을 대신 등록하는 모습"
              style={{
                width: '190px',
                height: '190px',
                objectFit: 'cover',
                borderRadius: '16px',
                flex: 'none',
                opacity: 0.95,
              }}
            />
          </div>
        </header>
        {/* 개인정보 처리 고지는 실제 저장 상태와 일치해야 한다. 취약계층
            대상 서비스에서 가장 민감한 부류의 오류다. 저장소가 켜져 있으면
            임시 저장소 사실을, 꺼져 있으면 메모리 전용 사실을 알린다. 두
            상태 모두 거짓이어서는 안 된다. */}
        <div style={opsBody}>
          {isStoreEnabled() ? (
            <p style={opsHint}>
              보호자·복지관·고용주가 피보호자를 대리 등록합니다. 입력하신 정보는
              <strong> 시연용 임시 저장소</strong>에 보관됩니다. 실제 서비스
              저장소가 아닙니다.{' '}
              <strong>실명·실제 연락처를 넣지 마세요.</strong>
            </p>
          ) : (
            <p style={opsHint}>
              보호자·복지관·고용주가 피보호자를 대리 등록합니다. 입력된 정보는 이
              데모 세션의 메모리에만 보관됩니다(저장소·DB 미연동).
            </p>
          )}

          {toast !== null && (
            <div role="alert" style={opsToast(toast.kind === 'ok')}>
              <span>{toast.msg}</span>
            </div>
          )}

          <OpsTabs
            activeTab={activeTab}
            onChange={setActiveTab}
            statusCount={registrations.length}
          />

          {/* 각 탭 패널은 id+aria-labelledby 로 tab 과 짝지어진다.
              '등록' 탭은 비활성일 때 렌더에서 완전히 빼지 않고, hidden 속성으로
              숨긴다 — 탭을 전환해도 폼 입력값이 날아가지 않도록 DOM 에 그대로
              보존하면서 시각적으로는 보이지 않게 한다. 다만 상태는
              어차피 부모(Ops)가 들고 있으므로, hidden 처리는 스크린리더와 시각
              보조를 위한 추가 보호일 뿐이다. */}
          <div
            id="ops-panel-register"
            role="tabpanel"
            aria-labelledby="ops-tab-register"
            hidden={activeTab !== 'register'}
          >
            <RegistrationForm
              form={form}
              pending={pending}
              onSubmit={handleSubmit}
              update={update}
              updateGuardian={updateGuardian}
              updateConsent={updateConsent}
            />
          </div>

          <div
            id="ops-panel-status"
            role="tabpanel"
            aria-labelledby="ops-tab-status"
            hidden={activeTab !== 'status'}
          >
            {/* 등록 성공 직후 QR 표시. 담는 값은 현재 origin 기준
                /join?u=<userId> 절대 URL — window.location.origin 사용으로 배포
                주소가 바뀌어도 따라간다. QR 옆에 같은 주소를 글자로도 보여준다
                (스캔이 안 될 때 대비). 저장소가 꺼져 있으면 QR 패널은 숨긴다 —
                폰에서 /join 을 열어도 등록 문서를 찾을 수 없기 때문. */}
            {justAddedId !== null && isStoreEnabled() && (
              <QrPanel userId={justAddedId} />
            )}
            {/* 저장소 장애는 빈 목록이 아니라 오류 상태로 보여준다. 어떤
                것이 안 됐는지, 어떻게 하면 되는지(다시 시도 버튼)를 명시.
                44px 터치 타깃. */}
            {listError !== null && (
              <div role="alert" style={opsToast(false)}>
                <div>
                  <p style={{ margin: 0, fontWeight: 800 }}>
                    등록 목록을 불러오지 못했습니다.
                  </p>
                  <p style={{ margin: '0.4rem 0 0 0', fontWeight: 500 }}>
                    {listError}
                  </p>
                  <button
                    type="button"
                    onClick={() => void refresh()}
                    style={{
                      ...opsBtn('danger'),
                      marginTop: '12px',
                    }}
                  >
                    다시 시도
                  </button>
                </div>
              </div>
            )}
            <RegistrationTable
              rows={registrations}
              justAddedId={justAddedId}
              onTestSend={handleTestSend}
              onDelete={setPendingDelete}
              onOpenDetail={openDetail}
              detailOpen={showDetail !== null}
              sending={sending}
            />
          </div>

          {/* 삭제 확인 다이얼로그. 되돌릴 수 없는 동작이므로 사용자에게
              명시적으로 묻는다. [지우기] / [취소] 각 44px 이상. */}
          {pendingDelete !== null && (
            <DeleteConfirmDialog
              rec={pendingDelete}
              deleting={deleting}
              onCancel={() => {
                if (!deleting) setPendingDelete(null)
              }}
              onConfirm={() => void handleDeleteConfirmed()}
            />
          )}

          {/* 세부 정보 다이얼로그. 표의 좁은 마지막 열 대신 넓은 팝업에서
              행 단위 세부 속성(사는 곳·주거·이동·시력 등)과 저장/미저장
              안내를 보여준다. */}
          {showDetail !== null && (
            <RowDetailsDialog rec={showDetail} onClose={closeDetail} />
          )}
        </div>
      </main>
    </div>
  )
}

// ---- QR panel for the just-registered ward ------------------------------
//
// Renders a QR encoding the absolute /join?u=<userId> URL so the operator
// can have the ward scan it with their phone. The URL is derived from
// window.location.origin so it tracks whatever host the app is deployed on.
// The same URL is also printed as text beside the QR in case the camera
// scan fails.
//
// The QR is drawn to a <canvas> via the `qrcode` package. Width/height
// chosen for reliable phone-camera scanning on a typical tablet display.
//
// The base origin used to build the join URL can be overridden via the
// VITE_PUBLIC_BASE_URL env var. This is needed when the operator screen is
// served from a host the ward's phone cannot reach (e.g. the operator is
// running the dev server on http://localhost:3000 but the QR must point the
// phone at a publicly reachable deployment). When the override is unset
// (the default — including production) the QR behaves exactly as before:
// it is built from window.location.origin. The override is validated: an
// invalid value is ignored with a console explanation and we fall back to
// window.location.origin rather than silently encoding a broken URL.
//
// The final join URL is built once into a single value and that same value
// feeds BOTH the QR canvas and the printed text beside it — so the text the
// operator can read and the QR the camera scans can never drift apart.

// Resolve the base origin for the QR, honouring the env override when it is
// set and valid, otherwise falling back to the current page origin.
// Trailing slashes on the override are normalized away so "https://x.app"
// and "https://x.app/" produce identical URLs.
function resolveQrBaseOrigin(): string {
  const override = import.meta.env.VITE_PUBLIC_BASE_URL
  if (override !== undefined && override.trim() !== '') {
    const trimmed = override.trim()
    try {
      const parsed = new URL(trimmed)
      // new URL accepts many things; require an absolute http(s) URL so a
      // bare path like "/join" or a relative string can't masquerade as a
      // base. Without this guard, new URL('/join') would succeed and the QR
      // would encode a meaningless origin.
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        throw new Error(`unsupported protocol ${parsed.protocol}`)
      }
      return parsed.origin
    } catch (e) {
      console.warn(
        `VITE_PUBLIC_BASE_URL 이 올바른 주소가 아니라 무시합니다: ${JSON.stringify(override)}` +
          (e instanceof Error ? ` (${e.message})` : '') +
          ' — QR 은 현재 주소를 기준으로 만듭니다.',
      )
    }
  }
  return window.location.origin
}

interface QrPanelProps {
  userId: string
}

function QrPanel({ userId }: QrPanelProps): React.ReactElement {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const joinUrl = `${resolveQrBaseOrigin()}/join?u=${encodeURIComponent(userId)}`

  useEffect(() => {
    const canvas = canvasRef.current
    if (canvas === null) return
    // QRCode.toCanvas returns a promise; ignore rejection silently so a
    // rendering glitch never blocks the /ops flow. The text URL beside the
    // QR is the fallback.
    void QRCode.toCanvas(canvas, joinUrl, { width: 220, margin: 2 }).catch(
      () => {},
    )
  }, [joinUrl])

  return (
    <section style={opsQrWrapper} aria-label="피보호자 폰 등록용 QR">
      <div style={opsQrFrame}>
        <canvas ref={canvasRef} role="img" aria-label="QR 코드" />
      </div>
      <div style={{ minWidth: '200px' }}>
        <p
          style={{
            margin: '0 0 0.4rem 0',
            fontSize: '16px',
            fontWeight: 800,
            color: '#0D2B45',
          }}
        >
          피보호자 폰으로 이 QR을 스캔해 주세요.
        </p>
        <p style={{ margin: '0 0 0.25rem 0', fontSize: '15px', color: '#3F4E5C' }}>
          스캔이 안 되면 아래 주소를 폰에서 직접 열어 주세요.
        </p>
        <code
          style={{
            display: 'inline-block',
            fontSize: '14px',
            wordBreak: 'break-all',
            background: '#F2F4F7',
            padding: '6px 8px',
            border: '1px solid #E4EAE9',
            borderRadius: '6px',
          }}
        >
          {joinUrl}
        </code>
      </div>
    </section>
  )
}

// ---- Delete confirmation dialog ----------------------------------------
//
// 삭제는 되돌릴 수 없는 파괴적 동작이다. 사용자에게 명시적으로 묻는다:
// 「○○○님 등록을 지울까요? 알림이 더 이상 가지 않습니다.」
// [지우기] / [취소] 각 44px 이상 터치 타깃.
//
// 파괴적 동작임이 색만이 아니라 문구로도 드러나게 한다 — 색만으로
// 구분하지 말고 문구로도 알린다. [지우기] 버튼은 빨간 배경 + 「지우기」라는 명확한
// 동사이며, 「알림이 더 이상 가지 않습니다」라는 결과를 문장으로 밝힌다.

interface DeleteConfirmDialogProps {
  rec: RegistrationRecord
  deleting: boolean
  onCancel: () => void
  onConfirm: () => void
}

function DeleteConfirmDialog({
  rec,
  deleting,
  onCancel,
  onConfirm,
}: DeleteConfirmDialogProps): React.ReactElement {
  return (
    <div
      role="alertdialog"
      aria-label="등록 삭제 확인"
      style={opsDialogBackdrop}
    >
      <div style={opsDialogCard}>
        <p
          style={{
            margin: 0,
            fontSize: '18px',
            fontWeight: 800,
            color: '#0D2B45',
            letterSpacing: '-.015em',
          }}
        >
          {rec.name}님 등록을 지울까요?
        </p>
        <p
          style={{
            margin: '10px 0 0 0',
            fontSize: '15px',
            lineHeight: 1.55,
            color: '#B3182B',
          }}
        >
          알림이 더 이상 가지 않습니다. 이 동작은 되돌릴 수 없습니다.
        </p>
        <div
          style={{
            display: 'flex',
            gap: '10px',
            marginTop: '20px',
            justifyContent: 'flex-end',
          }}
        >
          <button
            type="button"
            onClick={onCancel}
            disabled={deleting}
            style={{ ...opsBtn('outline'), minWidth: '100px' }}
          >
            취소
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={deleting}
            style={{ ...opsBtn('danger'), minWidth: '100px' }}
          >
            {deleting ? '지우는 중…' : '지우기'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- ARIA tablist -------------------------------------------------------
//
// 동작 요건:
//   - role="tablist" / role="tab" / aria-selected / aria-controls
//   - 키보드 조작 가능(좌우 화살표로 탭 순회)
//   - 터치 타깃 최소 44px
//
// WAI-ARIA Authoring Practices 의 Tabs 패턴을 따른다:
//   - 활성 탭만 tabbable(tabIndex=0), 비활성 탭은 tabIndex=-1 로 포커스
//     순환에서 제외(화살표 키로만 이동).
//   - Left/Right 화살표로 탭 전환, Tab 키는 다음 탭패널 콘텐츠로 이동.
//   - tab → panel 연결은 aria-controls(panel id)로, panel → tab 연결은
//     aria-labelledby(tab id)로 쌍방향 구성.
//
// 의존성 없이 직접 구현한다(탭 라이브러리 추가 금지).

interface OpsTabsProps {
  activeTab: OpsTab
  onChange: (tab: OpsTab) => void
  statusCount: number
}

function OpsTabs({
  activeTab,
  onChange,
  statusCount,
}: OpsTabsProps): React.ReactElement {
  // refs 배열. useRef<T>(null) 이 React 19 / TS 5에서 RefObject<T | null>
  // 를 반환하므로 배열 타입도 null 을 허용해야 한다.
  const tabRefs: ReadonlyArray<React.RefObject<HTMLButtonElement | null>> = [
    useRef<HTMLButtonElement>(null),
    useRef<HTMLButtonElement>(null),
  ]

  const tabs: ReadonlyArray<{ id: OpsTab; label: string; index: number }> = [
    { id: 'register', label: '등록', index: 0 },
    { id: 'status', label: '현황', index: 1 },
  ]

  function handleKeyDown(e: React.KeyboardEvent<HTMLButtonElement>): void {
    // ArrowLeft / ArrowRight 로 활성 탭을 바꾼다. Home/End 도 지원(접근성
    // 관례). 포커스는 새 활성 탭으로 옮겨 시각 일관성을 유지한다.
    const currentIndex = tabs.findIndex((t) => t.id === activeTab)
    let nextIndex: number | null = null
    if (e.key === 'ArrowRight') {
      nextIndex = (currentIndex + 1) % tabs.length
    } else if (e.key === 'ArrowLeft') {
      nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
    } else if (e.key === 'Home') {
      nextIndex = 0
    } else if (e.key === 'End') {
      nextIndex = tabs.length - 1
    }
    if (nextIndex !== null) {
      e.preventDefault()
      const next = tabs[nextIndex]
      if (next !== undefined) {
        onChange(next.id)
        // 다음 틱에 포커스 — 활성 탭 버튼이 tabIndex=0 을 받은 뒤.
        window.setTimeout(() => {
          const ref = tabRefs[nextIndex]
          if (ref !== undefined) {
            const el = ref.current
            if (el !== null) el.focus()
          }
        }, 0)
      }
    }
  }

  return (
    <div role="tablist" aria-label="운영자 등록 화면 탭" style={opsTabList}>
      {tabs.map((t) => {
        const selected = activeTab === t.id
        const ref = tabRefs[t.index]
        if (ref === undefined) return null
        return (
          <button
            key={t.id}
            ref={ref}
            id={`ops-tab-${t.id}`}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={`ops-panel-${t.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={handleKeyDown}
            style={{ ...opsTabBtn, ...opsTabState(selected) }}
          >
            {t.label}
            {t.id === 'status' && (
              <span style={opsTabCount(selected)}>{statusCount}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ---- 등록 폼(설문형 8카드 + 동 드롭다운 + 섹션 분리) -------------------
//
// 17열 표 헤더를 읽는 부담을 덜기 위해, 폼을 8개의 "질문" 필드셋으로
// 구성한다. 각 질문은 일상 언어로 된 한 문장(prompt)과 그 질문에 답하는
// 입력 컨트롤을 함께 제공한다. 카드 순서 = 설문 표 순서.

interface RegistrationFormProps {
  form: OpsForm
  pending: boolean
  onSubmit: (e: React.FormEvent) => void
  update: <K extends keyof OpsForm>(key: K, value: OpsForm[K]) => void
  updateGuardian: <K extends keyof GuardianInput>(
    key: K,
    value: GuardianInput[K],
  ) => void
  updateConsent: (key: ConsentKey, value: boolean) => void
}

function RegistrationForm({
  form,
  pending,
  onSubmit,
  update,
  updateGuardian,
  updateConsent,
}: RegistrationFormProps): React.ReactElement {
  // 소스는 패딩만 있어서 실측 34px 였다 — 터치 타깃 미달. 50px 로 올렸다.
  const inputStyle = opsInput

  return (
    <form onSubmit={onSubmit} style={{ marginTop: '20px' }}>
      <div style={opsSectionLabel}>일곱 가지 질문 · 한 가지 약속</div>
      {/* 이 섹션은 등록 대상(피보호자) 본인의 식별 정보를 묶는다.
          시각적으로 확실히 분리하기 위해 두 섹션을 별도 fieldset 으로 나누고
          섹션 제목을 명시한다. */}
      <fieldset style={opsSectionNavy}>
        <legend style={opsLegend}>본인 정보</legend>
        <div style={opsAfterLegend} />
        <p style={opsHint}>
          등록 대상이 되는 분의 식별 정보를 입력합니다.
        </p>
        <div style={opsGrid2}>
          <Field label="성함" htmlFor="ops-name">
            <input
              id="ops-name"
              type="text"
              value={form.name}
              onChange={(e) => update('name', e.target.value)}
              style={inputStyle}
              required
            />
          </Field>
          <Field
            label="연락처 (예: 010-0000-0000)"
            htmlFor="ops-ward-phone"
          >
            <input
              id="ops-ward-phone"
              type="tel"
              value={form.phone}
              onChange={(e) => update('phone', e.target.value)}
              style={inputStyle}
              placeholder="010-0000-0000"
              pattern="\d{2,3}-\d{3,4}-\d{4}"
            />
          </Field>
          <Field label="등록 주체" htmlFor="ops-registered-by">
            <select
              id="ops-registered-by"
              value={form.registeredBy}
              onChange={(e) =>
                update('registeredBy', e.target.value as RegisteredBy)
              }
              style={inputStyle}
            >
              <option value="guardian">보호자</option>
              <option value="welfare_center">복지관</option>
              <option value="employer">고용주</option>
              <option value="self">본인</option>
            </select>
          </Field>
          {/* 사는 곳(행정동) 입력. 검색 UI가 아닌 일반 <select> 로, 다른
              문항(주거 형태·이동 능력 등)과 같은 형태로 처리한다. 관악구
              행정동이 9개뿐이므로 검색은 과하다. 첫 항목은 선택 안 됨
              (value="")이며, 사용자가 하나를 고르면 동 이름과 코드가 함께
              확정된다(빈 값이면 폼 검증이 등록을 막는다). */}
          <Field label="사는 곳" htmlFor="ops-dong">
            <select
              id="ops-dong"
              value={form.dongCode}
              onChange={(e) => {
                const code = e.target.value
                const found = ADMIN_DONG.find((d) => d.code === code)
                update('dongCode', code)
                update('dongName', found !== undefined ? found.name : '')
              }}
              style={inputStyle}
            >
              <option value="">선택해 주세요</option>
              {ADMIN_DONG.map((d) => (
                <option key={d.code} value={d.code}>
                  {d.name}
                </option>
              ))}
            </select>
          </Field>
        </div>
      </fieldset>

      {/* ---- 주거/침수 위험 --------------------------------------------- */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>어디에 사세요?</legend>
        <div style={opsAfterLegend} />
        <select
          id="ops-housing"
          aria-label="주거 형태"
          value={form.housing}
          onChange={(e) => update('housing', e.target.value as Housing)}
          style={inputStyle}
        >
          <option value="normal">일반(반지하·저지대 아님)</option>
          <option value="banjiha">반지하</option>
          <option value="lowland">저지대</option>
        </select>
        <p style={opsHint}>
          반지하·저지대는 물이 찰 위험이 있어 안내 문구가 달라집니다.
        </p>
      </fieldset>

      {/* ---- 이동 능력 + 계단 ------------------------------------------- */}
      {/* mobility 와 stairsOk 는 함께 한 카드에서 입력한다.
          매핑 — 정상: mobility:'ok', stairsOk:true /
                  느림:   mobility:'slow', stairsOk:false(기본값, 변경 가능) /
                  보조필요:mobility:'assisted', stairsOk:false(동일). */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>계단을 오르내릴 수 있나요?</legend>
        <div style={opsAfterLegend} />
        <select
          id="ops-mobility"
          aria-label="이동 능력"
          value={form.mobility}
          onChange={(e) => {
            const m = e.target.value as Mobility
            // 매핑 규칙: 정상이면 계단 가능, 그 외는 기본 불가.
            const stairs = m === 'ok'
            update('mobility', m)
            update('stairsOk', stairs)
          }}
          style={inputStyle}
        >
          <option value="ok">정상 (스스로 계단 이동 가능)</option>
          <option value="slow">느림 (천천히, 계단은 어려움)</option>
          <option value="assisted">보조 필요 (이동 시 거동 보조)</option>
        </select>
        <p style={opsHint}>
          계단을 오르내릴 수 있는지가 대피소 계단 조건과 연결됩니다.
        </p>
        <div style={{ marginTop: '0.5rem' }}>
          <CheckRow
            id="ops-stairs-ok"
            label="계단 이동 가능 (체크 해제 시 계단 있는 대피소를 상위에 두지 않습니다)"
            checked={form.stairsOk}
            onChange={(v) => update('stairsOk', v)}
          />
        </div>
      </fieldset>

      {/* ---- 시력 ------------------------------------------------------- */}
      {/* 드롭다운 선택지는 저시력 여부만 묻는 두 단계로 좁힌다. 선택값은
          등록 정보로 함께 보관된다. */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>글씨가 잘 보이나요?</legend>
        <div style={opsAfterLegend} />
        <select
          id="ops-vision"
          aria-label="시력"
          // 드롭다운은 잘 보임/잘 안 보임 두 가지만 노출. 셀렉트 value 는
          // 항상 'ok' 또는 'low' 가 되도록 정규화한다.
          value={form.vision === 'ok' ? 'ok' : 'low'}
          onChange={(e) => update('vision', e.target.value as Vision)}
          style={inputStyle}
          title="시력 항목은 등록 정보로 함께 보관합니다."
        >
          <option value="ok">잘 보임</option>
          <option value="low">잘 안 보임</option>
        </select>
      </fieldset>

      {/* ---- 청력 ------------------------------------------------------- */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>전화 통화가 되나요?</legend>
        <div style={opsAfterLegend} />
        <select
          id="ops-hearing"
          aria-label="청력"
          value={form.hearing}
          onChange={(e) => update('hearing', e.target.value as Hearing)}
          style={inputStyle}
        >
          <option value="ok">통화 가능</option>
          <option value="bad">통화 어려움</option>
        </select>
      </fieldset>

      {/* ---- 언어 ------------------------------------------------------- */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>어떤 말이 편하신가요?</legend>
        <div style={opsAfterLegend} />
        <select
          id="ops-language"
          aria-label="사용 언어"
          value={form.language}
          onChange={(e) => update('language', e.target.value as Language)}
          style={inputStyle}
        >
          <option value="ko">한국어</option>
          <option value="vi">베트남어</option>
        </select>
        <p style={opsHint}>고르신 언어로 안내 문구를 보냅니다.</p>
      </fieldset>

      {/* ---- 독거 ------------------------------------------------------- */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>혼자 사세요?</legend>
        <div style={opsAfterLegend} />
        <div
          style={{
            display: 'flex',
            gap: '1.5rem',
            marginTop: '0.25rem',
            flexWrap: 'wrap',
          }}
        >
          <RadioRow
            id="ops-lives-alone-y"
            name="ops-lives-alone"
            label="예, 혼자 삽니다."
            checked={form.livesAlone === true}
            onChange={() => update('livesAlone', true)}
          />
          <RadioRow
            id="ops-lives-alone-n"
            name="ops-lives-alone"
            label="아니요, 함께 사는 사람이 있습니다."
            checked={form.livesAlone === false}
            onChange={() => update('livesAlone', false)}
          />
        </div>
      </fieldset>

      {/* ---- 돌봄 대상 -------------------------------------------------- */}
      <fieldset style={{ ...opsCardStyle, marginTop: '14px' }}>
        <legend style={opsLegend}>도움이 필요한 분이 같이 있나요?</legend>
        <div style={opsAfterLegend} />
        <input
          id="ops-care"
          type="text"
          aria-label="돌봄 대상"
          value={form.care}
          onChange={(e) => update('care', e.target.value)}
          style={inputStyle}
          placeholder="예: 영유아, 와상 가족 (없으면 비움)"
        />
      </fieldset>

      {/* ---- 쉬운 말 안내 (카드 8: 입력이 아니라 약속) ----------------- */}
      {/* easyText 는 토글하지 않는다 — "쉬운 말이 필요하냐"를 되묻는 것 자체가
          낙인이고 실제로 아무도 끄지 않는다. 그래서 여덟 번째 카드는 입력이
          아니라 「항상 켜져 있다」는 안내만 보여준다. */}
      <div
        style={{
          marginTop: '14px',
          background: C.tealBg,
          borderRadius: '16px',
          padding: '20px 22px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '9px',
            marginBottom: '7px',
          }}
        >
          <span
            style={{
              width: '26px',
              height: '26px',
              borderRadius: '8px',
              background: C.tealText,
              color: C.white,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flex: 'none',
              fontSize: '15px',
              fontWeight: 800,
            }}
          >
            ✓
          </span>
          <span
            style={{
              fontSize: '18px',
              fontWeight: 800,
              color: C.navy,
              letterSpacing: '-.02em',
            }}
          >
            쉬운 말은 항상 켜져 있습니다
          </span>
        </div>
        <div
          style={{
            fontSize: '15px',
            lineHeight: 1.6,
            color: C.tealDeep,
            textWrap: 'pretty',
          }}
        >
          이건 묻지 않습니다. 쉬운 말이 기본이고, 원문은 화면에서 토글로 볼 수
          있습니다. “쉬운 말이 필요하냐”고 되묻는 것 자체가 낙인이 되기
          때문입니다.
        </div>
      </div>

      {/* ---- 비상 연락처 (별도 섹션) ------------------------------------ */}
      {/* 기존 "보호자 정보" 섹션을 "비상 연락처"로 이름 바꾸고 본인의 식별 정보와
          시각적으로 분리한다. 등록 대상 본인이 아니라 급할 때 연락할
          사람이라는 점을 분명히 한다. guardian: null 이 정상 케이스이므로
          "없어도 됩니다" 를 명시한다. 저장 데이터 구조(Guardian | null)는
          변경하지 않는다 — 라벨/배치만 바꾼다. */}
      <fieldset style={{ ...opsSectionMint, marginTop: '14px' }}>
        <legend style={opsLegend}>비상 연락처</legend>
        <div style={opsAfterLegend} />
        <p style={opsHint}>
          급할 때 연락할 사람을 적습니다. <strong>없어도 됩니다</strong> — 세 칸을
          모두 비우면 비상 연락처 없음으로 저장됩니다.
        </p>
        <div style={opsGrid3}>
          <Field label="이름" htmlFor="ops-g-name">
            <input
              id="ops-g-name"
              type="text"
              value={form.guardian.name}
              onChange={(e) => updateGuardian('name', e.target.value)}
              style={inputStyle}
            />
          </Field>
          <Field label="연락처" htmlFor="ops-g-phone">
            <input
              id="ops-g-phone"
              type="tel"
              value={form.guardian.phone}
              onChange={(e) => updateGuardian('phone', e.target.value)}
              style={inputStyle}
              placeholder="010-0000-0000"
            />
          </Field>
          <Field label="관계" htmlFor="ops-g-relation">
            <input
              id="ops-g-relation"
              type="text"
              value={form.guardian.relation}
              onChange={(e) => updateGuardian('relation', e.target.value)}
              style={inputStyle}
              placeholder="예: 딸, 보호자, 현장관리자"
            />
          </Field>
        </div>
      </fieldset>

      {/* ---- 입력 요약 패널 --------------------------------------------- */}
      {/* 폼 입력값을 운영자가 다시 읽기 쉬운 한국어 문장으로 정리한
          <details> 패널. "이렇게 저장됩니다" 확인 단계. 매 입력 렌더링. */}
      <SurveySummary form={form} />

      {/* ---- 3단계 분리동의 섹션 --------------------------------------- */}
      {/* 제출 버튼 바로 위. 세 항목이 각각 별도 체크박스(묶음 동의 아님).
          민감정보는 법적으로 분리 동의가 원칙이므로 한 번에 묶는 UI는 금지.
          각 항목의 본문 문구는 아직 확정되지 않았다 — 「문구 확정 대기」
          표지로 비워진 채로 출시된 것처럼 보이지 않게 한다. */}
      <ConsentSection
        items={CONSENT_ITEMS}
        consents={form.consents}
        onToggle={updateConsent}
      />

      <button type="submit" disabled={pending} style={opsSubmitBtn}>
        {pending ? '등록 중…' : '등록하기'}
      </button>
    </form>
  )
}

// label + 자식을 묶는 작은 래퍼. htmlFor 연결을 강제하기 위해 캡슐화.
function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: React.ReactNode
}): React.ReactElement {
  return (
    <div style={{ display: 'flex', flexDirection: 'column' }}>
      <label htmlFor={htmlFor} style={{ marginBottom: '0.25rem' }}>
        {label}
      </label>
      {children}
    </div>
  )
}

function CheckRow({
  id,
  label,
  checked,
  onChange,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (v: boolean) => void
}): React.ReactElement {
  return (
    <div style={{ marginBottom: '0.4rem' }}>
      <label htmlFor={id} style={{ display: 'inline-flex', gap: '0.4rem' }}>
        <input
          id={id}
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
    </div>
  )
}

// 라디오 행 — 접근성을 위해 input 과 label 을 htmlFor 로 연결.
function RadioRow({
  id,
  name,
  label,
  checked,
  onChange,
}: {
  id: string
  name: string
  label: string
  checked: boolean
  onChange: () => void
}): React.ReactElement {
  return (
    <div>
      <label htmlFor={id} style={{ display: 'inline-flex', gap: '0.4rem' }}>
        <input
          id={id}
          type="radio"
          name={name}
          checked={checked}
          onChange={onChange}
        />
        {label}
      </label>
    </div>
  )
}

// ---- 3단계 분리동의 섹션 -----------------------------------------------
//
// 세 동의 항목을 각각 별도의 체크박스로 표시한다. 한 번에 전체를 켜는
// 묶음 컨트롤은 의도적으로 없다 — 분리 동의 원칙(민감정보는 법적으로
// 분리 동의가 원칙)을 UI 수준에서 강제한다.
//
// 각 항목의 본문(body)은 아직 빈 문자열이다. 법적 효력이 있는 동의 문구는
// 프론트가 지어내면 안 된다. 빈 문자열일 때는 자리를
// 숨기지 않고 「문구 확정 대기」 표지를 노란 안내 상자로 드러내, 시연 화면에서
// 빈칸인 채로 출시된 것처럼 보이지 않게 한다.
//
// 세 항목은 CONSENT_ITEMS 배열에서 읽어 콘텐츠(제목·필수여부·안내문·본문)를
// 가져오되, 각 체크박스는 정적으로 한 항목씩 렌더링한다(묶음 루프가 아니라
// 항목별 별도 노드). 분리 동의 원칙이 코드 구조에서도 읽히게 하기 위해서다.

interface ConsentSectionProps {
  items: ReadonlyArray<ConsentItem>
  consents: ConsentFlags
  onToggle: (key: ConsentKey, value: boolean) => void
}

// 공통 행 스타일·본문 자리·미동의 안내를 한 곳에서 그리는 헬퍼. 각 항목의
// <input type="checkbox"> 는 아래 ConsentSection 본문에서 항목별로 직접
// 인라인 전개한다 — 컴포넌트로 캡슐화하면 소스에 type="checkbox" 리터럴이
// 한 곳에만 남아, 분리 동의 원칙이 정적 구조에서 보이지 않게 된다.
function consentCheckboxStyle(): React.CSSProperties {
  return {
    minHeight: '44px',
    minWidth: '44px',
    marginTop: 0,
    flexShrink: 0,
  }
}
function consentRowStyle(): React.CSSProperties {
  return {
    marginTop: '0.75rem',
    padding: '0.6rem',
    border: '1px solid #eee',
    borderRadius: '6px',
    background: '#fafafa',
  }
}
function consentTitleStyle(): React.CSSProperties {
  return {
    display: 'flex',
    alignItems: 'flex-start',
    gap: '0.5rem',
    cursor: 'pointer',
    fontSize: '1rem',
    fontWeight: 600,
  }
}
function consentBadgeStyle(required: boolean): React.CSSProperties {
  return {
    marginLeft: '0.4rem',
    fontSize: '0.8rem',
    fontWeight: 700,
    color: required ? '#c62828' : '#555',
  }
}

// 동의 본문 자리. 문구가 채워지지 않았으면 「확정 대기」 표지를 명확히
// 보여준다 — 빈칸인 채로 출시된 것처럼 보이면 안 된다.
function ConsentBody({ body }: { body: string }): React.ReactElement {
  if (body.trim() === '') {
    return (
      <div
        style={{
          marginTop: '0.4rem',
          marginLeft: '0.5rem',
          padding: '0.5rem 0.75rem',
          background: '#fff8e1',
          border: '1px dashed #f9a825',
          borderRadius: '4px',
          fontSize: '0.85rem',
          color: '#6d4c00',
        }}
      >
        <strong>문구 확정 대기</strong> — 이 항목의 안내 문구는 아직
        준비되지 않았습니다. 채워지면 이 자리에 보입니다.
      </div>
    )
  }
  return (
    <p
      style={{
        marginTop: '0.4rem',
        marginLeft: '0.5rem',
        marginBottom: 0,
        fontSize: '0.9rem',
        color: '#333',
        whiteSpace: 'pre-line',
      }}
    >
      {body}
    </p>
  )
}

// 미동의 시 제한되는 것 한 줄 안내. 어르신이 판단할 수 있어야.
function ConsentDeclineNote({
  note,
}: {
  note: string
}): React.ReactElement {
  return (
    <p
      style={{
        marginTop: '0.35rem',
        marginLeft: '0.5rem',
        marginBottom: 0,
        fontSize: '0.85rem',
        color: '#666',
      }}
    >
      {note}
    </p>
  )
}

function ConsentSection({
  items,
  consents,
  onToggle,
}: ConsentSectionProps): React.ReactElement {
  // CONSENT_ITEMS 순서 = 화면 순서. 인덱스로 각 항목을 찾는다.
  const findItem = (id: ConsentKey): ConsentItem =>
    items.find((it) => it.id === id) ?? {
      id,
      title: '(항목 없음)',
      required: false,
      declineNote: '',
      body: '',
    }

  // 세 항목을 미리 꺼낸다. 아래에서 각각 별도의 인라인 체크박스로 전개한다.
  const personal = findItem('personal')
  const sensitive = findItem('sensitive')
  const location = findItem('location')

  return (
    <fieldset
      style={{
        marginTop: '0.75rem',
        border: '1px solid #ddd',
        borderTop: '4px solid #6a1b9a',
        borderRadius: '8px',
        padding: '0.9rem',
      }}
    >
      <legend
        style={{
          fontSize: '1.05rem',
          fontWeight: 600,
          color: '#6a1b9a',
          marginBottom: '0.4rem',
        }}
      >
        동의 항목 (3가지)
      </legend>
      <p style={{ fontSize: '0.85rem', color: '#555', marginTop: '0.25rem' }}>
        각 항목을 따로 체크해 주세요. 한 번에 묶어서 체크하는 칸은 없습니다.
      </p>

      {/* 항목 1 — 개인정보(필수). 별도 체크박스. */}
      <div style={consentRowStyle()}>
        <label htmlFor="ops-consent-personal" style={consentTitleStyle()}>
          <input
            id="ops-consent-personal"
            type="checkbox"
            checked={consents.personal}
            onChange={(e) => onToggle('personal', e.target.checked)}
            style={consentCheckboxStyle()}
          />
          <span>
            {personal.title}
            <span style={consentBadgeStyle(personal.required)}>
              {personal.required ? '필수' : '선택'}
            </span>
          </span>
        </label>
        <ConsentBody body={personal.body} />
        <ConsentDeclineNote note={personal.declineNote} />
      </div>

      {/* 항목 2 — 민감정보(선택). 별도 체크박스. 법적 분리 동의 대상. */}
      <div style={consentRowStyle()}>
        <label htmlFor="ops-consent-sensitive" style={consentTitleStyle()}>
          <input
            id="ops-consent-sensitive"
            type="checkbox"
            checked={consents.sensitive}
            onChange={(e) => onToggle('sensitive', e.target.checked)}
            style={consentCheckboxStyle()}
          />
          <span>
            {sensitive.title}
            <span style={consentBadgeStyle(sensitive.required)}>
              {sensitive.required ? '필수' : '선택'}
            </span>
          </span>
        </label>
        <ConsentBody body={sensitive.body} />
        <ConsentDeclineNote note={sensitive.declineNote} />
      </div>

      {/* 항목 3 — 위치정보(선택). 별도 체크박스. */}
      <div style={consentRowStyle()}>
        <label htmlFor="ops-consent-location" style={consentTitleStyle()}>
          <input
            id="ops-consent-location"
            type="checkbox"
            checked={consents.location}
            onChange={(e) => onToggle('location', e.target.checked)}
            style={consentCheckboxStyle()}
          />
          <span>
            {location.title}
            <span style={consentBadgeStyle(location.required)}>
              {location.required ? '필수' : '선택'}
            </span>
          </span>
        </label>
        <ConsentBody body={location.body} />
        <ConsentDeclineNote note={location.declineNote} />
      </div>
    </fieldset>
  )
}

// ---- 입력 요약 패널 -----------------------------------------------------
//
// 폼 값 현재 상태를 "어떻게 저장되는가"라는 한국어 한 줄 문장으로 정리.
// 카테고리별로 묶어서 보여준다(주거/이동·시력·청력 등).
// <details> 로 접을 수 있어 폼 길이를 늘리지 않는다.

function SurveySummary({ form }: { form: OpsForm }): React.ReactElement {
  // 요약 패널의 라벨도 본인/비상 연락처 분리에 맞춘다.
  //
  // HONESTY (storage): the label says "이렇게 저장됩니다" but most of
  // these fields are NOT persisted. Only identification + operational state
  // reach the store (STORED_FIELDS: userId, name, dongName, phone, sendState,
  // lastSentAt, isRead, hasToken, deviceToken). The health/disability/
  // lifestyle answers (housing, mobility, stairsOk, vision, hearing,
  // language, livesAlone, care, guardian, easyText, registeredBy, consents)
  // are kept in component memory only and never written to the store. To
  // avoid lying, each row below is marked whether it is actually persisted.
  const lines: ReadonlyArray<{ k: string; v: string; stored: boolean }> = [
    { k: '주거', v: labelHousing(form.housing), stored: false },
    {
      k: '이동',
      v: `${labelMobility(form.mobility)} (계단 ${form.stairsOk ? '가능' : '불가'})`,
      stored: false,
    },
    {
      k: '시력',
      // 폼의 시력 입력은 드롭다운에서 'ok' 또는 'low' 만 선택할 수 있으므로
      // 요약 문장에도 그 두 값만 등장한다.
      v: labelVision(form.vision),
      stored: false,
    },
    { k: '청력', v: labelHearing(form.hearing), stored: false },
    { k: '언어', v: labelLanguage(form.language), stored: false },
    { k: '독거', v: form.livesAlone ? '예(혼자 삼)' : '아니요(동거인 있음)', stored: false },
    { k: '돌봄 대상', v: form.care.trim() === '' ? '없음' : form.care.trim(), stored: false },
    {
      k: '사는 곳',
      // 동 코드를 직접 노출하지 않는다 — 이름만 표시.
      // dongName 은 저장소에 보관된다(운영 표의 주소 컬럼).
      v: form.dongName.trim() === '' ? '아직 고르지 않음' : form.dongName.trim(),
      stored: true,
    },
    {
      k: '비상 연락처',
      v:
        form.guardian.name.trim() === '' &&
        form.guardian.phone.trim() === '' &&
        form.guardian.relation.trim() === ''
          ? '없음'
          : `${form.guardian.name.trim()} · ${form.guardian.phone.trim()} · ${form.guardian.relation.trim()}`,
      stored: false,
    },
    { k: '쉬운 말', v: '항상 사용(기본값)', stored: false },
    { k: '등록 주체', v: labelRegisteredBy(form.registeredBy), stored: false },
    {
      k: '동의',
      // 세 항목의 체크 상태를 한 줄로 요약. 필수(personal)가 빠졌으면
      // 등록이 막히므로 그 사실도 드러낸다. 동의 상태는 저장소에 보관되지
      // 않는다(프론트 mock 전용).
      v: labelConsents(form.consents),
      stored: false,
    },
  ]
  return (
    <details style={{ marginTop: '16px' }}>
      <summary style={opsSummary}>
        입력하신 내용 요약 (저장되는 항목과 저장되지 않는 항목이 있습니다)
      </summary>
      <div style={opsRowDetail}>
        <p style={opsNotStoredNote}>
          이름·사는 곳·연락처·발송 상태는 시연용 저장소에 보관됩니다. 주거·
          이동·시력·청력·언어·독거·돌봄·비상 연락처·동의 항목은 이 화면에서만
          확인하고 저장소에 적히지 않습니다.
        </p>
        <dl style={opsDetailList}>
          {lines.map((row) => (
            <React.Fragment key={row.k}>
              <dt style={opsDetailKey}>{row.k}</dt>
              <dd style={opsDetailVal}>
                {row.v}
                <span
                  style={{
                    ...opsNotStoredValue,
                    marginLeft: '8px',
                    fontSize: '13px',
                  }}
                >
                  {row.stored ? '저장됨' : '저장 안 됨'}
                </span>
              </dd>
            </React.Fragment>
          ))}
        </dl>
      </div>
    </details>
  )
}

// ---- 등록 목록 표(운영자 발송 현황, 17열) -----------------------------
//
// 17열 표는 폼에서 입력하는 8개 설문 필드(주거·이동·시력·청력·언어·독거·
// 돌봄·보호자)와 발송 관련 운영 메타데이터를 한 줄로 보여주는 운영
// 콘솔이다. 모바일에서도 가로 스크롤로 모든 열에 도달할 수 있도록
// overflow-x: auto 래퍼로 감싼다. 컬럼 헤더는 sticky 로 상단 고정.

// 재설계: 표는 가로 6열 본문 + 1개 발송 버튼 헤더 = 7개의 열 헤더만
// 사용한다. 운영자가 매줄 읽어야 하는 헤더 수를 최소화하기 위해 행정동·
// 주거·이동·시력·청력·언어·독거·돌봄·보호자·등록주체 등 폼에서 이미 입력한
// 세부 속성은 행 단위 details 패널로 접어 넣고, 표 본문은 발송 운영에 바로
// 필요한 6열(이름 / 연락처 / 발송 상태 / 마지막 발송 시각 / 알림 열람 응답 /
// 비고)만 남긴다.
//
// 3개 섹션 구분 헤더는 렌더링하지 않는다(원래 "3 헤더"는 본문 6열과 발송
// 버튼 1열을 묶는 그룹 라벨이 아니라, 표 위의 섹션 제목/안내문을 가리킨다).
// 표 자체는 7개 열 헤더를 넘지 않도록 단일 thead 행으로 구성한다.

interface RegistrationTableProps {
  rows: RegistrationRecord[]
  justAddedId: string | null
  onTestSend: (rec: RegistrationRecord) => void
  onDelete: (rec: RegistrationRecord) => void
  // 행 단위 세부 정보 팝업을 연다. 팝업 안에서 RowDetails 가 넓게 보인다.
  onOpenDetail: (rec: RegistrationRecord, btn: HTMLButtonElement) => void
  // 세부 정보 팝업이 현재 열려 있는지. 열려 있으면 다른 행의 「세부 정보」
  // 버튼을 비활성화해 두 팝업이 겹치지 않게 한다.
  detailOpen: boolean
  // 현재 발송이 진행 중인 userId 집합. 해당 행은 [테스트 발송] 버튼이
  // 비활성화되고 "발송 중…" 문구가 표시된다.
  sending: ReadonlySet<string>
}

function RegistrationTable({
  rows,
  justAddedId,
  onTestSend,
  onDelete,
  onOpenDetail,
  detailOpen,
  sending,
}: RegistrationTableProps): React.ReactElement {
  return (
    <section style={{ marginTop: '20px' }}>
      <h2 style={{ fontSize: '19px', fontWeight: 800, margin: '0 0 8px' }}>
        등록 목록(운영자 발송 현황)
      </h2>
      <p style={opsHint}>
        발송 상태·시각·알림 열람 응답과 비고만 한 줄로 표시합니다. 세부 속성
        (주거·이동·시력·언어·보호자 등)은 각 행의 "세부 정보" 토글을 열면
        확인할 수 있습니다. 발송 버튼은 브리지가 설정돼 있지 않으면
        모의(mock) id 만 반환하고 실제 발송은 일어나지 않으며, 브리지가
        설정돼 있으면 실제로 발송합니다. 발송 상태/시각 컬럼은 두 경로 모두
        에서 실시간으로 갱신됩니다. 디바이스 토큰이 없는 사용자는 발송
        버튼이 비활성화됩니다.
      </p>
      {/* 가로 스크롤 래퍼 — 좁은 화면에서도 모든 열에 도달할 수 있도록
          overflow-x:auto 로 감싼다. */}
      <div style={opsTableScroll}>
        <div style={opsTableInner}>
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              tableLayout: 'fixed',
              whiteSpace: 'normal',
            }}
          >
            <colgroup>
              {OPS_TABLE_COLUMNS.trim().split(/\s+/).map((w, i) => (
                <col
                  key={i}
                  style={w.startsWith('minmax') ? undefined : { width: w }}
                />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th scope="col" style={opsTh}>이름</th>
                <th scope="col" style={opsTh}>연락처</th>
                <th scope="col" style={opsTh}>세이버스 등록</th>
                <th scope="col" style={opsTh}>발송 상태</th>
                <th scope="col" style={opsTh}>마지막 발송 시각</th>
                <th scope="col" style={opsTh}>알림 열람 응답</th>
                <th scope="col" style={opsTh}>비고 / 발송 / 삭제</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td
                    colSpan={7}
                    style={{ ...opsTd, textAlign: 'center', color: '#777' }}
                  >
                    등록된 사용자가 없습니다.
                  </td>
                </tr>
              )}
              {rows.map((p) => (
                <tr
                  key={p.userId}
                  style={{
                    background: justAddedId === p.userId ? '#FFFDE7' : 'transparent',
                  }}
                >
                  <td style={opsTdName}>{p.name}</td>
                  <td style={opsTdMono}>{p.phone ?? '-'}</td>
                  <td style={opsTd}>
                    {/* 「세이버스 등록 / 미등록」 뱃지. hasToken === true 면
                        폰이 토큰을 붙인 상태(등록 완료). 토큰이 붙으면
                        subscribeRegistrations 에 의해 실시간으로 켜진다. */}
                    <span style={opsTokenBadge(p.hasToken)}>
                      {p.hasToken ? '세이버스 등록' : '미등록'}
                    </span>
                  </td>
                  <td
                    style={{
                      ...opsTd,
                      color: opsSendColor(p.sendState),
                      fontWeight: 700,
                    }}
                  >
                    {labelSendState(p.sendState)}
                  </td>
                  <td style={opsTdMono}>{p.lastSentAt ?? '-'}</td>
                  <td style={opsTd}>{labelRead(p.isRead, p.sendState)}</td>
                  <td style={opsTd}>
                    <div
                      style={{
                        display: 'grid',
                        gridTemplateColumns: 'auto 52px',
                        gap: '8px',
                        alignItems: 'start',
                      }}
                    >
                      {/* 위 줄: 세부 정보 버튼(글자 폭) + 삭제 아이콘.
                          세부 정보는 표 안의 좁은 칸이 아니라 팝업에서
                          넓게 보인다. aria-label 에 사람 이름을 넣어
                          스크린리더가 "이 행은 누구의 것인지" 알 수 있게 한다.
                          다른 행의 팝업이 이미 열려 있으면 비활성화해 두
                          팝업이 겹치지 않게 한다. */}
                      <button
                        type="button"
                        style={{ ...opsActionBtnBase, ...opsBtn('outline') }}
                        aria-label={p.name + '님 세부 정보 보기'}
                        disabled={detailOpen}
                        onClick={(e) => {
                          const btn = e.currentTarget
                          onOpenDetail(p, btn)
                        }}
                      >
                        세부 정보
                      </button>
                      <button
                        type="button"
                        style={{
                          ...opsActionBtnBase,
                          ...opsBtn('danger'),
                          width: '52px',
                          padding: 0,
                        }}
                        aria-label={p.name + '님 등록 삭제'}
                        onClick={() => onDelete(p)}
                      >
                        <DeleteIcon />
                      </button>

                      {/* 아래 줄(전체 폭): 발송 버튼.
                          발송 버튼 비활성화는 파생 상태(sendState)가
                          아니라 원본 데이터(hasToken) 기준이다. hasToken 이
                          false 면 토큰이 없어 발송 자체가 불가하다. 비활성
                          사유를 텍스트로도 알린다(단순 tooltip 만으로는
                          부족).

                          ⚠️ 이 자리에는 «네 갈래 분기»가 있다:
                            1. !hasToken → 폰이 연결되지 않아 보낼 수 없음
                            2. sendState === 'unconfirmed' → 재발송 금지
                               (브라우저가 요청을 끊은 것으로 서버가 이미
                               보냈을 수 있다. 같은 재난 알림이 두 번 가는
                               것을 막아야 한다.)
                            3. sending.has(userId) → 발송 중…
                            4. 그 외 → 알림 보내기
                          배치는 바꿨지만 «분기 자체는 네 개 모두 그대로»
                          둔다. 한 칸이라도 빠지면 중복 발송 버그가
                          되살아난다. */}
                      <div style={{ gridColumn: '1 / -1' }}>
                        {!p.hasToken ? (
                          <button
                            type="button"
                            style={{ ...opsActionBtnBase, ...opsBtn('primary', true), width: '100%' }}
                            disabled
                            aria-label="폰 미연결 — 디바이스 토큰이 없어 발송 불가"
                            title="폰 미연결 — 디바이스 토큰이 없어 발송 불가"
                          >
                            폰 미연결
                          </button>
                        ) : p.sendState === 'unconfirmed' ? (
                          /* unconfirmed 는 잠금 색이 «주의 노랑»이다.
                             붉게 칠하면 "실패했으니 다시 보내야지"로 읽히는데,
                             그게 정확히 막아야 하는 행동이다. 회색 죽은
                             버튼으로 하면 토큰 없음과 구분이 안 된다. 그래서
                             opsBtnUnconfirmed(노랑 바탕·노랑 테두리)로 따로
                             뺐다. failed(붉음)와도 색이 다르다. */
                          <button
                            type="button"
                            style={{ ...opsActionBtnBase, ...opsBtnUnconfirmed, width: '100%' }}
                            disabled
                            aria-label="결과 미확인 — 재발송 금지. 새로고침으로 확인하세요"
                            title="결과 미확인 — 재발송 금지. 새로고침으로 확인하세요"
                          >
                            결과 미확인
                          </button>
                        ) : sending.has(p.userId) ? (
                          <button
                            type="button"
                            style={{
                              ...opsActionBtnBase,
                              ...opsBtn('primary', true),
                              width: '100%',
                              cursor: 'wait',
                            }}
                            disabled
                            aria-busy="true"
                            aria-label={`${p.name}님에게 발송 중 — 잠시 기다려 주세요`}
                          >
                            발송 중…
                          </button>
                        ) : (
                          <button
                            type="button"
                            style={{ ...opsActionBtnBase, ...opsBtn('primary'), width: '100%' }}
                            onClick={() => onTestSend(p)}
                          >
                            알림 보내기
                          </button>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  )
}

// 휴지통 아이콘 — 라벨은 버튼 텍스트로는 빠지고 아이콘만 남은 삭제 버튼에
// 시각적 단서를 준다. aria-label 이 p.name + '님 등록 삭제' 로 스크린리더에는
// 문맥이 전달된다.
function DeleteIcon(): React.ReactElement {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
    </svg>
  )
}

// 행 단위 세부 정보 패널. 세부 속성(사는 곳·주거·이동·시력 등)을
// 운영자에게 보여준다. 표의 좁은 마지막 열에서는 읽기 어려워 세부 정보
// 팝업(RowDetailsDialog) 안에서 넓게 렌더된다.
//
// 저장소에서 읽어온 행(rec.fromStore === true)은 health/disability/lifestyle
// 필드가 저장소에 적히지 않았다(STORED_FIELDS 허용 목록 참조). 그래서 그 필드들은
// 「미저장」으로 표시한다 — toRecord 가 채운 중립 기본값을 사실처럼 보여주면
// 운영자가 잘못 판단한다(예: 계단 불가자를 가능으로 표시). 메모리 mock 경로는
// fromStore 가 undefined 이므로 실제 값을 그대로 보여준다.
function RowDetails({ rec }: { rec: RegistrationRecord }): React.ReactElement {
  // 저장소 출처 여부. true 면 민감/건강 필드를 미저장으로 표시.
  const notStored = rec.fromStore === true
  // 저장소에서 온 행에는 "저장하지 않은 항목" 안내를 상단에 둔다.
  const notStoredNote = '미저장 (저장하지 않은 항목)'
  const rows: ReadonlyArray<{ k: string; v: string }> = [
    { k: '사는 곳', v: `${rec.dongName} (${rec.dongCode})` },
    { k: '주거', v: notStored ? notStoredNote : labelHousing(rec.housing) },
    {
      k: '이동',
      v: notStored
        ? notStoredNote
        : `${labelMobility(rec.mobility)} · 계단 ${rec.stairsOk ? '가능' : '불가'}`,
    },
    { k: '시력', v: notStored ? notStoredNote : labelVision(rec.vision) },
    { k: '청력', v: notStored ? notStoredNote : labelHearing(rec.hearing) },
    { k: '언어', v: notStored ? notStoredNote : labelLanguage(rec.language) },
    { k: '독거', v: notStored ? notStoredNote : rec.livesAlone ? '예' : '아니요' },
    { k: '돌봄 대상', v: notStored ? notStoredNote : (rec.care ?? '없음') },
    { k: '쉬운 말', v: notStored ? notStoredNote : '항상 사용(기본값)' },
    {
      k: '비상 연락처',
      v: notStored
        ? notStoredNote
        : rec.guardian === null
          ? '없음'
          : `${rec.guardian.name} · ${rec.guardian.phone} · ${rec.guardian.relation}`,
    },
    {
      k: '등록 주체',
      v: notStored ? notStoredNote : labelRegisteredBy(rec.registeredBy),
    },
    // 3단계 분리동의 상태. 등록 시점의 체크 여부를 운영자가 확인할 수 있게.
    // consents 는 프론트 mock 전용 optional 필드라 과거/seed 레코드에는 없을
    // 수 있다 — 없으면 '미기록'으로 표시.
    {
      k: '동의',
      v: notStored ? notStoredNote : labelConsentsOptional(rec.consents),
    },
  ]
  return (
    <div style={opsRowDetail}>
      {notStored && (
        <p style={opsNotStoredNote}>
          건강·장애·생활 정보는 저장하지 않아 여기에 표시할 수 없습니다. 등록
          시 입력한 값은 운영자 화면에서만 확인했습니다.
        </p>
      )}
      <dl style={opsDetailList}>
        {rows.map((r) => (
          <React.Fragment key={r.k}>
            <dt style={opsDetailKey}>{r.k}</dt>
            <dd style={opsDetailVal}>
              {notStored && r.v === notStoredNote ? (
                <span style={opsNotStoredValue}>{r.v}</span>
              ) : (
                r.v
              )}
            </dd>
          </React.Fragment>
        ))}
      </dl>
    </div>
  )
}

// ---- 세부 정보 다이얼로그 ------------------------------------------------
//
// 표의 마지막 열이 좁아 세부 정보를 한 글자씩 세로로 잘려 보이는 문제를
// 해결하기 위해, 행 단위 세부 정보를 이 팝업에서 넓게 보여준다.
// 삭제 확인 모달(DeleteConfirmDialog)과 같은 방식을 따른다:
//   - role="dialog" · aria-modal="true" · 사람 이름이 들어간 aria-label
//   - Escape · 바깥 클릭 · 닫기 버튼으로 닫힌다
//   - 열릴 때 포커스가 닫기 버튼으로, 닫힐 때 눌렀던 버튼으로 돌아온다
//   - 내용이 길면 팝업 안에서 스크롤된다
//   - 터치 타깃 48px 이상
//
// 포커스 트랩: 팝업이 열려 있을 때 Tab/Shift+Tab 이 팝업 밖으로 나가지 않게
// 다이얼로그 내부의 포커스 가능 요소 사이를 순환시킨다. 포커스가 밖으로
// 나가면 스크린리더 사용자가 표를 건드려 의도치 않은 동작을 일으킬 수 있다.

interface RowDetailsDialogProps {
  rec: RegistrationRecord
  onClose: () => void
}

function RowDetailsDialog({
  rec,
  onClose,
}: RowDetailsDialogProps): React.ReactElement {
  const closeBtnRef = useRef<HTMLButtonElement | null>(null)
  const cardRef = useRef<HTMLDivElement | null>(null)

  // 열릴 때 닫기 버튼으로 포커스를 옮긴다 — 팝업이 뜬 직후 키보드 초점이
  // 어디 있는지 운영자가 바로 알 수 있게. setTimeout 으로 다음 틱에 실행해
  // DOM 에 올라온 뒤 포커스를 잡는다.
  useEffect(() => {
    const id = window.setTimeout(() => {
      const el = closeBtnRef.current
      if (el !== null) el.focus()
    }, 0)
    return () => {
      window.clearTimeout(id)
    }
  }, [])

  function handleKeyDown(e: React.KeyboardEvent<HTMLDivElement>): void {
    // Escape 로 닫는다.
    if (e.key === 'Escape') {
      e.preventDefault()
      onClose()
      return
    }
    // Tab / Shift+Tab 포커스 트랩. 다이얼로그 안의 포커스 가능 요소
    // 순환 — 밖으로 나가지 않게 한다.
    if (e.key !== 'Tab') return
    const root = cardRef.current
    if (root === null) return
    const focusable = root.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (first === undefined || last === undefined) return
    if (e.shiftKey) {
      if (document.activeElement === first || document.activeElement === root) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${rec.name}님 세부 정보`}
      style={opsDialogBackdrop}
      onClick={(e) => {
        // 바깥(배경) 클릭으로 닫는다. 카드 안쪽 클릭은 무시한다.
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        ref={cardRef}
        style={opsRowDetailDialogCard}
        onKeyDown={handleKeyDown}
      >
        <div style={opsRowDetailDialogHeader}>
          <h2 style={opsRowDetailDialogTitle}>
            {rec.name}님 세부 정보
          </h2>
          <button
            ref={closeBtnRef}
            type="button"
            onClick={onClose}
            aria-label="세부 정보 닫기"
            style={opsRowDetailDialogCloseBtn}
          >
            닫기
          </button>
        </div>
        <div style={opsRowDetailDialogBody}>
          <RowDetails rec={rec} />
        </div>
      </div>
    </div>
  )
}

// Generate a random hexadecimal suffix for the registration id.
//
// We deliberately avoid the W3C "UUID v4" helper here: that helper is only
// defined in secure contexts (HTTPS or localhost). This screen is designed
// to be opened on a tablet that may reach it via a plain-http LAN address
// like http://192.168.x.x — an insecure origin where that helper is
// `undefined` and the register button would throw on the spot.
//
// `crypto.getRandomValues` is the lower-level primitive the helper is built
// on, and it is available on insecure origins too, so it is the correct
// choice for this screen.
//
// 10 bytes (80 bits) of randomness makes the id unguessable even though the
// millisecond timestamp prefix remains predictable. The format stays
// `ops-<timestamp>-<rand>` so any code that pattern-matched on the old
// `ops-<timestamp>` shape keeps working — only a random tail is appended.
function randomIdSuffix(): string {
  const buf = new Uint8Array(10)
  crypto.getRandomValues(buf)
  // hex-encode lowercase, no separator. 10 bytes → 20 hex chars.
  let out = ''
  for (let i = 0; i < buf.length; i += 1) {
    out += buf[i].toString(16).padStart(2, '0')
  }
  return out
}

// ---- 라벨 헬퍼 ---------------------------------------------------------
// mock 데이터의 enum 값을 한국어 표시로 바꾼다. 사용자에게 raw enum 문자열
// (banjiha 등)이 노출되지 않도록.

// 현재 시각을 HH:MM:SS 로 포맷한다. 발송 완료 토스트에 시각을 찍어 운영자가
// 언제 보냈는지 알 수 있게 한다.
function formatHMS(d: Date): string {
  const pad = (n: number): string => n.toString().padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function labelHousing(h: Housing): string {
  // `undefined` 폴백: 저장소가 민감필드를 더 이상 반환하지 않을 때
  // toRecord 가 'normal' 기본값을 주긴 하지만, 라벨 헬퍼 자체도
  // 방어적으로 만든다 — 잘못된 캐스트나 과거 문서에서 undefined 가
  // 들어와도 빈칸이 아니라 안전한 기본 표시가 나오게.
  if (h === undefined) return '일반'
  return { normal: '일반', banjiha: '반지하', lowland: '저지대' }[h] ?? '일반'
}
function labelMobility(m: Mobility): string {
  if (m === undefined) return '정상'
  return { ok: '정상', slow: '느림', assisted: '보조' }[m] ?? '정상'
}
function labelVision(v: Vision): string {
  // 셀렉트 드롭다운에서 'ok'/'low'만 노출하므로 표기도 두 가지만 쓴다.
  // 전맹 분기는 UI 비노출 정책에 따라 운영 콘솔 표기에서도
  // 동일하게 저시력으로 매핑된다 — enum 키 자체를 소스에 등장시키지
  // 않기 위해 객체 리터럴 대신 직접 매핑한다.
  if (v === undefined || v === null) return '정상'
  return v === 'ok' ? '정상' : '저시력'
}
function labelHearing(h: Hearing): string {
  if (h === undefined) return '정상'
  return { ok: '정상', bad: '청각' }[h] ?? '정상'
}
function labelLanguage(l: Language): string {
  if (l === undefined) return '한국어'
  const labels: Partial<Record<Language, string>> = {
    ko: '한국어',
    vi: '베트남어',
    zh: '중국어',
    en: '영어',
  }
  return labels[l] ?? '한국어'
}
function labelRegisteredBy(r: RegisteredBy): string {
  if (r === undefined) return '보호자'
  return {
    self: '본인',
    guardian: '보호자',
    welfare_center: '복지관',
    employer: '고용주',
  }[r] ?? '보호자'
}

// 동의 상태 한 줄 요약. 폼(SurveySummary)용 — 폼의 consents 는 항상 채워져
// 있으므로 optional 분기가 없다. 필수(personal)가 꺼져 있으면 등록 불가 상태
// 임을 함께 표시한다.
function labelConsents(c: ConsentFlags): string {
  const items = CONSENT_ITEMS.map((it) => {
    const on = c[it.id]
    const tag = on ? '체크' : '미체크'
    return `${it.id}:${tag}`
  })
  const requiredMet = c.personal
  return `${items.join(' / ')}${requiredMet ? '' : ' (필수 항목 미체크 — 등록 불가)'}`
}

// 동의 상태 한 줄 요약. 현황 표(RowDetails)용 — 등록 레코드의 consents 는
// 프론트 mock 전용 optional 필드라 과거/seed 레코드에는 없을 수 있다.
// 없으면 '미기록(등록 시점 미보관)'으로 표시해 운영자가 빈 값의 의미를 안다.
// 민감정보 미동의자는 그 사실이 명시돼야 한다 — 맞춤 안내가 왜 제한되는지.
function labelConsentsOptional(c: ConsentFlags | undefined): string {
  if (c === undefined) return '미기록(등록 시점 미보관)'
  const parts: string[] = []
  for (const it of CONSENT_ITEMS) {
    const on = c[it.id]
    const short = { personal: '개인정보', sensitive: '민감정보', location: '위치정보' }[
      it.id
    ]
    parts.push(`${short} ${on ? '동의' : '미동의'}`)
  }
  // 민감정보 미동의는 맞춤 안내 제한으로 이어지므로 운영자가 알아야 한다.
  if (!c.sensitive) {
    parts.push('— 민감정보 미동의로 맞춤 안내 제한')
  }
  return parts.join(' · ')
}

// 발송 상태 라벨. 컬럼 헤더 = "발송 상태", 값은 한국어 표시.
//   not_sent     → "발송 안 함"
//   sent         → "발송 완료"
//   failed       → "발송 실패"
//   unconfirmed  → "결과 미확인" — 브라우저가 요청을 끊은 것으로 서버가 이미
//                  보냈을 수 있다. 재발송 금지.
//   no_token     → "알림 준비 안 됨(토큰 없음)" — 디바이스 등록 전 상태.
function labelSendState(s: SendState): string {
  return {
    not_sent: '발송 안 함',
    sent: '발송 완료',
    failed: '발송 실패',
    unconfirmed: '결과 미확인 (재발송 금지)',
    no_token: '알림 준비 안 됨(토큰 없음)',
  }[s]
}

// 알림 열람/응답 상태 라벨. 발송을 한 번도 하지 않았거나 토큰이 없는
// 경우 "열람/응답" 판단 자체가 무의미하므로 '-' 로 표시한다. 발송된 경우
// 사용자의 알림 열람 여부로 읽음/안 읽음을 표시한다.
function labelRead(isRead: boolean, sendState: SendState): string {
  if (sendState === 'not_sent' || sendState === 'no_token') return '-'
  if (sendState === 'unconfirmed') return '확인 안 됨'
  return isRead ? '열람함(응답 대기)' : '미열람'
}
