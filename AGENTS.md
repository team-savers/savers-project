# AGENTS.md

Shared project brief for **all** coding agents (Claude Code, Codex, Antigravity, …) working in this repository. This is the single source of truth for project context; tool-specific working notes live in each tool's own file (e.g. `CLAUDE.md` for Claude Code) and should not duplicate what is here.

## Project status

This repository holds the planning set — design docs (`docs/공통_가이드/`: `아키텍처.md`, `리스크.md`, `구현_범위.md`, `외부_승인.md`), decision records (`docs/adr/`), per-role playbooks (`docs/역할_가이드/`), the execution schedule (`docs/역할_일정/`) — plus the **scaffolded monorepo skeleton** (`apps/`, `packages/`, `infra/`, CI, quality gates). It is the workspace for team **세이버스 (SAVERS)**, competing in the 2026 제8회 K-디지털 트레이닝 해커톤.

**This repository is public** — judges browse it directly. Treat every commit as published: no secrets, no personal data beyond team member names, no competition submission forms (see "Not in this repository" below).

What exists in code today is a **walking skeleton, not a working service**. One disaster event threads the whole path — `수신 → 매칭 → 검색 → 생성(가드레일) → 세션 발급 → 웹푸시 발송 → 대피소 안내 → 챗봇 → 보호자 상태` — with every external dependency replaced by an offline stub behind a named seam ([ADR-0007](docs/adr/0007-walking-skeleton.md)). Nothing here talks to a real API yet: the disaster feed, the 국민행동요령 corpus, HyperCLOVA X, FCM, the shelter API and the resident store are all stubbed or in-memory, and each has an owner and a phase in [docs/역할_일정/](docs/역할_일정/00-overall.md).

⚠️ **Don't read the stubs as measurements.**
The bundled corpus is dummy text marked `[더미]`;
scoring 근거 일치율 against it measures agreement with a placeholder.
`apps/frontend/` is a real PWA now, but every backend call still resolves to an in-memory mock
(`VITE_USE_MOCK=true` is the default) — no HTTP wiring to `apps/backend` exists yet,
and `src/api/http.ts` holds contract path constants with unimplemented bodies.
`infra/docker-compose.yml` brings up backend + ai-engine only; the frontend is not a compose service.
Don't improvise a different structure — extend the one described under "Repo structure convention",
and replace a stub at its seam rather than around it.

Key hard dates: **preliminary round opens 2026-07-27**, **prelim submission (with measured metrics) due 2026-08-10 13:00**, **finals early September**; the build-out is a ~2-week sprint to 8/10 followed by a finals-prep track. All schedule phases (P1–P5) start on 2026-07-27 — no work is planned before the round opens; see [docs/역할_일정/00-overall.md](docs/역할_일정/00-overall.md) for the phased plan and per-role schedules.

## What SAVERS is

SAVERS is a disaster-response assistant for people who cannot judge or evacuate on their own — safety-vulnerable groups (children, elderly, disabled) and foreign workers facing language barriers. Its thesis: the problem is not lack of disaster information, but the "부재는 정보를 개인의 행동으로 전환하는 능력의 부재" — the inability to turn information into a concrete personal action. Existing channels (긴급재난문자/CBS, 안전디딤돌) broadcast the same regional content to everyone; SAVERS instead matches a registered resident to a live alert, confirms their **current location exactly once** at the moment they open the notification link (no background/continuous tracking, location used per-session and never persisted), and generates a personalized, guardrail-constrained action instruction delivered via PWA web push (FCM) — see [ADR-0005](docs/adr/0005-webpush-primary-channel.md).

First-target disaster type for the MVP: 호우·도시침수 (heavy rain / urban flooding).

## Planned architecture (4 modules)

1. **실시간 위치 매칭 엔진 (Location Matching Engine)** — normally matches users by registered 행정동 (administrative district) only; on alert, does a one-time browser Geolocation lookup, reverse-geocoded via 카카오맵 API, to check danger-zone membership and shelter distance.
2. **Advanced RAG 파이프라인** — chunks/embeds 행정안전부 국민행동요령 (official action manuals) into a Chroma vector DB; retrieval is conditioned on disaster type + user vulnerability profile.
3. **에이전틱 LLM 메시지 생성 (Agentic persona LLM)** — LangChain-orchestrated, HyperCLOVA X-generated messages, constrained by a guardrail prompt that forces answers to cite only retrieved official source text (hallucination suppression).
4. **무설치 사용자 터미널 (Zero-install terminal)** — delivery via PWA web push (FCM); the generated message is delivered **verbatim, with no template-slot substitution** ([ADR-0005](docs/adr/0005-webpush-primary-channel.md) — do not reintroduce a rendering adapter). Includes an interactive chatbot ("Interactive Care") for follow-up Q&A, with accessibility features (TTS, plain-language rewriting, auto-translation for foreign workers).

