// Mock profiles. Every name, phone, and detail here is a fictional
// synthetic persona for the SAVERS demo — no real person is represented.
// Phones use the obvious 010-0000-xxxx dummy range. See ./README.md.
//
// 페르소나 목록:
//   p001/p002 — full personas.
//   p003 guardian: null         — guardian contact absent on this persona
//   p004 hearing: 'bad'         — hearing impairment persona
//   p005 vision: 'low'          — large-print/semantic-first path
//                              (UI 드롭다운은 더 이상 전맹 옵션을 노출하지
//                               않는다. 시맨틱·음성 강화 출력은
//                               저시력 경로에서 처리한다.)
//   p006 care: '영유아'          — auto-stated in message body
//   p007 mobility: 'assisted' + stairsOk: false
//   p008 housing: 'normal' + defaults (control)
//   p009 language:'vi'         — vietnamese-speaking foreign worker persona
//   p010 language:'vi'         — vietnamese-speaking foreign worker persona
//                              (다른 주거/이동 속성으로 다양성 확보)
//
// Language coverage: language:'ko' / language:'vi'. The contract lists
// ko, vi, zh, en, but only ko and vi have UI translations today. zh and en
// profiles fall back to Korean at the `t()` resolution layer (with a
// dev-mode console.warn). The demo personas stay on the two fully-translated
// languages; the type is widened so a zh/en profile from the backend does
// not break the type system.
//
// 과거 중국어/영어 페르소나는 언어만 vi 로 정합하고 기존 주거/이동/고용주
// 맥락은 유지해 persona 다양성을 보존한다.
//
// dongCode = 행정동 8자리 (서원동 1162064500), bjdCode = 법정동 10자리
// (신림동 1162010200). The pairing of administrative dong != beopjeong-dong
// is a real-world case the data captures on purpose (see openapi.yaml
// bjdCode description).

import type { Profile } from '../api/types'

export const PROFILES: Record<string, Profile> = {
  p001: {
    userId: 'p001',
    name: '김순자',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'banjiha',
    mobility: 'slow',
    stairsOk: false,
    easyText: true,
    vision: 'low',
    hearing: 'ok',
    language: 'ko',
    livesAlone: true,
    care: null,
    guardian: { name: '이영희', phone: '010-0000-0001', relation: '딸' },
    registeredBy: 'guardian',
  },
  p002: {
    userId: 'p002',
    name: '응우옌 반',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'lowland',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'vi',
    livesAlone: true,
    care: null,
    guardian: {
      name: '박현장',
      phone: '010-0000-0002',
      relation: '현장관리자',
    },
    registeredBy: 'employer',
  },
  p003: {
    userId: 'p003',
    name: '박영수',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'normal',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'ko',
    livesAlone: true,
    care: null,
    // Guardian is null on purpose — this persona has no guardian contact.
    guardian: null,
    registeredBy: 'welfare_center',
  },
  p004: {
    userId: 'p004',
    name: '최순영',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'normal',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    // Hearing impairment persona.
    hearing: 'bad',
    language: 'ko',
    livesAlone: true,
    care: null,
    guardian: { name: '김준호', phone: '010-0000-0004', relation: '아들' },
    registeredBy: 'guardian',
  },
  p005: {
    userId: 'p005',
    name: '정맑음',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'normal',
    mobility: 'assisted',
    stairsOk: false,
    easyText: true,
    // Low vision: large-print + semantic-emphasis path. UI 드롭다운은 더 이상
    // 전맹 옵션을 노출하지 않는다 — 음성 중심 출력도 이 저시력
    // 경로에서 처리된다.
    vision: 'low',
    hearing: 'ok',
    language: 'ko',
    livesAlone: false,
    care: null,
    guardian: { name: '정수민', phone: '010-0000-0005', relation: '보호자' },
    registeredBy: 'guardian',
  },
  p006: {
    userId: 'p006',
    name: '한보람',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'normal',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'ko',
    livesAlone: false,
    // Care subject auto-stated in message body.
    care: '영유아',
    guardian: { name: '한동석', phone: '010-0000-0006', relation: '배우자' },
    registeredBy: 'guardian',
  },
  p007: {
    userId: 'p007',
    name: '윤명자',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'lowland',
    mobility: 'assisted',
    stairsOk: false,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'ko',
    livesAlone: true,
    care: null,
    guardian: { name: '윤지현', phone: '010-0000-0007', relation: '딸' },
    registeredBy: 'guardian',
  },
  // Control persona — defaults, no special branches.
  p008: {
    userId: 'p008',
    name: '이기준',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'normal',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'ko',
    livesAlone: false,
    care: null,
    guardian: { name: '이수경', phone: '010-0000-0008', relation: '배우자' },
    registeredBy: 'guardian',
  },
  // p009 — 베트남어 사용 노동외국인 페르소나. 과거 중국어 설정을
  // 베트남어로 변경. p002(vi) 와 같은 고용주 등록 맥락이지만 거주 형태·이동
  // 능력을 다르게 설정해 persona 다양성을 유지한다.
  p009: {
    userId: 'p009',
    name: '트란 반',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'normal',
    mobility: 'ok',
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'vi',
    livesAlone: true,
    care: null,
    guardian: {
      name: '최현장',
      phone: '010-0000-0009',
      relation: '현장관리자',
    },
    registeredBy: 'employer',
  },
  // p010 — 베트남어 사용 노동외국인 페르소나. 과거 영어 설정을
  // 베트남어로 변경. p009 와 동일 언어지만 저지대 주거·느린 보행으로 다른
  // 속성 분포를 만들어 다양성을 확보한다.
  p010: {
    userId: 'p010',
    name: '레 틴',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'lowland',
    mobility: 'slow',
    stairsOk: false,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'vi',
    livesAlone: true,
    care: null,
    guardian: {
      name: '정현장',
      phone: '010-0000-0010',
      relation: '현장관리자',
    },
    registeredBy: 'employer',
  },
  // p011 — all_excluded demo persona.
  //
  // Every shelter the server knows about for this location was excluded
  // (침수 위험·운영 중단·가는 길 위험). The paired fixture is
  // SHELTERS_ALL_EXCLUDED_VERTICAL (availability 'all_excluded', items
  // empty, excluded reasons populated). See shelters.ts for details.
  p011: {
    userId: 'p011',
    name: '김복자',
    dongCode: '1162064500',
    dongName: '서원동',
    bjdCode: '1162010200',
    housing: 'banjiha',
    mobility: 'slow',
    // stairsOk stays true; the all_excluded flow no longer carries a
    // vertical-evacuation instruction, so there is no stairs invariant to
    // preserve here. Kept true for consistency with the fixture's persona.
    stairsOk: true,
    easyText: true,
    vision: 'ok',
    hearing: 'ok',
    language: 'ko',
    livesAlone: true,
    care: null,
    guardian: { name: '김영희', phone: '010-0000-0011', relation: '딸' },
    registeredBy: 'guardian',
  },
}
