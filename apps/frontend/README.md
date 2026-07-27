# apps/frontend — PWA · 웹푸시 진입 화면 · Interactive Care 챗봇

담당: 이진호(프론트엔드/UX).

## 상태

**스캐폴딩 완료(P1 S1-1).** React + Vite + TypeScript + vite-plugin-pwa 통합 서비스워커 구성이 끝났습니다.

## 알림 채널 (2026-07-26 전환)

1차 알림 채널은 **웹푸시(FCM)** 입니다. 카카오 알림톡은 예선 범위에서 제외되었습니다 —
2026-07-26 팀 결정. ADR 등록과 공통 문서 갱신은 별건으로 진행 중이며,
그 전까지 `AGENTS.md`·`docs/adr/0004-pwa-over-native.md` 등 공통 문서는 여전히 알림톡 전제입니다 — **이 README가 프론트 기준입니다.**

- **템플릿 사전승인이 없으므로 생성된 문구를 그대로 렌더합니다.** 변수 슬롯 매핑(렌더링 어댑터)을 다시 만들지 마세요.
- **알림 액션 버튼에 의존하지 않습니다.** 플랫폼별 최대 2개 제한이 있어 신뢰할 수 없습니다.
  알림은 제목+본문+탭 = 랜딩 진입으로 단순화하고, **집/밖/도움 분기는 랜딩 첫 화면에서** 수행합니다.
- **서비스워커는 반드시 1개입니다.** FCM이 요구하는 `firebase-messaging-sw.js`와 `vite-plugin-pwa`의 SW는
  같은 스코프에서 충돌합니다. `strategies: 'injectManifest'` + 커스텀 `src/sw.ts` 안에서
  Workbox 캐싱과 `onBackgroundMessage`를 함께 처리하고, 루트에 별도 SW 파일을 두지 않습니다.

### 시연 환경 제약 ⚠️

**안드로이드 크롬 / 데스크톱 크롬 고정.** iOS 웹푸시는 **16.4+ 및 홈 화면 추가(A2HS) 상태**에서만 동작합니다.
알림톡이 1차 채널이던 시기에는 이 제약이 우회되었으나, 채널 전환으로 **우회 수단이 사라졌습니다.**
iOS는 시연 대상에서 제외하며, 미지원 확인 화면을 캡처해 증빙으로 남깁니다.

또한 **웹푸시는 localhost를 제외하면 HTTPS가 필수**입니다. 안드로이드 실기기 검증에는 배포된 HTTPS URL이 반드시 필요합니다.

## 스캐폴딩할 때 지켜야 할 것

- **경로는 반드시 영문**. `AGENTS.md`의 명명 규약상 코드 디렉토리에 한글 이름은 결함입니다.
- **개발 서버 포트는 3000 고정** (`vite.config.ts`의 `server.port`). 카카오맵 JS SDK 허용 도메인이
  `http://localhost:3000`으로 이미 등록되어 있어, 포트를 바꾸려면 카카오 콘솔 도메인 추가가 선행돼야 합니다.
  배포 도메인이 정해지면 콘솔에 **추가 등록**해야 배포본에서 지도가 렌더됩니다.
- **`node_modules/`는 루트 `.gitignore`에 이미 등록**되어 있습니다. 별도 추가 불필요.
- ⚠️ **`*.csv` / `*.jsonl`은 루트 `.gitignore`에서 전역 무시됩니다.** 화이트리스트는
  `apps/**/fixtures/*.csv` 계열뿐이므로, 법정동코드 전체자료 같은 데이터를 `src/data/`에 두면
  **커밋되지 않고 조용히 사라집니다.** `src/fixtures/`에 두거나 빌드타임에 JSON으로 변환하세요.
  (git은 무시된 파일을 나중에 되살리지 못합니다.)
- ℹ️ 루트 `.gitignore`의 `lib/`·`build/`·`dist/`·`env/`는 **루트 앵커(`/lib/`)로 수정되어 있어**
  `apps/frontend/src/lib/`은 무시되지 않습니다. 다만 이 프로젝트는 React + Vite 스택이라 해당 사항이 없습니다.
- **키 등급** — 커밋 가능: 카카오 **JS** 키, Firebase 웹 config, VAPID **공개**키.
  절대 비공개: 카카오 REST 키, TMAP 키, CLOVA 키, **FCM Admin SDK 서비스계정 JSON**(백엔드 소관 — 이 디렉토리에 들어와선 안 됩니다).
  실키는 `.env.local`, 커밋은 `.env.example`(키 이름만).
- **CI 골격은 이미 있습니다** — [`.github/workflows/frontend-ci.yml`](../../.github/workflows/frontend-ci.yml).
  `paths: apps/frontend/**` 필터가 걸린 **non-required** 워크플로이며(경로 변경 없는 PR에서
  체크가 생성되지 않아 머지가 영구 블록되는 함정 회피 — `docs/공통_가이드/저장소_운영.md` §4),
  `package.json`이 없는 지금은 모든 단계를 건너뜁니다. 스캐폴딩 PR에서 확인할 것:
  - 패키지 매니저가 npm이 아니면(pnpm/yarn) install 단계와 `cache` 설정을 교체
  - install이 `npm ci`이므로 **`package-lock.json`을 반드시 커밋**해야 설치 단계가 실행됩니다
  - `lint` / `typecheck` / `build` 스크립트 이름 (`--if-present`라 없으면 조용히 무시됨)
  - `.github/dependabot.yml`의 npm 블록 주석 해제

## 설계 제약 (타협 대상 아님 — `AGENTS.md` 참조)

- 취약계층 본인에게 **설치·설정 부담을 지우지 않습니다**. 등록은 보호자/복지관/지자체가 대행.
- 위치는 **알림 링크 진입 시 1회만** 읽고 세션 범위로만 사용, 저장하지 않습니다.
  **storage 계열 API 금지**(sessionStorage 포함). FCM 토큰의 IndexedDB 사용은 라이브러리 표준 동작이라 예외이며,
  "위치·프로필을 우리 코드로 저장하지 않는다"는 원칙으로 해석합니다.
- **위치 실패 = 기능 강등, 서비스 실패 아님.** 어떤 실패 상태에서도 액션 허브(도움 요청·119)는 렌더됩니다.
- 접근성(TTS·쉬운 말·자동 번역)은 부가 기능이 아니라 핵심 요구사항입니다.