### Tech stack by layer

| Layer | Tech |
|---|---|
| Data ingestion | 기상청·소방청·행정안전부 재난안전데이터 공유 플랫폼 Open API, Python/FastAPI scheduler |
| Location processing | Browser Geolocation API, 카카오맵 역지오코딩 API, 행정동 code matching table |
| Knowledge base | 행정안전부 국민행동요령 corpus, Chroma vector DB |
| Generation/control | LangChain orchestration, HyperCLOVA X, guardrail prompts |
| Delivery/accessibility | PWA web push (Firebase Cloud Messaging) as the **primary** channel — 카카오 알림톡 not adopted, in the preliminary round or the finals ([ADR-0005](docs/adr/0005-webpush-primary-channel.md)), TTS, multilingual translation |
| Infra/ops | AWS **single VM** (Seoul region ap-northeast-2, CPU-only — HyperCLOVA X/embedding are external APIs, **no GPU**; backend + ai-engine via docker-compose, managed redundancy deferred — see [ADR-0003](docs/adr/0003-single-vm-seoul.md); the PWA is a static build served off-VM by Vercel — see [ADR-0008](docs/adr/0008-frontend-static-hosting.md)), log-based latency measurement, offline cache fallback mode |
=

## Non-negotiable design constraints

These came out of explicit risk mitigation decisions in the planning doc — don't casually "simplify" them away:

- **No continuous location tracking.** Location is read once, at notification-open time, and is session-scoped only — never persisted to storage.
- **Generation must be evidence-grounded.** The agentic LLM layer must answer only from retrieved 국민행동요령 source text; the guardrail prompt exists specifically to suppress hallucination, and its on/off effect is a measured KPI (see below) — don't remove or bypass it for convenience.
- **Zero install burden on the vulnerable user.** Registration/setup is designed to be done by a guardian/복지관/지자체 on the person's behalf, not by the end user. Any feature that requires the vulnerable person to install an app or self-configure conflicts with this.
- **Offline/degraded fallback required.** If the public disaster APIs are down or slow, the system must fall back to a pre-cached shelter/action-manual mode rather than failing silently.
- **Minimal collection, encrypted.** Sensitive fields (location, disability status) are minimally collected and encrypted; treat this as a hard requirement when adding new user fields.

## Quality bar / evaluation methodology (build these as code, not manual review)

The team's differentiation strategy is that quality is proven by **reproducible automated scripts**, submitted alongside the code, not by human surveys. When implementing evaluation:

- **알림 도달 속도**: end-to-end latency from disaster API ingestion to personalized alert dispatch. Target ≤30s. Measure via timestamp logging, report mean + p95 over 100 runs.
- **근거 일치율 (source-fidelity rate)**: generated message vs. official 국민행동요령 source text agreement. Target ≥85%, scored against a 30–50 case eval set.
- **환각 억제율 (hallucination suppression rate)**: same eval set run guardrail on/off; target ≥50% reduction in hallucinated content with guardrail on.
- **메시지 명확성 (message clarity)**: plain-language term substitution rate ≥90%, "single actionable instruction" inclusion rate 100%, per 국립국어원 쉬운 공공언어 기준; scored by rule-based check + cross-model LLM grading (grading model must differ from the generation model to avoid self-grading bias).
- **재난 이력 리플레이**: past 호우 특보 (heavy rain advisory) history is replayed end-to-end to validate real dispatch-condition latency and fidelity, not just synthetic tests.

All of the above targets are placeholder hypotheses to be replaced with real prototype measurements during the preliminary round — don't treat the numeric targets in this file as final ground truth once real measurements exist in the repo.

## Team / module ownership

