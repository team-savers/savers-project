// Mock chat replies. Keyword-matched canned answers; the mock adapter
// searches this list in order and returns the first match.
//
// Fixture mix:
//   - 3~4 evidence-backed replies with sources populated
//   - 1 evidence-less case: answer null + refusalReason "no_evidence" + []
//
// Source quotes are demo adaptations of 행정안전부 국민행동요령 patterns and
// are clearly labeled as such with a single uniform tag — they are demo
// fixtures, not the actual official manual text. Real retrieval happens in
// apps/ai-engine.
//
// LANGUAGE COVERAGE: each rule carries replies in BOTH Korean and
// Vietnamese. The mock adapter selects based on `req.locale` so a
// Vietnamese speaker asking a question receives a Vietnamese answer — this
// is the path the Vietnamese persona exercises end-to-end. Source
// quotes (국민행동요령 / official guidance) stay in Korean because they are
// demo adaptations written to mirror Korean official guidance; the
// conversational `answer` field is what the resident reads, and that is
// localized.

import type { ChatResponse, Language } from '../api/types'

export interface ChatRule {
  // Short identifier for the rule (declared as id: string), used for
  // debugging. Stays stable across edits so log output can distinguish
  // "rules were split" from "rules were deleted".
  id: string
  // Keywords matched by the adapter against the question. First match wins.
  // The match is word-aware, not a raw substring test, so a single syllable
  // cannot trigger a rule from inside an unrelated longer word (e.g. the
  // syllable "물" inside "반려동물"). Korean and Vietnamese keyword stems
  // are listed together so a question in either language hits the same rule.
  keywords: string[]
  // Per-language reply. Korean is always present; Vietnamese is present for
  // the two demo languages that have UI translations today. zh/en fall back
  // to Korean at the adapter layer (see mock.ts postChat), so only ko is
  // required in each entry. `Partial` lets the table ship ko+vi without
  // inventing zh/en translations.
  reply: Partial<Record<Language, ChatResponse>> & { ko: ChatResponse }
}

