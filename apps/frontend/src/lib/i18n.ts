// UI string dictionary + small language-aware display helpers.
//
// The resident-facing screens (Landing, Join, ShelterGuide, ChatDock,
// LocationConsent) render every human-readable label through this module.
// The dictionary is split by language: Korean is the default and always
// present; Vietnamese is the second fully-translated UI language driven by
// Profile.language. The source of the UI language is the profile — the
// resident never picks a language themselves (a guardian/welfare center /
// employer chose it during surrogate registration).
//
// TYPE-LEVEL MISSING-KEY DETECTION (the load-bearing property):
//   `StringKey` is a closed union of every UI string id. `Dictionary` is
//   `Record<StringKey, DictionaryEntry>`, and DICTIONARY is annotated with
//   that exact type (not inferred). Consequences:
//     - A typo in a key passed to `t()` is a compile error (the union does
//       not contain it).
//     - An entry missing from DICTIONARY is a compile error (Record requires
//       every key).
//     - Adding a new StringKey without filling at least `ko` is a compile
//       error (DictionaryEntry.ko is required).
//   Korean (`ko`) is the required baseline for every entry; Vietnamese (`vi`)
//   is optional but strongly expected — a missing `vi` on an entry that has
//   one is flagged at the type level via the `MissingVi` sentinel (see below).
//
// KOREAN FALLBACK POLICY:
//   `t(key, lang)` resolves to the entry's `vi` string when lang === 'vi' and
//   a `vi` field exists. For zh and en (languages whose UI translations are
//   out of scope), and for any language without a `vi` field, the function
//   falls back to Korean — but NOT silently. A console.warn is emitted for
//   every zh/en resolution so the developer knows the screen is rendering
//   Korean instead of the profile's language. A profile with a language we do
//   not yet support therefore renders Korean everywhere — never a
//   mixed-language screen, never `undefined` on screen.

import { createElement } from 'react'
import type { ReactNode } from 'react'
import type {
  Bearing,
  Hearing,
  Housing,
  Language,
  Mobility,
  Vision,
} from '../api/types'