| Person | Role | Owns |
|---|---|---|
| 안은남 | PM | Milestones, integration, final demo |
| 신호정 | Tech Lead | System architecture + inter-module contracts (OpenAPI/schemas), a walking skeleton threading the full flow, guardrail prompt design principles + initial version, repo scaffolding/CI/eval-harness skeleton — **concentrated up front** — then ongoing review/advisory. Architecture decisions are recorded as ADRs in `docs/adr/` so contract/skeleton knowledge is not siloed. |
| 김소원 | AI/RAG Engineer | 국민행동요령 preprocessing/chunking, Chroma indexing, semantic search tuning, 근거 일치율 measurement |
| 최혜리 (겸임) | Frontend/UX | PWA/웹푸시(FCM) integration, chatbot UI/UX, accessibility (multilingual/plain-language/voice), clarity metric instrumentation |
| 김도혁 | Backend/Infra | 기상청·소방청 API integration, location matching engine, FastAPI backend, infra redundancy, offline fallback |
| 최혜리 | QA/Security | Minimal-collection/encryption, guardrail validation, web-push fallback path, E2E testing, demo material |

## Naming convention (documents & folders)

The rule has two halves — which half applies is decided by **what the folder holds, not where it sits**:

- **Documents → Korean.** Planning/design documents and the folders that group them are Korean-named (`아키텍처.md`, `리스크.md`, `docs/역할_가이드/`, `docs/역할_일정/`, …), using an underscore-separated `A_B` pattern for multi-word names.
- **Everything else → English, mandatory.** Any folder that is not a document folder — code, config, assets, tooling, data, test fixtures, CI — **must** be English-named, always, with no Korean-name exception available. This is not a stylistic preference: these paths are consumed by build tools, import statements, Docker/CI configs, and shell scripts, where non-ASCII path segments cause encoding and portability failures. A Korean folder name appearing anywhere under `apps/`, `packages/`, `infra/`, or `.github/` is a defect to be renamed, not a judgment call.

Within the Korean half, keep these agreed **English exceptions**: `CLAUDE.md`, `AGENTS.md`, `README`, `docs/adr/` (ADR filenames), and `docs/pr-checklist.md` (inherited from the repo template) — all of them tool- or convention-bound names. Apply this when creating any new planning doc: new project-level docs default to Korean names unless they fall under an exception; new non-document folders are English without exception.

All planning docs live under `docs/`; the repo root keeps only `AGENTS.md`, `CLAUDE.md`, and `README.md`. Put a new doc in the folder that matches its axis:

| Folder | Holds |
|---|---|
| `docs/공통_가이드/` | Project-wide design docs everyone reads — `개발자_가이드.md`, `환경_세팅_가이드.md`, `배포_절차.md`, `서버_운영.md`, `저장소_운영.md`, `아키텍처.md`, `워킹_스켈레톤_설명.md`, `워킹_스켈레톤_점검.md`, `리스크.md`, `구현_범위.md`, `외부_승인.md`, `비용_산정.md`, `개인정보_체크리스트.md`, `후속_과제.md` |
| `docs/역할_가이드/` | Per-role playbooks — who does what. `01-기획총괄.md` … `06-QA-보안.md` |
| `docs/역할_일정/` | Per-role timelines — when it must be done. Same role numbering as `역할_가이드/` |
| `docs/공유_문서/` | Continuously revised working documents (인터뷰 가이드, 회의 결과, …) — **not** competition submission forms, which stay out of the repo per "Not in this repository". Its `README.md` is the index — every file listed with 최종 수정일 · 버전 · 핵심 내용 · 상태·근거, updated in the same PR as the file itself |
| `docs/adr/` | Architecture decision records (English filenames) |
| `docs/pr-checklist.md` | PR procedure, inherited from the template |

`역할_가이드/` and `역할_일정/` are 1:1 by role number — adding a role means adding a file to both.

### Not in this repository (deliberate)

These are kept **outside** the repo because it is public, and `.gitignore` blocks them so they cannot be re-added by accident. Do not "restore" them:

| Asset | Where it lives | Why |
|---|---|---|
| `docs/제출_자료/` — 참가신청서·기획서 PDFs | team's local/shared drive | Competition submission forms; the 참가신청서 carries member names and a signature block |
| `docs/참고_자료/` — 수상작 레포 전수조사 PDF | team's local/shared drive | Internal competitor research; nothing judges need to see |
| `내부_인수인계.md` — Tech Lead handover plan | team's local/shared drive | Contains the personal circumstances behind ADR-0002; the public-facing rationale is in [docs/adr/0002-frontloaded-tech-lead.md](docs/adr/0002-frontloaded-tech-lead.md) |

If a doc in this repo needs to cite one of them, cite the ADR or the summary — never re-commit the source file.

## Markdown line wrapping (committed files only)

**Committed `.md` files are hard-wrapped at sentence boundaries. GitHub comments are not.**
The two render differently, and that difference is the whole rule:

