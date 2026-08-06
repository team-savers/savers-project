# apps/frontend — SAVERS PWA

SAVERS 사용자 터미널 화면을 담당한다. React + Vite + TypeScript + PWA(FCM 웹푸시).

## 라우트

| 경로 | 화면 | 파일 |
|------|------|------|
| `/` | 홈 (진입 안내) | `src/App.tsx` (HomeView) |
| `/demo` | 푸시 데모 + 페르소나 선택 | `src/App.tsx` (DemoView) |
| `/a?t=<token>` | 재난 알림 랜딩 — 맞춤 행동 안내 + 대피소 + 챗봇 | `src/pages/Landing.tsx` |
| `/ops` | 운영자 대리 등록 (보호자/복지관/고용주가 피보호자 등록) | `src/pages/Ops.tsx` |
| `/join?u=<userId>` | 피보호자 폰 온보딩 (QR 스캔 → FCM 토큰 연결) | `src/pages/Join.tsx` |

라우팅은 `window.location.pathname` 기반이다. 라우터 라이브러리를 쓰지 않는다.

## 폴더 구조

```
src/
  api/
    types.ts        — 팀 계약(openapi.yaml) 스키마 변환 (프론트 전용 필드는 별도 표시)
    client.ts       — 컴포넌트가 import 하는 유일한 API 진입점 (mock/http 전환)
    mock.ts         — mock 어댑터 (200–600ms 지연, fixture 데이터)
    http.ts         — 실제 HTTP 어댑터 자리. 지금은 모든 메서드가 예외를 던진다(백엔드 엔드포인트 미구현). VITE_USE_MOCK=false 일 때 활성화되지만, 배선되기 전에는 호출 즉시 실패한다.
    firestore.ts    — /ops↔/join 크로스디바이스 브리지 (임시, env 4종 모두 있어야 활성)
  lib/
    i18n.ts         — 다국어 UI 사전 (ko/vi), 방향·거리·제외 사유 등 표시 헬퍼
    readability.ts  — 쉬운 공공언어 치환 (행정용어 → 일상용어), 가독성 측정
    kakaoMap.ts     — 카카오맵 JS SDK 지연 로더 (첫 확장 시 1회만 로드)
    push.ts         — FCM 토큰 발급 · 포그라운드 메시지 구독
    swUpdate.ts     — 서비스워커 업데이트 감지
  pages/
    Landing.tsx     — 재난 알림 랜딩 화면
    Ops.tsx         — 운영자 대리 등록 화면
    Join.tsx        — 피보호자 폰 온보딩
  components/
    ShelterGuide.tsx — 대피소 안내 (위치 동의 3갈래 분기, 인라인 지도·상세)
    EasyText.tsx     — 메시지 본문 카드 (쉬운 말 치환 본문 + 읽어주기 + 큰 글씨/근거 원문 토글)
    ChatDock.tsx     — 추가 질문 챗봇 (빠른 질문 + 자유 입력)
    LocationConsent.tsx — 사용자가 직접 누를 때만 1회 위치 확인하는 동의 카드
    ShelterMap.tsx   — 카카오맵 인라인 지도 (비전시 사용자는 렌더되지 않음)
    SpeakButton.tsx  — 본문 음성 낭독 (내장 speechSynthesis)
  mocks/
    profiles.ts     — 11인 데모 페르소나
    shelters.ts     — 대피소 fixture (상황별 분기)
    chatReplies.ts  — 챗봇 canned 응답 규칙 (원문은 각색)
    adminDong.ts    — 행정동 코드 (데모 범위)
  App.tsx           — 앱 셸, 라우팅, 포그라운드 푸시 배너
  sw.ts             — 서비스워커 (Workbox + FCM 백그라운드 메시지)
```

## 데이터 소스