// ---- UI string keys --------------------------------------------------
//
// Every id here MUST have a matching entry in DICTIONARY below. The union is
// the source of truth for what the screens may ask for; the dictionary is
// the source of truth for what each language says.
export type StringKey =
  // Landing — alert header / status / retry
  | 'alert.loadFailed'
  | 'alert.networkErrorPrefix'
  | 'alert.retry'
  | 'alert.retrying'
  | 'alert.preparing'
  // Landing — address fallback
  | 'landing.addressUnknown'
  // Landing — 위치 카드의 등록 주소 라벨. 히어로 위치 카드에서 사용자가
  // "이게 내 얘기인지" 확인하는 작은 캡션이다.
  | 'landing.registeredHomeLabel'
  // Landing — 등록 세션 표시. 등록 문서에서 만든 세션(이름·행정동만 진짜,
  // 나머지는 특기사항 없음)에서 담담하게 한 줄로 그 사실을 드러낸다. 경고나
  // 사과가 아니라 사실 확인이다.
  | 'landing.registrationOnlyNotice'
  // Landing — contract invariant violation (grounded body with no sources).
  // The body claimed evidence but carries none, so it is suppressed. The
  // title stays; only the instruction body is hidden.
  | 'alert.bodySuppressedTitle'
  | 'alert.bodySuppressed'
  // ShelterGuide — section label + no-matching-key notice
  | 'shelter.sectionLabel'
  | 'shelter.noMatchingKey.title'
  | 'shelter.noMatchingKey.body'
  | 'shelter.searching'
  | 'shelter.fetchFailedPrefix'
  // ShelterGuide — list header by basis
  | 'shelter.nearbyCurrentLocation'
  | 'shelter.nearbyRegisteredHome'
  // ShelterGuide — freshness / cache disclosure
  | 'shelter.cacheAsOf'
  // ShelterGuide — exclusion notice
  | 'shelter.excludedPrefix'
  // ShelterGuide — degraded / empty
  | 'shelter.degradedNotice'
  | 'shelter.emptyList'
  // ShelterGuide — list item scaffolding
  | 'shelter.distance'
  | 'shelter.direction'
  | 'shelter.hasStairs'
  | 'shelter.expand.map.open'
  | 'shelter.expand.map.close'
  | 'shelter.expand.detail.open'
  | 'shelter.expand.detail.close'
  // ShelterGuide — blind detail block
  | 'shelter.blind.address'
  | 'shelter.blind.distance'
  | 'shelter.blind.direction'
  | 'shelter.blind.hasStairs'
  // ShelterGuide — all_excluded notice
  | 'shelter.allExcluded.why'
  | 'shelter.allExcluded.whyNone'
  | 'shelter.allExcluded.generic'
  // allExcluded copy admits the gap honestly (no shelter could be offered).
  // ko: 지금 안내할 수 있는 대피소를 찾지 못했습니다.
  // vi: Hiện không tìm được nơi trú ẩn nào để hướng dẫn.
  | 'shelter.allExcluded.reasonSeparator'
  | 'shelter.allExcluded.tailOthers'
  // ShelterGuide — next-action guidance for empty-list branches. When no
  // shelter can be offered (upstream outage, all excluded, or simply an
  // empty result), the resident must NOT be left with a bare "there are no
  // shelters" line that could make them stay in place. The next action is
  // conditioned on stairsOk: a resident who CAN use stairs is told to move
  // to higher ground / an upper floor; a resident who CANNOT is honestly
  // told there is no action the screen can offer right now and to use the
  // chat / ask a guardian instead. A third state, stairsUnknown, covers
  // registration-built sessions where stairsOk defaulted to true as a
  // neutral placeholder but was never actually confirmed — there we must
  // NOT give a definitive upstairs instruction.
  | 'shelter.nextAction.stairsOk'
  | 'shelter.nextAction.stairsBlocked'
  | 'shelter.nextAction.stairsUnknown'
  // LocationConsent
  | 'consent.sectionLabel'
  | 'consent.intro'
  | 'consent.bullet.once'
  | 'consent.bullet.session'
  | 'consent.bullet.fallback'
  | 'consent.button.idle'
  | 'consent.button.requesting'
  | 'consent.button.done'
  | 'consent.button.denied'
  | 'consent.button.unavailable'
  | 'consent.note.denied'
  | 'consent.note.unavailable'
  | 'consent.aria.button'
  // ChatDock
  | 'chat.sectionLabel'
  | 'chat.toggle.open'
  | 'chat.toggle.closed'
  | 'chat.status.searching'
  | 'chat.quickListLabel'
  | 'chat.quickExhausted'
  | 'chat.inputLabel'
  | 'chat.placeholder'
  | 'chat.send'
  | 'chat.sendBusy'
  | 'chat.errorPrefix'
  | 'chat.retry'
  | 'chat.refusal.no_evidence'
  | 'chat.refusal.out_of_scope'
  | 'chat.refusal.unsafe'
  | 'chat.refusal.fallback'
  | 'chat.refusal.emergency'
  | 'chat.followup.askMore'
  | 'chat.followup.reshelter'
  // ChatDock — quick replies
  | 'chat.quick.goOut'
  | 'chat.quick.pet'
  | 'chat.quick.upperFloor'
  | 'chat.quick.familyCare'
  | 'chat.quick.alone'
  // Join — onboarding screen (all phases)
  | 'join.loading'
  | 'join.notFound.title'
  | 'join.notFound.body'
  | 'join.confirm.title'
  | 'join.confirm.askAccept'
  | 'join.confirm.nameConfirm'
  | 'join.confirm.acceptButton'
  | 'join.confirm.explainer'
  | 'join.working'
  | 'join.conflict.title'
  | 'join.conflict.askReplace'
  | 'join.conflict.replaceDetail'
  | 'join.conflict.replaceButton'
  | 'join.conflict.keepButton'
  | 'join.done.title'
  | 'join.done.body'
  | 'join.kept.title'
  | 'join.kept.body'
  | 'join.denied.title'
  | 'join.denied.body'
  | 'join.denied.recoveryAndroid'
  | 'join.denied.recoveryIos'
  | 'join.denied.rescan'
  | 'join.error.title'
  | 'join.error.retry'
  | 'join.error.unavailable'
  | 'join.error.timeout'
  // Join — iOS home-screen notice (iOS Safari only supports web push after the
  // page is added to the home screen). Shown only on iOS-class browsers that
  // are NOT running as a standalone home-screen app.
  | 'join.iosNotice.title'
  | 'join.iosNotice.body'
  | 'join.iosNotice.steps'
  | 'join.iosNotice.helper'
  // ShelterMap — loading / error notices (the map slot only; the text list
  // is i18n'd separately inside ShelterGuide).
  | 'shelter.map.loading'
  | 'shelter.map.error'
  // SpeakButton — read-aloud toggle labels + aria-labels. Screen readers
  // announce the aria-label, so it must follow the active UI language.
  | 'speak.read'
  | 'speak.stop'
  | 'speak.aria.read'
  | 'speak.aria.stop'
  // EasyText 단계적 노출 — "다음" 버튼. 이 버튼은 행동 지침에 도달하는
  // 유일한 통로이므로 화면 언어를 반드시 따라야 한다: 라벨이 한국어면
  // 베트남어만 읽는 사용자에게 지침으로 가는 길이 읽을 수 없는 글자로
  // 적혀 있는 셈이 된다(PR #50 리뷰, 머지 전 필수).
  | 'easyText.next'
  | 'easyText.allRevealed'

// The dictionary entry shape. `ko` is always required — it is the baseline
// that every fallback resolves to. `vi` is optional at the type level but
// every existing entry carries one; the `MissingVi` sentinel below makes
// forgetting a `vi` field a compile error for the existing keys while still
// allowing new entries to be added with just `ko` during development.
//
// `zh` and `en` are deliberately absent from the entry shape: UI translations
// for those languages are out of scope. Profiles with those languages fall
// back to Korean via `t()`.
export interface DictionaryEntry {
  ko: string
  vi?: string
}

// The dictionary type. `Record<StringKey, DictionaryEntry>` is what turns
// "I forgot a key" into a hard compile error instead of a runtime hole.
export type Dictionary = Record<StringKey, DictionaryEntry>

