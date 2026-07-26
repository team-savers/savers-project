# apps/frontend — PWA · 알림톡 진입 화면 · Interactive Care 챗봇

담당: 이진호(프론트엔드/UX).

## 상태

**아직 스캐폴딩 전입니다.** 프레임워크 선택과 초기 구성은 P1에서 이진호가 진행합니다.

## 스캐폴딩할 때 지켜야 할 것

- **경로는 반드시 영문**. `AGENTS.md`의 명명 규약상 코드 디렉토리에 한글 이름은 결함입니다.
- **`node_modules/`는 루트 `.gitignore`에 이미 등록**되어 있습니다. 별도 추가 불필요.
- ⚠️ 루트 `.gitignore`에 `lib/`, `build/`, `dist/`, `env/` 패턴이 있습니다. SvelteKit/Next처럼
  **`src/lib/`을 소스로 쓰는 프레임워크를 고르면 소스가 통째로 무시됩니다.**
  그 경우 `.gitignore`에 `!apps/frontend/src/lib/` 예외를 **반드시 함께 추가**하세요.
- **CI 골격은 이미 있습니다** — [`.github/workflows/frontend-ci.yml`](../../.github/workflows/frontend-ci.yml).
  `paths: apps/frontend/**` 필터가 걸린 **non-required** 워크플로이며(경로 변경 없는 PR에서
  체크가 생성되지 않아 머지가 영구 블록되는 함정 회피 — `docs/TEMPLATE_GUIDE.md` §4),
  `package.json`이 없는 지금은 모든 단계를 건너뜁니다. 스캐폴딩 PR에서 확인할 것:
  - 패키지 매니저가 npm이 아니면(pnpm/yarn) install 단계와 `cache` 설정을 교체
  - `lint` / `typecheck` / `build` 스크립트 이름 (`--if-present`라 없으면 조용히 무시됨)
  - `.github/dependabot.yml`의 npm 블록 주석 해제

## 설계 제약 (타협 대상 아님 — `AGENTS.md` 참조)

- 취약계층 본인에게 **설치·설정 부담을 지우지 않습니다**. 등록은 보호자/복지관/지자체가 대행.
- 위치는 **알림 링크 진입 시 1회만** 읽고 세션 범위로만 사용, 저장하지 않습니다.
- 접근성(TTS·쉬운 말·자동 번역)은 부가 기능이 아니라 핵심 요구사항입니다.