- **mock 어댑터가 기본.** `VITE_USE_MOCK=false` 로 설정하지 않으면 `src/api/mock.ts` 의 fixture 데이터가 쓰인다. 200–600ms 인공 지연으로 로딩 상태가 실제로 보인다.
- **쉬운 말 치환.** 본문 자리에는 한국어 화면에서 행정용어를 일상용어로 바꾼 «치환본»을 보여준다(`src/lib/readability.ts` 의 `substituteAdminTerms`). 베트남어 화면에서는 사전이 없으므로 서버가 만든 `message.body` 원문을 그대로 본문으로 쓴다. 음성 낭독(SpeakButton)은 화면에 보이는 문장(치환본 또는 원문)을 읽는다 — 시각 채널과 음성 채널이 같은 문장을 말한다. «원문 보기» 버튼은 치환 전 원문이 아니라 RAG 근거 출처(sources)를 펼치고, «크게 보기»는 본문 글씨를 22px → 34px 로 키운다.
- **대피소 가용성 상태.** `ok` · `all_excluded` · `cache_only` · `upstream_unavailable` 네 가지 상태가 fixture 에 모두 포함돼 있다 (`src/mocks/shelters.ts`).

## 실행 방법

```bash
cd apps/frontend
npm ci
npm run dev        # 개발 서버 (포트 3000)
npm run lint       # oxlint
npm run typecheck  # tsc --noEmit (app·sw·node·scripts 4패스)
npm run build      # 프로덕션 빌드
```

### 명확성 지표 채점 (제출 산출물)

용어 치환율(KPI ≥90%)을 파일로 뽑는 스크립트가 `scripts/measure-clarity.ts`에 있다.
입력은 ai-engine 채점기의 보고서다 — 같은 문안을 두 채점기가 나눠 채점해
케이스·문안·사전이 각각 하나만 존재하게 한다. 실행 순서와 채점 의미는
[apps/ai-engine/eval/README.md](../ai-engine/eval/README.md)
"명확성 지표가 절반만 여기 있는 이유" 절 참조. Node >= 22.18 필요
(타입 스트리핑으로 .ts를 직접 실행).

```bash
npm run eval:clarity -- --in ../ai-engine/eval/reports/grounding_report.json
```

## 알림 채널

1차 알림 채널은 웹푸시(FCM)이다. 카카오 알림톡은 예선·본선 모두 채택하지 않는다 — ADR-0005 참조.

- 알림 액션 버튼에 의존하지 않는다 (플랫폼별 최대 2개 제한). 알림은 제목+본문+탭 → 랜딩 진입으로 단순화한다.
- 서비스워커는 1개다. FCM의 `firebase-messaging-sw.js` 와 vite-plugin-pwa 의 SW가 같은 스코프에서 충돌하므로, `strategies: 'injectManifest'` + 커스텀 `src/sw.ts` 안에서 Workbox 캐싱과 `onBackgroundMessage`를 함께 처리한다.

### 시연 환경 제약

- **안드로이드 크롬 / 데스크톱 크롬 고정.** iOS 웹푸시는 16.4+ 및 홈 화면 추가(A2HS) 상태에서만 동작한다.
- **웹푸시는 localhost를 제외하면 HTTPS가 필수.** 안드로이드 실기기 검증에는 배포된 HTTPS URL이 필요하다.

## 설계 제약

- 취약계층 본인에게 설치·설정 부담을 지우지 않는다. 등록은 보호자/복지관/지자체가 대행 (`/ops`).
- 위치는 알림 링크 진입 시 1회만 읽고 세션 범위로만 사용, 저장하지 않는다.
- 위치 실패 = 기능 강등, 서비스 실패가 아니다. 어떤 실패 상태에서도 안내와 다음 행동 경로는 렌더된다.
- 접근성(TTS · 쉬운 말 · 다국어 번역)은 부가 기능이 아니라 핵심 요구사항이다.

## 개발 시 주의

- **경로는 반드시 영문.** 코드 디렉토리에 한글 이름은 결함이다.
- **개발 서버 포트는 3000 고정** (`vite.config.ts`). 카카오맵 JS SDK 허용 도메인이 `http://localhost:3000` 으로 등록돼 있다.
- **`*.csv` / `*.jsonl`은 루트 `.gitignore`에서 전역 무시**된다. 데이터 파일은 `src/mocks/` 에 두거나 빌드타임에 변환한다.
- **키 등급** — 커밋 가능: 카카오 JS 키, Firebase 웹 config, VAPID 공개 키. 절대 비공개: 카카오 REST 키, TMAP 키, CLOVA 키, FCM Admin SDK 서비스계정 JSON.
- **CI** — `.github/workflows/frontend-ci.yml` 은 `apps/frontend/**` 필터가 걸린 non-required 워크플로다.