const DICTIONARY: Dictionary = {
  'alert.loadFailed': {
    ko: '지금은 맞춤 안내를 불러오지 못했습니다.',
    vi: 'Hiện không thể tải hướng dẫn cá nhân hóa.',
  },
  'alert.networkErrorPrefix': {
    ko: '네트워크 또는 서버 오류:',
    vi: 'Lỗi mạng hoặc máy chủ:',
  },
  'alert.retry': {
    ko: '다시 시도',
    vi: 'Thử lại',
  },
  'alert.retrying': {
    ko: '다시 불러오는 중…',
    vi: 'Đang tải lại…',
  },
  'alert.preparing': {
    ko: '개인 안내를 준비하고 있습니다…',
    vi: 'Đang chuẩn bị hướng dẫn cá nhân…',
  },
  'landing.addressUnknown': {
    ko: '주소 미확인',
    vi: 'Chưa xác định địa chỉ',
  },
  'landing.registeredHomeLabel': {
    ko: '등록된 주소',
    vi: 'Địa chỉ đã đăng ký',
  },
  'landing.registrationOnlyNotice': {
    ko: '이 안내는 등록된 성함과 행정동만 바탕으로 작성됐습니다. 개인 상황에 맞춘 정보가 필요하면 아래에서 더 물어보실 수 있습니다.',
    vi: 'Hướng dẫn này chỉ dựa trên tên và địa chỉ hành chính đã đăng ký. Nếu cần thông tin phù hợp với tình huống của bạn, hãy hỏi thêm bên dưới.',
  },
  'alert.bodySuppressedTitle': {
    ko: '이 안내의 행동 지시문을 표시하지 않습니다',
    vi: 'Không hiển thị chỉ dẫn hành động của thông báo này',
  },
  'alert.bodySuppressed': {
    ko:
      '이 안내문이 근거로 삼아야 할 공식 출처가 함께 오지 않았습니다. 근거 없는 지시를 드리는 것은 위험하므로, 행동 지시문만 빼고 안내를 다시 불러올 수 있게 합니다. 아래 대피소 안내와 추가 질문은 그대로 쓸 수 있습니다.',
    vi:
      'Thông báo này không kèm nguồn chính thức làm căn cứ. Việc đưa ra chỉ dẫn không có căn cứ là nguy hiểm, nên chỉ phần chỉ dẫn hành động bị ẩn — bạn vẫn có thể tải lại hướng dẫn, xem hướng dẫn nơi trú ẩn và hỏi thêm bên dưới.',
  },
  'shelter.sectionLabel': {
    ko: '대피소 안내',
    vi: 'Hướng dẫn nơi trú ẩn',
  },
  'shelter.noMatchingKey.title': {
    // The Korean previously read "주소지를 확인할 수 있어" (the address CAN be
    // resolved), which is the opposite of the Vietnamese and the opposite of
    // what this notice means: the address could NOT be resolved, so shelters
    // cannot be shown. Both languages now say the same thing.
    ko: '주소지를 확인할 수 없어 대피소 안내를 표시하지 못합니다.',
    vi: 'Không xác định được địa chỉ nên không thể hiển thị hướng dẫn nơi trú ẩn.',
  },
  'shelter.noMatchingKey.body': {
    ko: '맞춤 안내를 다시 불러오면 주소지가 확인됩니다.',
    vi: 'Vui lòng tải lại hướng dẫn cá nhân để xác định địa chỉ.',
  },
  'shelter.searching': {
    ko: '대피소를 찾는 중…',
    vi: 'Đang tìm nơi trú ẩn…',
  },
  'shelter.fetchFailedPrefix': {
    ko: '대피소 정보를 가져오지 못했습니다:',
    vi: 'Không tải được thông tin nơi trú ẩn:',
  },
  'shelter.nearbyCurrentLocation': {
    ko: '현재 위치 기준 가까운 대피소',
    vi: 'Nơi trú ẩn gần theo vị trí hiện tại',
  },
  'shelter.nearbyRegisteredHome': {
    ko: '등록하신 자택({dong}) 기준 가까운 대피소',
    vi: 'Nơi trú ẩn gần theo địa chỉ đã đăng ký ({dong})',
  },
  'shelter.cacheAsOf': {
    ko: '⚠️ {when} 기준 저장된 정보입니다. 최신 정보가 아닐 수 있습니다.',
    vi: '⚠️ Thông tin lưu theo thời điểm {when}. Có thể không phải mới nhất.',
  },
  'shelter.excludedPrefix': {
    ko: '⚠️ 침수 위험·운영 상태 등의 사유로 {count}곳을 안내에서 제외했습니다.',
    vi: '⚠️ Đã loại {count} nơi khỏi hướng dẫn do nguy cơ ngập nước hoặc tình trạng vận hành.',
  },
  'shelter.degradedNotice': {
    ko: '지금 대피소 정보를 불러올 수 없습니다. 잠시 후 다시 시도해 주세요.',
    vi: 'Hiện không tải được thông tin nơi trú ẩn. Vui lòng thử lại sau.',
  },
  'shelter.emptyList': {
    ko: '주변에 안내 가능한 대피소가 없습니다.',
    vi: 'Không có nơi trú ẩn nào quanh đây.',
  },
  'shelter.distance': {
    ko: '거리',
    vi: 'Khoảng cách',
  },
  'shelter.direction': {
    ko: '방향',
    vi: 'Hướng',
  },
  'shelter.hasStairs': {
    ko: '계단 있음',
    vi: 'Có bậc thang',
  },
  'shelter.expand.map.open': {
    ko: '▼ 지도 보기',
    vi: '▼ Xem bản đồ',
  },
  'shelter.expand.map.close': {
    ko: '▲ 지도 닫기',
    vi: '▲ Đóng bản đồ',
  },
  'shelter.expand.detail.open': {
    ko: '▼ 상세 안내 보기',
    vi: '▼ Xem hướng dẫn chi tiết',
  },
  'shelter.expand.detail.close': {
    ko: '▲ 상세 안내 닫기',
    vi: '▲ Đóng hướng dẫn chi tiết',
  },
  'shelter.blind.address': {
    ko: '주소:',
    vi: 'Địa chỉ:',
  },
  'shelter.blind.distance': {
    ko: '거리:',
    vi: 'Khoảng cách:',
  },
  'shelter.blind.direction': {
    ko: '방향:',
    vi: 'Hướng:',
  },
  'shelter.blind.hasStairs': {
    ko: '계단이 있습니다.',
    vi: 'Có bậc thang.',
  },
  'shelter.allExcluded.why': {
    ko: '침수 위험·운영 상태 등의 사유로 안내 가능한 대피소 {count}곳 모두 제외됐습니다. ({reasons})',
    vi: 'Đã loại toàn bộ {count} nơi trú ẩn do nguy cơ ngập nước hoặc tình trạng vận hành. ({reasons})',
  },
  'shelter.allExcluded.whyNone': {
    ko: '지금 이 위치에서 안내 가능한 대피소가 없습니다.',
    vi: 'Hiện không có nơi trú ẩn nào quanh vị trí này.',
  },
  'shelter.allExcluded.generic': {
    ko: '지금 안내할 수 있는 대피소를 찾지 못했습니다. 아래에서 더 질문할 수 있습니다.',
    vi: 'Hiện không tìm được nơi trú ẩn nào để hướng dẫn. Bạn có thể hỏi thêm ở bên dưới.',
  },
  'shelter.allExcluded.reasonSeparator': {
    ko: ', ',
    vi: ', ',
  },
  'shelter.allExcluded.tailOthers': {
    ko: '그 외 {count}곳',
    vi: 'khác {count} nơi',
  },
  'shelter.nextAction.stairsOk': {
    ko: '지금 가까운 대피소를 안내할 수 없습니다. 침수가 시작됐다면 위층이나 높은 건물로 옮겨 주세요.',
    vi: 'Hiện không thể hướng dẫn nơi trú ẩn gần. Nếu bắt đầu ngập, hãy chuyển lên tầng trên hoặc tòa nhà cao gần nhất.',
  },
  'shelter.nextAction.stairsBlocked': {
    ko: '아래에서 더 질문할 수 있고, 보호자에게 연락할 수도 있습니다. 이 화면에서 계단 없이 안내할 수 있는 대피 방법은 아직 없습니다.',
    vi: 'Bạn có thể hỏi thêm bên dưới hoặc liên hệ người bảo vệ. Hiện tại màn hình này chưa có cách di tản nào không dùng cầu thang để hướng dẫn.',
  },
  // nextAction.stairsUnknown: registration-built sessions default
  // `stairsOk` to true as a neutral placeholder, but that value was never
  // confirmed by a guardian during surrogate registration. We must NOT treat
  // it as a green light to give a definitive "go upstairs" instruction (that
  // is what stairsOk=true means for a real profile). Instead we honestly say
  // we don't know the resident's stairs ability, so we cannot safely
  // recommend climbing, and point them to the chat / a guardian.
  'shelter.nextAction.stairsUnknown': {
    ko: '계단 이용 가능 여부가 등록되어 있지 않아 무작정 위층으로 올라가라고 안내할 수 없습니다. 침수가 시작됐다면 아래에서 물어보시거나 보호자에게 연락해 주세요.',
    vi: 'Chưa ghi nhận việc bạn có thể dùng cầu thang hay không, nên không thể khuyên chắc chắn lên tầng trên. Nếu bắt đầu ngập, hãy hỏi bên dưới hoặc liên hệ người bảo vệ.',
  },
  'consent.sectionLabel': {
    ko: '현재 위치 확인',
    vi: 'Xác nhận vị trí hiện tại',
  },
  'consent.intro': {
    ko: '가까운 대피소를 찾기 위해 현재 위치를 확인할 수 있습니다.',
    vi: 'Có thể xác nhận vị trí hiện tại để tìm nơi trú ẩn gần.',
  },
  'consent.bullet.once': {
    ko: '이 화면에서 확인을 누른 순간에만 1회 확인합니다.',
    vi: 'Chỉ xác nhận 1 lần ngay khi bạn bấm đồng ý trên màn hình này.',
  },
  'consent.bullet.session': {
    ko: '확인된 위치는 이번 안내에만 쓰고 저장하지 않습니다.',
    vi: 'Vị trí xác nhận chỉ dùng cho hướng dẫn lần này, không lưu lại.',
  },
  'consent.bullet.fallback': {
    ko: '위치를 확인하지 않아도 등록된 주소 기준으로 안내합니다.',
    vi: 'Ngay cả khi không xác nhận vị trí, vẫn hướng dẫn theo địa chỉ đã đăng ký.',
  },
  'consent.button.idle': {
    ko: '내 위치 확인하고 가까운 대피소 찾기',
    vi: 'Xác nhận vị trí của tôi và tìm nơi trú ẩn gần',
  },
  'consent.button.requesting': {
    ko: '위치를 확인하는 중…',
    vi: 'Đang xác nhận vị trí…',
  },
  'consent.button.done': {
    ko: '위치 확인 완료',
    vi: 'Đã xác nhận vị trí',
  },
  'consent.button.denied': {
    ko: '위치를 쓸 수 없어요',
    vi: 'Không thể dùng vị trí',
  },
  'consent.button.unavailable': {
    ko: '위치를 쓸 수 없어요',
    vi: 'Không thể dùng vị trí',
  },
  'consent.note.denied': {
    ko: '위치를 쓸 수 없어요. 브라우저 설정에서 위치 권한을 허용하면 다음에 쓸 수 있어요. 지금은 등록된 주소 기준으로 대피소를 안내해요.',
    vi: 'Không thể dùng vị trí. Nếu bạn cho phép quyền vị trí trong cài đặt trình duyệt, lần sau sẽ dùng được. Hiện đang hướng dẫn nơi trú ẩn theo địa chỉ đã đăng ký.',
  },
  'consent.note.unavailable': {
    ko: '위치를 쓸 수 없어요. 지금은 등록된 주소 기준으로 대피소를 안내해요.',
    vi: 'Không thể dùng vị trí. Hiện đang hướng dẫn nơi trú ẩn theo địa chỉ đã đăng ký.',
  },
  'consent.aria.button': {
    ko: '현재 위치 1회 확인하기',
    vi: 'Xác nhận vị trí hiện tại 1 lần',
  },
  'chat.sectionLabel': {
    ko: '추가 질문',
    vi: 'Câu hỏi thêm',
  },
  'chat.toggle.open': {
    ko: '💬 질문창 닫기',
    vi: '💬 Đóng ô câu hỏi',
  },
  'chat.toggle.closed': {
    ko: '💬 더 궁금한 점 질문하기',
    vi: '💬 Hỏi thêm điều thắc mắc',
  },
  'chat.status.searching': {
    ko: '답변을 찾는 중…',
    vi: 'Đang tìm câu trả lời…',
  },
  'chat.quickListLabel': {
    ko: '빠른 질문',
    vi: 'Câu hỏi nhanh',
  },
  'chat.quickExhausted': {
    ko: '미리 준비된 질문을 모두 사용하셨어요. 아래 칸에 직접 입력해 주세요.',
    vi: 'Bạn đã dùng hết câu hỏi chuẩn bị sẵn. Vui lòng tự nhập vào ô bên dưới.',
  },
  'chat.inputLabel': {
    ko: '무엇이든 물어보세요 (예: "침수하면 어디로 가요?")',
    vi: 'Hỏi bất cứ điều gì (ví dụ: "Ngập nước thì đi đâu?")',
  },
  'chat.placeholder': {
    ko: '질문을 입력하세요',
    vi: 'Nhập câu hỏi',
  },
  'chat.send': {
    ko: '질문 보내기',
    vi: 'Gửi câu hỏi',
  },
  'chat.sendBusy': {
    ko: '답변 준비 중…',
    vi: 'Đang chuẩn bị câu trả lời…',
  },
  'chat.errorPrefix': {
    ko: '답변을 가져오지 못했습니다:',
    vi: 'Không tải được câu trả lời:',
  },
  'chat.retry': {
    ko: '다시 시도',
    vi: 'Thử lại',
  },
  'chat.refusal.no_evidence': {
    ko: '확인된 지침이 없습니다',
    vi: 'Không có chỉ dẫn đã được xác nhận',
  },
  'chat.refusal.out_of_scope': {
    ko: '이번 재난과 관련된 질문에만 답할 수 있습니다',
    vi: 'Chỉ có thể trả lời các câu hỏi liên quan đến thảm họa lần này',
  },
  'chat.refusal.unsafe': {
    ko: '이 질문에는 답하기 어렵습니다',
    vi: 'Khó trả lời câu hỏi này',
  },
  'chat.refusal.fallback': {
    ko: '이 질문에는 안전하게 인용할 수 있는 공식 지침이 없습니다.',
    vi: 'Không có chỉ dẫn chính thức nào có thể trích dẫn an toàn cho câu hỏi này.',
  },
  'chat.refusal.emergency': {
    ko: '위급하다면 즉시 구급·구조를 요청하거나 보호자에게 연락하세요.',
    vi: 'Trong tình huống khẩn cấp, hãy gọi cấp cứu hoặc liên hệ người bảo vệ ngay.',
  },
  'chat.followup.askMore': {
    ko: '다른 것도 물어볼래요',
    vi: 'Tôi muốn hỏi thêm điều khác',
  },
  'chat.followup.reshelter': {
    ko: '대피소 다시 보기',
    vi: 'Xem lại nơi trú ẩn',
  },
  'chat.quick.goOut': {
    ko: '지금 나가도 되나요?',
    vi: 'Bây giờ ra ngoài được không?',
  },
  'chat.quick.pet': {
    ko: '반려동물은 어떻게 하나요?',
    vi: 'Phải làm gì với thú cưng?',
  },
  'chat.quick.upperFloor': {
    ko: '위층으로 올라가도 되나요?',
    vi: 'Lên tầng trên được không?',
  },
  'chat.quick.familyCare': {
    ko: '혼자 못 움직이는 가족이 있어요',
    vi: 'Có người nhà không tự di chuyển được',
  },
  'chat.quick.alone': {
    ko: '혼자 있는데 어떻게 하나요?',
    vi: 'Tôi ở một mình, phải làm sao?',
  },
  'join.loading': {
    ko: '등록 정보를 불러오는 중입니다…',
    vi: 'Đang tải thông tin đăng ký…',
  },
  'join.notFound.title': {
    ko: '등록 정보를 찾을 수 없습니다.',
    vi: 'Không tìm thấy thông tin đăng ký.',
  },
  'join.notFound.body': {
    ko: '이 화면은 보호자·복지관이 먼저 등록한 뒤 보여주는 QR 코드로만 열 수 있습니다. QR 코드를 다시 스캔해 주세요. 문제가 계속되면 보호자에게 연락해 주세요.',
    vi: 'Màn hình này chỉ mở được qua mã QR do người bảo hộ hoặc trung tâm phúc lợi tạo sau khi đăng ký. Vui lòng quét lại mã QR. Nếu vẫn gặp vấn đề, hãy liên hệ người bảo hộ.',
  },
  'join.confirm.title': {
    ko: 'SAVERS 알림 등록',
    vi: 'Đăng ký thông báo SAVERS',
  },
  'join.confirm.askAccept': {
    ko: '재난 안전 알림을 받으시겠어요?',
    vi: 'Bạn có muốn nhận thông báo an toàn thảm họa không?',
  },
  'join.confirm.nameConfirm': {
    ko: '{name}님, 맞으신가요?',
    vi: 'Bạn là {name}, đúng không?',
  },
  'join.confirm.acceptButton': {
    ko: '알림 받기',
    vi: 'Nhận thông báo',
  },
  'join.confirm.explainer': {
    ko: '알림을 켜면 호우·침수 등 재난 상황이 발생했을 때 이 폰으로 안내 문자를 받아볼 수 있습니다.',
    vi: 'Khi bật thông báo, bạn sẽ nhận được tin nhắn hướng dẫn trên điện thoại này khi xảy ra thảm họa như mưa lớn, ngập nước.',
  },
  'join.working': {
    ko: '알림을 준비하는 중입니다…',
    vi: 'Đang chuẩn bị thông báo…',
  },
  'join.conflict.title': {
    ko: '이미 다른 폰이 등록되어 있습니다.',
    vi: 'Đã có điện thoại khác đăng ký.',
  },
  'join.conflict.askReplace': {
    ko: '이 폰으로 바꾸시겠어요?',
    vi: 'Bạn có muốn đổi sang điện thoại này không?',
  },
  'join.conflict.replaceDetail': {
    ko: '바꾸면 안전 알림이 이 폰으로 도착하고, 이전에 등록한 폰에서는 받을 수 없습니다.',
    vi: 'Nếu đổi, thông báo an toàn sẽ đến điện thoại này và điện thoại cũ sẽ không nhận được nữa.',
  },
  'join.conflict.replaceButton': {
    ko: '바꾸기',
    vi: 'Đổi',
  },
  'join.conflict.keepButton': {
    ko: '그만두기',
    vi: 'Giữ nguyên',
  },
  'join.done.title': {
    ko: '등록되었습니다.',
    vi: 'Đã đăng ký.',
  },
  'join.done.body': {
    ko: '이제 재난 알림이 이 폰으로 도착합니다. 화면은 닫으셔도 됩니다.',
    vi: 'Bây giờ thông báo thảm họa sẽ đến điện thoại này. Bạn có thể đóng màn hình.',
  },
  'join.kept.title': {
    ko: '이전 폰을 그대로 유지합니다.',
    vi: 'Giữ nguyên điện thoại cũ.',
  },
  'join.kept.body': {
    ko: '안전 알림은 계속 이전에 등록한 폰으로 도착합니다. 이 화면은 닫으셔도 됩니다.',
    vi: 'Thông báo an toàn vẫn tiếp tục đến điện thoại đã đăng ký trước đó. Bạn có thể đóng màn hình.',
  },
  'join.denied.title': {
    ko: '알림이 거부되어 있습니다.',
    vi: 'Thông báo đã bị từ chối.',
  },
  'join.denied.body': {
    ko: '한 번 거부한 알림 권한은 이 화면에서 다시 켤 수 없습니다. 브라우저 설정에서 알림을 다시 허용해 주세요.',
    vi: 'Quyền thông báo đã từ chối không thể bật lại từ màn hình này. Vui lòng bật lại trong cài đặt trình duyệt.',
  },
  'join.denied.recoveryAndroid': {
    ko: '예(안드로이드 크롬): 주소창 왼쪽 아이콘 → 권한 → 알림 → 허용.',
    vi: 'Ví dụ (Chrome Android): biểu tượng bên trái thanh địa chỉ → Quyền → Thông báo → Cho phép.',
  },
  'join.denied.recoveryIos': {
    ko: '예(아이폰 사파리): 설정 → 사파리 → 위치/알림 → 해당 사이트 허용.',
    vi: 'Ví dụ (Safari iPhone): Cài đặt → Safari → Vị trí/Thông báo → Cho phép trang web này.',
  },
  'join.denied.rescan': {
    ko: '알림을 다시 켠 뒤 이 QR 코드를 다시 스캔해 주세요.',
    vi: 'Sau khi bật lại thông báo, vui lòng quét lại mã QR này.',
  },
  'join.error.title': {
    ko: '알림을 등록하지 못했습니다.',
    vi: 'Không thể đăng ký thông báo.',
  },
  'join.error.retry': {
    ko: '다시 시도',
    vi: 'Thử lại',
  },
  'join.error.unavailable': {
    ko: '알림을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    vi: 'Không thể sử dụng thông báo. Vui lòng thử lại sau.',
  },
  'join.error.timeout': {
    ko: '연결이 오래 걸리고 있습니다. 잠시 후 다시 시도해 주세요.',
    vi: 'Kết nối đang mất nhiều thời gian. Vui lòng thử lại sau.',
  },
  'join.iosNotice.title': {
    ko: '아이폰에서 알림을 받으려면 홈 화면에 추가해 주세요.',
    vi: 'Để nhận thông báo trên iPhone, vui lòng thêm vào màn hình chính.',
  },
  'join.iosNotice.body': {
    ko: '아이폰은 홈 화면에 추가한 뒤에야 재난 알림을 받을 수 있습니다. 지금처럼 사파리에서 연 화면으로는 알림이 오지 않습니다.',
    vi: 'iPhone chỉ nhận được thông báo thảm họa sau khi được thêm vào màn hình chính. Nếu mở qua Safari như hiện tại, thông báo sẽ không đến.',
  },
  'join.iosNotice.steps': {
    ko: '추가 방법: 화면 아래 공유 버튼 → "홈 화면에 추가"',
    vi: 'Cách thêm: nút Chia sẻ ở dưới màn hình → "Thêm vào màn hình chính"',
  },
  'join.iosNotice.helper': {
    ko: '옆에 계신 보호자·복지 담당자가 대신 해주실 수 있습니다.',
    vi: 'Người bảo hộ hoặc nhân viên phúc lợi bên cạnh có thể làm thay cho bạn.',
  },
  'shelter.map.loading': {
    ko: '지도를 불러오는 중…',
    vi: 'Đang tải bản đồ…',
  },
  'shelter.map.error': {
    ko: '지도를 불러오지 못했습니다. 아래 거리·방향 안내를 이용해 주세요.',
    vi: 'Không tải được bản đồ. Vui lòng dùng hướng dẫn khoảng cách · hướng bên dưới.',
  },
  'speak.read': {
    ko: '🔊 읽어주기',
    vi: '🔊 Đọc to',
  },
  'speak.stop': {
    ko: '⏹ 멈추기',
    vi: '⏹ Dừng',
  },
  'speak.aria.read': {
    ko: '본문 소리 내어 읽어주기',
    vi: 'Đọc to nội dung',
  },
  'speak.aria.stop': {
    ko: '읽어주기 멈추기',
    vi: 'Dừng đọc to',
  },
  // {current}/{total} — 지금 펼친 문장 수 / 전체 문장 수.
  'easyText.next': {
    ko: '다음 ({current}/{total})',
    vi: 'Tiếp ({current}/{total})',
  },
  'easyText.allRevealed': {
    ko: '모두 보여드렸습니다',
    vi: 'Đã hiển thị toàn bộ',
  },
}