| Target | A newline inside a paragraph | Therefore |
|---|---|---|
| **Committed `.md`** (docs, README, ADRs) | collapses to a space (CommonMark soft break) | wrapping changes nothing on screen — **wrap it** |
| **GitHub comments** (issue / PR body, review) | survives as `<br>` (GFM hardbreaks) | wrapping inserts visible breaks mid-sentence — **leave one paragraph per line** |

Why wrap at all: an unwrapped paragraph is one long line,
so correcting a single word marks the **entire paragraph** as changed in a diff.
Reviewers then re-read a whole block to find one edit.

**Break at sentence or clause boundaries, capped at roughly 50 Korean characters (~100 English).**
The cap is a ceiling, not a target — never pad a line to reach it.
Fixed-column wrapping is explicitly *not* what this asks for:
reflowing to a column means one edited word pushes every following line,
which reproduces the whole-paragraph diff this rule exists to avoid.
One sentence per line is the ideal; split long sentences at a comma or connective.

Never break inside these — the line break either breaks parsing or breaks the link:

- table rows (a GFM row must be a single line)
- fenced code blocks (content is literal)
- headings
- `[text](url)` — breaking the URL half kills the link

List items and blockquotes wrap normally;
keep continuation lines indented to the item's text column.

Existing unwrapped docs are **not** rewrapped in a dedicated pass —
a reflow-only PR is pure diff noise and buries the real history.
Rewrap a file's paragraphs when you are already editing them for another reason.

## Repo structure convention (monorepo)

The team surveyed past winning teams' repo structures (research PDF kept outside this repo — see "Not in this repository"). Its **substantive** finding is not "split into many repos" (form) but **"keep AI as an independently deployable engine/module rather than an inline API call, and document deployment/ops directly in READMEs"** (substance).

Given this team's constraints — 6 people, a short hackathon timeline, and a **front-loaded Tech Lead (early-concentration model)** — the coordination cost and integration debt of a multi-repo org outweigh its benefits. **This project uses a single monorepo**, while keeping AI as an independently deployable service inside it to satisfy the winning-pattern substance ([ADR-0001](docs/adr/0001-monorepo.md)). Actual layout:

```
savers-project/
  apps/
    backend/               # FastAPI: 재난 Open API 수집, 위치 매칭, 발송 오케스트레이션
      pyproject.toml       #   src/api (thin routers) + src/backend_core (domain)
    ai-engine/             # Independently deployable: own pyproject + Dockerfile + README
      pyproject.toml       #   src/ai_engine (RAG retrieval + guardrail generation)
      eval/                #   Reproducible quality harness (goldens + metric functions)
    frontend/              # PWA (Node) — not scaffolded yet
  packages/
    contracts/             # OpenAPI spec + shared schemas (single source of truth)
  infra/                   # docker-compose, .env.example, AWS provisioning
  e2e/                     # Cross-app end-to-end harness (QA-owned) — HTTP only, non-required CI
  notebooks/               # Experiments; promoted logic moves into apps/<app>/src
  scripts/                 # setup-dev.sh/.ps1 + dev_env.py (env doctor), run-tests.sh (= CI
                           #   locally), setup-github.sh, apply-labels.sh
  docs/                    # Design docs, ADRs, role guides/schedules
  pyproject.toml           # ⚠️ tooling only (ruff config) — NOT an installable package
  CODEOWNERS               # per-folder owners — repo root, as ADR-0001 specifies
  .github/                 # CI, issue/PR templates, labels
```

The layout above is what [ADR-0001](docs/adr/0001-monorepo.md), [docs/공통_가이드/개발자_가이드.md](docs/공통_가이드/개발자_가이드.md) §7, and [docs/공통_가이드/아키텍처.md](docs/공통_가이드/아키텍처.md) §4 describe — **keep all four in sync**. Moving a top-level directory means editing those three docs in the same PR, not afterwards.

Two placements are load-bearing rather than arbitrary: `eval/` sits **inside** `apps/ai-engine` so the harness ships and versions with the model behavior it scores, and `CODEOWNERS` sits at the **repo root** (GitHub reads only one of root / `.github/` / `docs/` — do not leave a second copy behind).