export const CHAT_RULES: ChatRule[] = [
  {
    id: 'flood-basement',
    // Korean: 침수/잠긴/물이/반지하 ; Vietnamese: ngập/nước/tầng hầm
    // "물이" (not the bare syllable "물") so "반려동물" cannot collide: a
    // flood question attaches the subject particle (물이 들어와요 / 물이
    // 차올라요), while 반려동물 takes 은/는 and never "물이" as a stem.
    keywords: [
      '침수', '잠긴', '물이', '반지하',
      'ngập', 'nước', 'tầng hầm', 'ngap',
    ],
    reply: {
      ko: {
        answer:
          '반지나 지하에 계시면 즉시 위층으로 대피하세요. 물이 들어오기 전에 나가는 것이 가장 중요합니다.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] 국민행동요령 — 호우·도시침수',
            quote:
              '반지하 또는 지하실에 거주하는 사람은 침수 위험이 있으니 즉시 위층 또는 인근 높은 건물로 대피한다.',
          },
        ],
      },
      vi: {
        answer:
          'Nếu bạn ở tầng hầm hoặc bán hầm, hãy di chuyển ngay lên tầng trên. Việc ra khỏi đó trước khi nước chảy vào là quan trọng nhất.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] Hướng dẫn ứng phó — Bộ Hành chính và An toàn',
            quote:
              'Người dân ở khu vực có nguy cơ ngập nước (tầng hầm, vùng trũng) phải lập tức di chuyển lên tầng trên hoặc đến tòa nhà cao gần nhất.',
          },
        ],
      },
    },
  },
  {
    id: 'shelter-location',
    // Korean: 대피소/대피/어디/쉼터 ; Vietnamese: nơi trú ẩn/đi đâu/trú ẩn
    keywords: [
      '대피소', '대피', '어디', '쉼터',
      'nơi trú ẩn', 'nơi trú', 'trú ẩn', 'đi đâu', 'đi đâu',
    ],
    reply: {
      ko: {
        answer:
          '가까운 대피소는 안내 화면에서 확인하세요. 휠체어를 쓰시거나 계단이 어려우시면 층이 없는 곳을 먼저 안내해 드립니다.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] 국민행동요령 — 대피소 이용',
            quote:
              '거동이 불편한 사람은 계단이 없는 1층 대피소를 우선 이용하며, 시설 담당자에게 상황을 알린다.',
          },
          {
            title: '[demo] 임시주거 시설 안내',
            quote:
              '호우 시 주민센터 및 인근 학교 체육관을 임시 대피 장소로 운영한다.',
          },
        ],
      },
      vi: {
        answer:
          'Vui lòng xem nơi trú ẩn gần nhất trên màn hình hướng dẫn. Nếu bạn đi xe lăn hoặc gặp khó khăn với cầu thang, nơi không có tầng sẽ được ưu tiên hướng dẫn trước.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] Hướng dẫn — sử dụng nơi trú ẩn',
            quote:
              'Người gặp khó khăn khi di chuyển ưu tiên sử dụng nơi trú ẩn ở tầng trệt không có cầu thang và báo tình hình cho người phụ trách cơ sở.',
          },
          {
            title: '[demo] Hướng dẫn cơ sở tạm trú',
            quote:
              'Trung tâm dân cư và nhà thi đấu trường học gần đó được vận hành làm nơi trú ẩn tạm thời khi có mưa lớn.',
          },
        ],
      },
    },
  },
  {
    id: 'emergency-contact',
    // Korean: 구조/도와/살려/연락 ; Vietnamese: cứu/help/gọi/cấp cứu
    keywords: [
      '구조', '도와', '살려', '연락',
      'cứu', 'giúp', 'gọi', 'cấp cứu',
    ],
    reply: {
      ko: {
        answer:
          '위급한 상황이면 즉시 신고 기관에 연락하세요. 위치를 알 수 없으면 등록된 주소(서원동)를 함께 알려 주세요.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] 국민행동요령 — 위급 신고',
            quote:
              '생명에 위험이 있는 경우 즉시 신고 기관에 신고하며, 위치를 모를 때는 주변 표지판이나 등록된 주소를 함께 알린다.',
          },
        ],
      },
      vi: {
        answer:
          'Trong tình huống khẩn cấp, hãy gọi ngay cơ quan chức năng. Nếu không biết vị trí, vui lòng cung cấp thêm địa chỉ đã đăng ký (Seowon-dong).',
        refusalReason: null,
        sources: [
          {
            title: '[demo] Hướng dẫn — báo cáo khẩn cấp',
            quote:
              'Khi có nguy hiểm đến tính mạng, báo ngay cho cơ quan chức năng; nếu không biết vị trí, hãy cung cấp biển báo xung quanh hoặc địa chỉ đã đăng ký.',
          },
        ],
      },
    },
  },
  {
    id: 'already-happened-unsafe',
    // 이미 일어난/진행 중 상황 — 침수된 전기 설비, 현재 진행 중인 화재.
    // Korean: 잠겼/잠긴/불이 났어요/불이 나고 있어요/이미 ; Vietnamese:
    // ngập rồi/đang cháy/đã chập. 이 시제에는 설비를 만지라는 지시를
    // 반환하지 않는다 — 이미 물에 잠긴 차단기를 내리거나 불이 난 곳으로
    // 돌아가라는 지시는 사상 사고로 이어진다. 근거 인용문의 조건(「침수가
    // 예상되면」)이 이 시제에는 해당하지 않는다. 안전하게 인용할 수 있는
    // 사전 승인된 지침이 없으므로 거절한다(answer: null, refusalReason:
    // 'unsafe'). 이 값은 팀 계약에 있는 정상 응답이다.
    keywords: [
      '잠겨', '잠긴', '잠겼', '불이 났', '났어요', '나고 있', '타고 있',
      '이미',
      'đã cháy', 'đang cháy', 'ngập rồi', 'đã ngập', 'chập rồi',
    ],
    reply: {
      ko: {
        answer: null,
        refusalReason: 'unsafe',
        sources: [],
      },
      vi: {
        answer: null,
        refusalReason: 'unsafe',
        sources: [],
      },
    },
  },
  {
    id: 'preventive-utility',
    // 예상/대비 질문 — 아직 침수·화재가 아니지만 대비 방법을 묻는 경우.
    // Korean: 전기/단전/가스 (시제 표시 없음 = 예방 질문) ;
    // Vietnamese: điện/ga (phòng ngừa). 이 경우에만 「침수가 예상되면」
    // 조건의 근거 인용문이 해당하며, 미리 차단기를 내리고 가스를 잠그는
    // 대비 지시를 반환한다. 이미 일어남 규칙이 위에서 먼저 매치되므로
    // 이 규칙은 정말 예방 질문일 때만 도달한다.
    keywords: [
      '전기', '단전', '가스',
      'điện', 'ga',
    ],
    reply: {
      ko: {
        answer:
          '집을 비우시기 전에 전기 차단기를 내리고, 가스 밸브를 잠가 주세요. 침수 시 감전 위험이 큽니다.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] 국민행동요령 — 호우 시 시설 점검',
            quote:
              '침수가 예상되면 메인 차단기를 내리고 가스 밸브를 잠근 뒤 대피한다. 감전 우려가 있으니 물에 잠긴 콘센트에 손을 대지 않는다.',
          },
        ],
      },
      vi: {
        answer:
          'Trước khi rời nhà, vui lòng ngắt cầu dao điện và đóng van gas. Khi ngập nước, nguy cơ điện giật rất lớn.',
        refusalReason: null,
        sources: [
          {
            title: '[demo] Hướng dẫn — kiểm tra thiết bị khi mưa lớn',
            quote:
              'Khi có nguy cơ ngập, hãy ngắt cầu dao chính, đóng van gas rồi mới di tản. Có nguy cơ điện giật, không chạm vào ổ cắm đã chìm trong nước.',
          },
        ],
      },
    },
  },
  // Default / no-evidence case. Anything that did not match a rule above.
  // The refusal answer is null in both languages; refusalReason carries no
  // localized string (the UI maps the reason code to a localized message
  // via the i18n dictionary), so a single ChatResponse shape works for both.
  {
    id: 'no-evidence-default',
    keywords: [],
    reply: {
      ko: {
        answer: null,
        refusalReason: 'no_evidence',
        sources: [],
      },
      vi: {
        answer: null,
        refusalReason: 'no_evidence',
        sources: [],
      },
    },
  },
]