// ---- lookup ----------------------------------------------------------

// Resolves a UI string for a given key + language. Vietnamese is returned
// only when lang === 'vi' AND the entry has a `vi` field. zh and en are
// accepted (the contract lists them) but have no UI translations, so they
// fall back to Korean — with a console.warn so the developer is informed
// the screen is not rendering in the profile's language. Any other value
// (null, undefined, 'ko') also resolves to Korean silently.
//
// The fallback is intentional and total: an unsupported language never
// renders `undefined` or a hole, it renders Korean.
//
// Optional `params` substitutes `{name}` placeholders in the resolved
// string (single-pass, no nested brace handling). Missing params are left
// untouched — callers always supply every placeholder a key uses.
export function t(
  key: StringKey,
  lang: Language | undefined | null,
  params?: Record<string, string | number>,
): string {
  const entry = DICTIONARY[key]
  const value = resolveEntry(entry, lang, key)
  if (params === undefined) return value
  return substituteParams(value, params)
}

// Resolution core, separated so the zh/en warning fires exactly once per
// call. Vietnamese is the only non-Korean language with translations today.
function resolveEntry(
  entry: DictionaryEntry,
  lang: Language | undefined | null,
  key: StringKey,
): string {
  if (lang === 'vi' && entry.vi !== undefined) {
    return entry.vi
  }
  if (lang === 'zh' || lang === 'en') {
    // The contract allows these languages but UI translations are out of
    // scope. Warn so the developer knows the screen rendered Korean instead
    // of the profile's language — the fallback must not be silent.
    if (import.meta.env.DEV) {
      console.warn(
        `[i18n] No UI translation for language "${lang}" (key: "${key}"). ` +
          'Falling back to Korean. Add translations or narrow the Language union.',
      )
    }
  }
  return entry.ko
}