- Shared docs/infra/env live once under `infra/`·`docs/` (no cross-repo duplication or drift).
- Cross-cutting changes land atomically in one PR; that atomicity is the whole point of the monorepo.
- Boundaries are enforced by `CODEOWNERS` + branch protection; `apps/ai-engine/` proves "independently deployable" via its own Dockerfile/README.
- Do **not** re-split into an org + multi-repo layout unless the team explicitly revisits this decision — judges reward "AI as an independent module" and "deployment docs exist," both of which the monorepo satisfies.

## Build / run / test

Every app is installed **editable, from the repo root**. There is no root package — `pip install .` at the root is a mistake.

```bash
# One-shot setup = the three manual lines below, but verified: it checks whether each setting
# actually registered (pre-push hook, nbstripout git filter) instead of assuming the command ran.
bash scripts/setup-dev.sh          # Windows: powershell -ExecutionPolicy Bypass -File scripts\setup-dev.ps1
                                   # --check = diagnose only; details in docs/공통_가이드/환경_세팅_가이드.md

python3 -m venv .venv && source .venv/bin/activate
pip install -e "./apps/backend[dev]" -e "./apps/ai-engine[dev]"
pip install pre-commit && pre-commit install && pre-commit install --hook-type pre-push

uvicorn api.main:app --reload --port 8000              # backend    → :8000/docs
uvicorn ai_engine.service:app --reload --port 8100     # ai-engine  → :8100/docs

# Walking skeleton in one call: fires the demo 호우경보 over the seeded 행정동 and returns
# session tokens + per-recipient latency. With ai-engine down it still returns 200, with
# messageMode: official_fallback — that degradation is the designed behaviour, not a bug.
curl -X POST localhost:8000/internal/alerts/dispatch

bash scripts/run-tests.sh          # quality gate: ruff + mypy + pytest across all apps (= CI)
bash scripts/run-tests.sh --tests  # pytest only (what the pre-push hook runs)
```

- Imports are **`from api import ...` / `import backend_core` / `from ai_engine import ...`** — ⚠️ never with a `src.` prefix; the src layout makes `from src.x` break at runtime, and lint does not catch it.
- **Heavy dependencies (LangChain, Chroma, geo libs) go in an app's optional `[project.optional-dependencies]` extra, never in core `dependencies`.** CI installs core + `dev` only; moving them into core makes every CI run drag the RAG stack in.
- **Tooling config lives in two tiers**: root `pyproject.toml` carries `[tool.ruff]` for the whole repo (ruff resolves it by walking up); each app's `pyproject.toml` carries its own `[project]`, `[tool.mypy]`, `[tool.pytest.ini_options]`. ⚠️ mypy and pytest must be run **with the app directory as cwd** or they pick up no config — `scripts/run-tests.sh` and CI both do this.

## Architecture rules (violations are design defects, not style nits)

```
apps/backend/src/api  ──depends on──>  apps/backend/src/backend_core
apps/backend          ──HTTP only──>   apps/ai-engine     (contract in packages/contracts)
```

- **`backend_core` must never import `api`.** Domain logic has to stay runnable and testable without FastAPI.
- **`apps/ai-engine` must never import `apps/backend` (and vice versa).** They are separate deployables; the only coupling allowed is the HTTP contract. A Python import across that line silently destroys the "independently deployable AI module" property that the repo structure exists to prove.
- **Routers stay thin**: validate request → call domain → map response. Business logic in a router is a defect.
- **Contracts before implementation**: an interface between modules exists in `packages/contracts` first, then in code. Verbal agreements are not contracts (this is the Tech-Lead-hands-off insurance from ADR-0002).
- Pipeline direction inside the AI engine is one-way: parsing → chunking → embedding → retrieval → generation. No reverse dependencies.

## Where new code goes

- HTTP/routing/auth concerns → `apps/<app>/src/api/` (backend) or the service module (ai-engine)
- Domain logic → `apps/backend/src/backend_core/` or `apps/ai-engine/src/ai_engine/`
- Frontend → `apps/frontend/` (English paths only; read its README before scaffolding — the root `.gitignore` has traps for `src/lib/`)
- Experiments → `notebooks/` (never imported; promote verified logic into `apps/<app>/src/`)
- Evaluation assets (goldens, metric functions) → `apps/ai-engine/eval/` (metric functions stay pure: `(prediction, truth) → score`)
- Tests → `apps/<app>/tests/`, mirroring `src/` as `test_<module>.py`
- Cross-app end-to-end tests → `e2e/` (QA-owned). **Never** put them in `apps/*/tests/`: those paths feed the *required* pytest matrix, and E2E needs a running stack plus external API keys, so a required check would block every PR on infrastructure. `e2e/` reaches services over HTTP only — importing an app package from here breaks the same boundary rule the apps have.

