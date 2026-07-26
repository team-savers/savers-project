# 템플릿 적용·운용 가이드 (TEMPLATE_GUIDE)

이 저장소는 [Yopkigom/ai-project-template](https://github.com/Yopkigom/ai-project-template)에서
파생되어 **SAVERS 모노레포 구조로 이식**된 상태입니다. 이 문서는 그 스캐폴딩을 **운용**하는
방법(리포 설정 재적용, 알려진 함정, 품질 게이트 유지)을 다룹니다.

> ⚠️ 이식으로 원본 템플릿과 달라진 점 — 원본 문서의 설명을 그대로 따르지 마세요.
> - 코드는 루트 `src/`가 아니라 `apps/backend/src`·`apps/ai-engine/src`에 있습니다.
> - 앱마다 `pyproject.toml`이 있고, 루트 `pyproject.toml`은 **ruff 설정 전용**(설치 불가)입니다.
> - 설치는 `pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"`.
> - 품질 게이트는 `bash scripts/run-tests.sh` 하나로 실행합니다(CI와 동일 대상·순서).
> - required status check가 **매트릭스 4종 + pre-commit 1종 = 5종**으로 늘었습니다(§4 참고).
> - 이 저장소는 **public**이므로 §6의 "무료 private 제약"은 해당하지 않습니다.

## 1. 대원칙: 템플릿은 "파일"만 복사한다

GitHub 템플릿 리포는 **저장소 파일만 복사**하고 **리포 설정은 전혀 복사하지 않습니다.**
따라서 새 리포마다 아래 두 트랙을 모두 처리해야 합니다.

| 트랙 | 자동으로 따라옴 (파일) | 매번 재적용 필요 (설정) |
|---|---|---|
| 내용 | 워크플로, 이슈/PR/Discussion 템플릿, labels.yml, pre-commit, pyproject, 코드 골격, 문서 | 브랜치 보호 규칙, 라벨 실체, 머지 전략, Secrets/Variables, Discussions 활성화·카테고리, Code security 설정, 협업자 권한 |
| 처리 | "Use this template" 클릭 | `scripts/setup-github.sh` + 소량의 수동 설정 (§3) |

## 2. 이 저장소에서 남은 절차

템플릿 초기화(`init_template.py`)와 모노레포 이식은 **이미 완료**되었습니다. 새로 합류한
팀원은 개발 환경만 구성하면 되며, 그 절차는 [공통_가이드/환경_세팅_가이드.md](공통_가이드/환경_세팅_가이드.md)가
전담합니다 — 진단·복구 스크립트가 설정이 **실제로 등록됐는지**까지 확인합니다.

```bash
git clone https://github.com/team-savers/savers-project.git && cd savers-project
bash scripts/setup-dev.sh          # macOS·Linux·WSL·Git Bash
# Windows PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
```

> 수동 절차(venv·editable 설치·`pre-commit install` ×2·nbstripout 필터)와 각 오류의 대처법은
> 환경 세팅 가이드의 §2·§5에 있습니다. 특히 `--hook-type pre-push` 누락과 nbstripout 필터
> 미등록은 **오류 없이 조용히 실패**하므로 눈으로 확인하지 마세요.

리포 설정(브랜치 보호·머지 전략·라벨)은 admin이 1회 적용합니다. 잡 이름이나 앱을
추가·변경했다면 `scripts/setup-github.sh`의 `contexts`를 함께 고치고 재실행하세요.

```bash
gh auth login
bash scripts/setup-github.sh team-savers/savers-project
```

## 3. 수동 설정 체크리스트 (스크립트가 못 하는 것)

- [ ] **Settings → General → Features**: Discussions 활성화
- [ ] **Discussions → 카테고리 `CollaborationLog` 생성** — Discussion 카테고리는
      API가 없어 수동 생성만 가능. 만들지 않으면 이슈 config의 협업 일지 링크와
      DISCUSSION_TEMPLATE이 동작하지 않습니다.
- [ ] **Settings → Code security**: Secret scanning + Push protection 활성화
      (⚠️ public 리포 전용 — 무료 플랜 private 리포는 미지원, §6 참고)
- [ ] (팀) Collaborators/Teams 권한 부여, 루트 `CODEOWNERS`의 TODO 교체 후
      `setup-github.sh`의 `require_code_owner_reviews`를 `true`로
- [ ] (필요 시) Actions Secrets/Variables 등록 — 템플릿은 secrets를 쓰지 않지만,
      프로젝트에서 워크플로가 secrets를 참조하면 등록 전까지 CI가 실패합니다

## 4. 주의사항 (함정 모음)

- **required check + paths 필터 조합 금지**: 브랜치 보호의 required status check로
  지정된 워크플로에 `paths:` 필터가 있으면, 해당 경로 변경이 없는 PR에서 체크가
  아예 생성되지 않아 머지가 영원히 "Expected" 상태로 블록됩니다. 그래서 이 템플릿의
  `ci.yml`은 paths 필터 없이 모든 PR에서 돌고, path 필터형인 `notebook-check.yml`은
  required로 지정하지 않습니다. CI 비용을 줄이려면 `dorny/paths-filter` 같은
  잡 내부 필터를 쓰세요.
- **required check의 context 이름 = 잡의 `name:`**: `setup-github.sh`의
  `contexts`와 `ci.yml`의 잡 이름은 문자열이 정확히 일치해야 합니다.
  이 저장소는 매트릭스 잡이라 이름이 4개로 전개됩니다 —
  `Lint & Type Check (backend)` / `(ai-engine)`, `Unit tests (backend)` / `(ai-engine)`.
  앱을 추가하면 `ci.yml`의 matrix와 `setup-github.sh`의 contexts를 **반드시 함께** 늘리세요.
- **브랜치 보호 적용 시점**: 첫 CI가 돌기 전에 required check를 걸면 체크 이름을
  GitHub가 모르는 상태라, PR에서 "Expected" 대기가 생길 수 있습니다. 스크립트는
  이름 문자열로 직접 지정하므로 동작하지만, 가급적 ④(첫 push) 후에 ⑤를 실행하세요.
- **private 리포 제약**: 브랜치 보호·CODEOWNERS 등 일부 기능은 무료 플랜의
  private 리포에서 동작하지 않습니다. 전체 매트릭스와 대응은 §6 참고.
- **노트북 정합성**: 출력 셀이 포함된 채 커밋된 노트북은 nbstripout filter와 어긋나
  영원히 `modified`로 표시됩니다. 발견 즉시 stripped 상태로 재커밋하세요.
  방치하면 pre-commit의 stash 복원까지 깨질 수 있습니다.
- **`from src.xxx` import 금지**: src 레이아웃에서는 `src.` 접두어 import가 설치
  환경에서 깨집니다. lint가 못 잡는 사각지대이니 리뷰에서 확인하세요.
- **앱 간 파이썬 import 금지**: `apps/backend`와 `apps/ai-engine`은 별도 배포 단위입니다.
  한쪽을 import하는 순간 "독립 배포 가능한 AI 모듈"이라는 구조의 근거가 사라집니다
  (통신은 `packages/contracts`의 HTTP 계약으로만).
- **`git pull` autostash 함정**: staged 변경이 있는 채로 pull하면 autostash 복원
  실패로 작업이 dangling stash로 빠질 수 있습니다. clean한 작업트리에서
  fetch→merge를 분리해 통합하세요.

## 5. 운용 방법

- **브랜치 전략**: main 직접 push 금지(보호 규칙). feature 브랜치 → PR →
  Squash merge(실험 커밋이 main 히스토리를 오염시키지 않도록) → 브랜치 자동 삭제.
  상세 절차는 [pr-checklist.md](pr-checklist.md).
- **품질 게이트**: CI(ruff·mypy·pytest)와 pre-commit이 같은 기준을 봅니다.
  로컬에서 pre-commit이 통과하면 CI도 통과하는 구조를 유지하세요 — 둘이 어긋나기
  시작하면 pre-commit은 무시되기 시작합니다.
- **라벨**: `.github/labels.yml`이 원천. 라벨을 바꾸면 파일을 수정하고
  `bash scripts/apply-labels.sh <owner>/<repo>`로 동기화 (PR 템플릿의 '변경 유형'
  체크박스와 일치 유지).
- **노트북 → src 라이프사이클**: notebooks/는 실험 기록, apps/<app>/src/는 프로덕션.
  검증된 로직은 함수화해 해당 앱의 src/로 이전하고 apps/<app>/tests/에 테스트를 추가합니다.
- **의존성**: 무거운 라이브러리(torch 계열, DB 클라이언트)는 extra로 분리해
  CI/기본 설치를 가볍게 유지. mypy는 `[[tool.mypy.overrides]]`로 예외 처리.
- **에이전트 가이드(AGENTS.md) 갱신**: 아키텍처 규칙·함정·사고 이력이 생길 때마다
  기록하세요. "왜"가 없는 규칙은 에이전트도 사람도 무시합니다.

## 6. 무료 플랜 private 리포에서 쓰기

템플릿에서 **private 리포를 생성하는 것 자체는 제약이 없습니다.** 다만 무료 플랜의
private 리포에서는 아래 설정들이 동작하지 않습니다 (GitHub Pro(개인)/Team(조직)
또는 public 전환 시 전부 사용 가능).

| 항목 | 무료 private | 대응 |
|---|---|---|
| 파일 자산 전부 (워크플로·이슈/PR 템플릿·pre-commit·코드 골격) | ✅ | — |
| CI (GitHub Actions) | ✅ 월 2,000분 한도 | ci.yml의 `concurrency`가 중복 실행을 취소. 부족하면 public 전환(무제한) |
| 머지 전략·라벨·Discussions | ✅ | — |
| **브랜치 보호 규칙** | ❌ (API 403) | `setup-github.sh`가 경고 후 나머지(머지 전략·라벨)를 계속 적용 |
| **CODEOWNERS** (자동 배정·필수 리뷰) | ❌ | 파일은 무해하게 남음 — Pro/public 전환 시 즉시 동작 |
| Secret scanning / Push protection | ❌ (public 전용) | pre-commit `detect-private-key`(PEM 전용) + **gitleaks**(API 키 범용 패턴) + `.gitignore` 시크릿 패턴이 로컬 방어선 |
| README의 CI 배지 | ❌ (외부 임베드 불가) | 배지 줄 삭제, public 전환 시 복원 |

브랜치 보호가 없는 동안의 실질 방어선은 **pre-commit + pre-push pytest**입니다 —
CI와 동일 기준이므로 훅 설치만 지키면 품질 게이트는 유지됩니다. 다만 main 직접
push를 막는 **강제력**은 없으므로, 팀 규모가 커지거나 강제가 필요해지면
Pro/Team 또는 public 전환 후 `setup-github.sh`를 재실행하세요.

## 7. 템플릿 자체의 유지보수

파생 프로젝트에서 발견한 개선점(새 함정, 더 나은 CI 구성, 관례 추가)은 이 템플릿
리포에 역반영하세요. 템플릿은 "가장 최근 프로젝트의 교훈이 축적된 곳"일 때 가치가
있습니다. 단, 이미 생성된 파생 리포에는 자동 전파되지 않으므로 필요 시 수동으로
가져갑니다 (`git remote add template ...` 후 선별 cherry-pick도 방법).

> 참고: 플랜별 기능 차이의 원문은 GitHub Docs
> [GitHub's plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans)
> 를 기준으로 합니다 (2026-07 확인).