function substituteParams(
  template: string,
  params: Record<string, string | number>,
): string {
  let out = template
  for (const [name, val] of Object.entries(params)) {
    out = out.split(`{${name}}`).join(String(val))
  }
  return out
}

// ---- enum label maps (presentation only) -----------------------------
//
// These present the underlying enum values (source of truth lives in
// api/types.ts). Each is split by language so a Vietnamese screen never
// shows a Korean label mid-sentence.

export function housingLabel(housing: Housing, lang: Language | undefined | null): string {
  const map: Record<Housing, { ko: string; vi: string }> = {
    banjiha: { ko: '반지하', vi: 'tầng hầm' },
    lowland: { ko: '저지대 주택', vi: 'nhà vùng trũng' },
    normal: { ko: '일반 주택', vi: 'nhà thông thường' },
  }
  const e = map[housing]
  return lang === 'vi' ? e.vi : e.ko
}

export function mobilityLabel(mobility: Mobility, lang: Language | undefined | null): string {
  const map: Record<Mobility, { ko: string; vi: string }> = {
    ok: { ko: '거동 가능', vi: 'di chuyển được' },
    slow: { ko: '보행 느림', vi: 'đi chậm' },
    assisted: { ko: '보조기/휠체어', vi: 'dụng cụ hỗ trợ/Xe lăn' },
  }
  const e = map[mobility]
  return lang === 'vi' ? e.vi : e.ko
}