## Project-specific gotchas (with the why — a rule without a reason gets ignored)

- **Public repo, so secrets are a one-way door.** A committed key is public the moment it is pushed; the fix is revocation and reissue, not a revert. Keys go in `infra/.env` (ignored); only `infra/.env.example` (key names, no values) is committed. Three backstops, and you need all three because each has a hole: GitHub Push protection catches **partner-issued patterns only** — the 카카오 / HyperCLOVA X (NCP) / 솔라피 keys this project actually uses are probably not among them, and the generic-pattern detection that would cover them requires a GitHub Advanced Security subscription this repo does not have. pre-commit `detect-private-key` catches **PEM private keys only**. The gap between those two is covered by **gitleaks**: as a pre-commit hook on staged changes, plus a full-tree scan in the required `Pre-commit hooks` CI job. ⚠️ Those two gitleaks entries are a pair — the hook's entry is hardcoded to `--staged`, so `pre-commit run --all-files` scans nothing; deleting the CI step silently removes the only check that sees an unhooked contributor's key.
- **`.gitignore` is tuned for this monorepo — read before adding data files.** Directory ignores (`/data/`, `/outputs/`) are root-anchored on purpose, and `lib/`-style patterns are anchored so they cannot swallow a frontend `src/lib/`. Git cannot un-ignore a file inside an ignored directory, so committable assets are whitelisted by **file pattern** (`!apps/ai-engine/eval/**/*.jsonl`, `!apps/**/fixtures/*.csv`). Add a matching whitelist line when you introduce a new committable data file — otherwise it vanishes silently.
- **Never mock away the guardrail to make a test pass.** Its on/off delta is a submitted KPI; a bypassed guardrail invalidates the measurement rather than fixing the test.
- **External API calls in tests must be mocked.** Real calls cost money and make CI non-deterministic; the disaster APIs are also rate-limited.
- **Required status checks are matrix jobs.** Their names (`Lint & Type Check (backend)`, `Unit tests (ai-engine)`, …) must match `scripts/setup-github.sh` exactly. Renaming a CI job without updating that script leaves every PR blocked on a check that will never appear.
- **Never add a `paths:` filter to a workflow that is a required check.** PRs that don't touch those paths never create the check, so they stay stuck on "Expected" forever. Frontend CI must therefore be a separate, non-required workflow.
- **Notebooks are output-stripped by nbstripout** (`.gitattributes` filter + pre-commit). A notebook committed with outputs disagrees with the filter and shows as permanently `modified` — re-commit it stripped as soon as you notice.
- **`git pull` with staged changes can lose work** via failed autostash restore; integrate from a clean tree. Recover dangling work with `git fsck --lost-found`.

## Collaboration / Git

- `main` is protected: feature branch → PR → **squash merge** → branch auto-deleted. Procedure: [docs/pr-checklist.md](docs/pr-checklist.md).
- CI (ruff · mypy · pytest) and pre-commit enforce the same rules on purpose. If they drift apart, people start ignoring the hooks — fix the drift, don't route around it.
- Repo settings (branch protection, merge strategy, labels) live only on GitHub's side — git does not track them and they never show up in a diff; they are re-applied by `scripts/setup-github.sh`. Details, the manual checklist, and the required-check contract: [docs/공통_가이드/저장소_운영.md](docs/공통_가이드/저장소_운영.md).
- Architecture decisions go in `docs/adr/` as they are made. This is the anti-bus-factor mechanism for the front-loaded Tech Lead model — an undocumented decision is a decision the team loses.
- **`docs/adr/` is the single source of truth for "확정" (confirmed).**
  An item that cannot be traced to an ADR number is **검토 중** (under review), not 확정 — this applies to everyone, no exceptions.
  Any document meant for outside readers (역할_가이드, 공통_가이드, etc.) marks each confirmed item with a one-line source, and **that source is an ADR number** — a path to another guide document does not qualify, because a guide citing itself is exactly the failure this rule exists to stop.
  An item with no source line is a signal it hasn't actually been decided yet.
  If something needs to be promoted to 확정, flag it to the Tech Lead to write the ADR — verbal agreement is not a contract in this repo (see the `Contracts before implementation` rule above), so writing it down is the Tech Lead's job, not the reporter's.
  Existing documents are brought into line when you are already editing them for another reason; no separate cleanup PR — same as the line-wrapping rule above.