export function visionLabel(vision: Vision, lang: Language | undefined | null): string {
  const map: Record<Vision, { ko: string; vi: string }> = {
    ok: { ko: '시력 정상', vi: 'thị lực bình thường' },
    low: { ko: '시력 저하', vi: 'thị lực giảm' },
    blind: { ko: '시각장애', vi: 'khiếm thị' },
  }
  const e = map[vision]
  return lang === 'vi' ? e.vi : e.ko
}

export function hearingLabel(hearing: Hearing, lang: Language | undefined | null): string {
  const map: Record<Hearing, { ko: string; vi: string }> = {
    ok: { ko: '청력 정상', vi: 'thính lực bình thường' },
    bad: { ko: '청력 저하', vi: 'thính lực giảm' },
  }
  const e = map[hearing]
  return lang === 'vi' ? e.vi : e.ko
}

// 8-point compass bearing label. The spec sends a Bearing enum
// ('N'|'NE'|...), not a degree number, so this is a direct lookup.
// Returns null when bearing is null (no direction known).
export function bearingLabel(
  bearing: Bearing | null,
  lang: Language | undefined | null,
): string | null {
  if (bearing === null) {
    return null
  }
  const map: Record<Bearing, { ko: string; vi: string }> = {
    N: { ko: '북', vi: 'Bắc' },
    NE: { ko: '북동', vi: 'Đông Bắc' },
    E: { ko: '동', vi: 'Đông' },
    SE: { ko: '남동', vi: 'Đông Nam' },
    S: { ko: '남', vi: 'Nam' },
    SW: { ko: '남서', vi: 'Tây Nam' },
    W: { ko: '서', vi: 'Tây' },
    NW: { ko: '북서', vi: 'Tây Bắc' },
  }
  const e = map[bearing]
  // Vietnamese bearings read naturally without a suffix; Korean appends
  // "-쪽" ("toward <dir>"). The suffix is language-specific so the rendered
  // phrase is grammatical in each language.
  return lang === 'vi' ? e.vi : `${e.ko}쪽`
}

// Distance formatter. Numbers are rendered with locale-aware grouping so a
// Vietnamese screen does not show Korean digit grouping. Below 1km we show
// meters; at/above 1km we show one-decimal kilometers.
export function formatDistance(
  m: number,
  lang: Language | undefined | null,
): string {
  const locale = lang === 'vi' ? 'vi-VN' : 'ko-KR'
  if (m < 1000) {
    const rounded = Math.round(m / 10) * 10
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(rounded) + 'm'
  }
  const km = m / 1000
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }).format(km) + 'km'
}

// Exclusion-reason label (ShelterList.excluded[].reason). Short noun-phrase
// labels that read naturally inside the exclusion summary.
export function excludedReasonLabel(
  reason: 'underground' | 'closed' | 'unreachable',
  lang: Language | undefined | null,
): string {
  const map: Record<'underground' | 'closed' | 'unreachable', { ko: string; vi: string }> = {
    underground: { ko: '지하 침수 위험', vi: 'nguy cơ ngập dưới đất' },
    closed: { ko: '운영 중단', vi: 'ngừng hoạt động' },
    unreachable: { ko: '가는 길 위험', vi: 'đường đến nguy hiểm' },
  }
  const e = map[reason]
  return lang === 'vi' ? e.vi : e.ko
}

// Count-unit suffix — "곳" (Korean) / "nơi" (Vietnamese). Used when listing
// excluded shelters and in "그 외 N곳" / "khác N nơi".
export function countUnit(lang: Language | undefined | null): string {
  return lang === 'vi' ? 'nơi' : '곳'
}

// ---- document language mirroring -------------------------------------

// Mirror the active UI language to <html lang="..."> at runtime so screen
// readers (TalkBack / NVDA / VoiceOver) pick the right pronunciation engine.
// index.html ships statically as lang="ko"; this corrects it to "vi" when a
// Vietnamese-profile screen is rendered. Idempotent — calling with the same
// language is a no-op write.
export function applyDocumentLanguage(lang: Language | undefined | null): void {
  if (typeof document === 'undefined') return
  // Only vi gets a non-ko document language today. zh/en profiles render
  // Korean UI (no translations shipped), so the document stays lang="ko"
  // to keep screen readers on the Korean pronunciation engine.
  const htmlLang = lang === 'vi' ? 'vi' : 'ko'
  // Direct property assignment (document.documentElement.lang = ...) rather
  // than setAttribute — screen readers look for the property form. This is
  // idempotent: assigning the same value is a no-op in practice, and the
  // guard avoids unnecessary DOM writes.
  if (document.documentElement.lang !== htmlLang) {
    document.documentElement.lang = htmlLang
  }
}

// ---- inline proper-noun language tagging -----------------------------
//
// When the screen language is not Korean (e.g. Vietnamese) but a piece of
// DATA on that screen is a Korean proper noun — a shelter name, an address,
// a registered dong name — a screen reader running in Vietnamese mode would
// apply Vietnamese phonetics to the Korean characters and make the very
// information the user must reach unintelligible. Wrapping that text in an
// inline element carrying lang="ko" tells the screen reader (and any TTS
// that respects the DOM language) to switch to the Korean pronunciation
// engine for that run, while the visible text is unchanged.
//
// IMPORTANT — these helpers are NO-OPS on a Korean screen. The document is
// already lang="ko", so adding lang="ko" again on every shelter name would
// be redundant noise for a Korean screen-reader user. Each call site guards
// the wrapping with an explicit screen-language check so the wrap only
// happens when lang !== 'ko'.
//
// Proper nouns are DATA, not UI copy: they are never translated. Wrapping
// changes an attribute only; the visible text is byte-for-byte the same
// string the server/mock returned.

// Wrap an inline run of Korean proper-noun text in a lang="ko" span. Caller
// is responsible for the screen-language condition (see callers in
// ShelterGuide / ShelterMap / Join): on a Korean screen the caller passes
// the raw text through instead, so this component is only mounted where the
// screen language is not Korean.
export function KoreanSpan({ children }: { children: ReactNode }): ReactNode {
  return createElement('span', { lang: 'ko' }, children)
}
