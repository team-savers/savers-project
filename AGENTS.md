# AGENTS.md

Shared project brief for **all** coding agents (Claude Code, Codex, Antigravity, …) working in this repository. This is the single source of truth for project context; tool-specific working notes live in each tool's own file (e.g. `CLAUDE.md` for Claude Code) and should not duplicate what is here.

## Project status

This repository holds the planning set — design docs (`docs/공통_가이드/`: `아키텍처.md`, `리스크.md`, `구현_범위.md`, `외부_승인.md`), decision records (`docs/adr/`), per-role playbooks (`docs/역할_가이드/`), the execution schedule (`docs/역할_일정/`) — plus the **scaffolded monorepo skeleton** (`apps/`, `packages/`, `infra/`, CI, quality gates). It is the workspace for team **세이버스 (SAVERS)**, competing in the 2026 제8회 K-디지털 트레이닝 해커톤.

**This repository is public** — judges browse it directly. Treat every commit as published: no secrets, no personal data beyond team member names, no competition submission forms (see "Not in this repository" below).

What exists in code today is a **walking skeleton, not a working service**. One disaster event threads the whole path — `수신 → 매칭 → 검색 → 생성(가드레일) → 세션 발급 → 웹푸시 발송 → 대피소 안내 → 챗봇 → 보호자 상태` — with every external dependency replaced by an offline stub behind a named seam ([ADR-0007](docs/adr/0007-walking-skeleton.md)). Nothing here talks to a real API yet: the disaster feed, the 국민행동요령 corpus, HyperCLOVA X, FCM, the shelter API and the resident store are all stubbed or in-memory, and each has an owner and a date in [docs/역할_일정/](docs/역할_일정/00-overall.md).

**Only a few of those seams get replaced before the finals** — real FCM sending, the event log, the flood-avoiding route (**OSMnx + networkx**), the suitability model, and the log-matching verifier. The rest (public-API polling, real datastore, Chroma) are deliberately deferred past the finals because they are not on the demo path; the seam catalogue in [docs/공통_가이드/워킹_스켈레톤_설명.md](docs/공통_가이드/워킹_스켈레톤_설명.md) marks which is which. **`Dispatcher.send()` is the one to fix first**: the default `RecordingDispatcher` records instead of sending, and two of the four submitted metrics cannot be measured at all until real push works.

⚠️ **Don't read the stubs as measurements.**
The bundled corpus is dummy text marked `[더미]`;
scoring 근거 일치율 against it measures agreement with a placeholder.
`apps/frontend/` is a real PWA now, and `src/api/http.ts` implements the contract HTTP adapter,
which `src/api/client.ts` selects per screen through `VITE_USE_MOCK` — still defaulting to `true`,
so every screen resolves to the in-memory mock until the flag is flipped. Evacuation (`Landing.tsx`)
and Guardian Q&A (`Guardian.tsx`) are wired to the real adapter as of 2026-08-29 (PR #206, PR #226)
and have each been run once against a live `apps/backend` manually — recorded in
[docs/공통_가이드/실패_모드_시연_대본.md](docs/공통_가이드/실패_모드_시연_대본.md) cases 2 and 5, not an
automated/CI-verified check. Whether the *deployed* demo build runs with `VITE_USE_MOCK=false` is
unconfirmed — check the Vercel project settings before citing it as live.
`infra/docker-compose.yml` brings up backend + ai-engine only; the frontend is not a compose service.
Don't improvise a different structure — extend the one described under "Repo structure convention",
and replace a stub at its seam rather than around it.

Key hard dates: **prelim submission was delivered 2026-08-10 13:00**; the team is now in the finals-prep track — **8/11–8/21 standby** (PM-only admin/goldens work), **8/22–8/29 implementation** — **8/22 is a half day (afternoon only, 4h; the morning is the Tech Lead's eval-harness slot)** and **Sundays 8/23 and 8/30 are off**, leaving a **52-hour implementation window per person** — **8/29 code freeze + demo-environment deploy (PM alone)**, **8/31–9/1 rehearsals**, **9/2–9/3 finals**, **9/4 awards. Fifty-two hours is the entire remaining implementation budget**, and there are only two implementers (AI/RAG/FE and Backend) with the critical chain alternating between them — see [docs/역할_일정/00-overall.md](docs/역할_일정/00-overall.md) for the per-segment plan, handoff deadlines, and per-role schedules.

## What SAVERS is

SAVERS is a disaster-response assistant for people who cannot judge or evacuate on their own — safety-vulnerable groups (children, elderly, disabled) and foreign workers facing language barriers. Its thesis: the problem is not lack of disaster information, but the "부재는 정보를 개인의 행동으로 전환하는 능력의 부재" — the inability to turn information into a concrete personal action. Existing channels (긴급재난문자/CBS, 안전디딤돌) broadcast the same regional content to everyone; SAVERS instead matches a registered resident to a live alert, confirms their **current location exactly once** at the moment they open the notification link (no background/continuous tracking, location used per-session and never persisted), and generates a personalized, guardrail-constrained action instruction delivered via PWA web push (FCM) — see [ADR-0005](docs/adr/0005-webpush-primary-channel.md).

First-target disaster type for the MVP: 호우·도시침수 (heavy rain / urban flooding).

## Planned architecture — three layers, three core technologies

> ⚠️ **All four rows are 확정.** Row 1's [ADR-0011](docs/adr/0011-m3-no-storage-not-no-receipt.md) was accepted 2026-08-24; rows 2 ~ 4 (ADR-0018, 0017, 0019, all written 2026-08-26) were accepted 2026-08-28 once their decision owners confirmed.
> Cite a row as 확정 only while the ADR's own status line says 승인 — that line, not this table, is the source.
> Row 4 was promoted as a **superseding ADR rather than an in-place amendment to [ADR-0002](docs/adr/0002-frontloaded-tech-lead.md)**:
> ADR-0002 is accepted, and changing an accepted ADR's decision content is not one of the four
> post-acceptance edit exceptions in [ADR-0005](docs/adr/0005-webpush-primary-channel.md) — ADR-0002 carries only a 대체 표시,
> the same shape as ADR-0004 → ADR-0005 and ADR-0003 → ADR-0008.
>
> | # | Decision | Changes | Status |
> |---|---|---|---|
> | 1 | **M3 metric = 「위치정보 무저장·무로깅」** — the server *does* receive a coordinate on `/v1/shelters/search` and stores/logs it nowhere. Reworded twice: 「즉시 파기 준수율 100%」 → 「미수신」 (8/21) → 「무저장·무로깅」 (8/22); the client-side alternative (no coordinate endpoint) was considered and **rejected for the finals window** | Submitted metric + the location constraint below | [ADR-0011](docs/adr/0011-m3-no-storage-not-no-receipt.md) **Accepted** — 2026-08-24 Tech Lead 승인 |
> | 2 | Four modules → three layers + three core technologies | Architecture framing | [ADR-0018](docs/adr/0018-three-layers-three-core-technologies.md) **Accepted** — 2026-08-28 PM·Backend·AI/RAG 확인 |
> | 3 | Route engine **OSMnx + networkx** instead of OSRM (2026-08-21) | Tech stack | [ADR-0017](docs/adr/0017-route-engine-osmnx-networkx.md) **Accepted** — 2026-08-28 Backend 확인 |
> | 4 | Tech Lead writes no code + infrastructure moves to PM (2026-08-11 reshuffle) | Supersedes part of [ADR-0002](docs/adr/0002-frontloaded-tech-lead.md) | [ADR-0019](docs/adr/0019-role-scope-after-2026-08-11-reshuffle.md) **Accepted** — 2026-08-28 PM·Backend 확인 |

Per 기획서 v3 the service is split into three layers: **① 판정 (assessment) belongs to the government** (기상청·홍수통제소·기후부 도시침수예보), **② 계산 (computation) is SAVERS**, **③ 전달 (delivery) is a zero-install mobile web channel**. **SAVERS does not implement its own hazard determination** — it converts an already-issued official warning into "where do I go, in how many minutes."

The computation layer holds three SAVERS-specific technologies:

1. **대피소 부합도 모델 (Shelter-suitability model)** — a PU-learning (spy technique) classifier over LightGBM, trained with 서울시's 수해대피소 designation list as labels. **Label/feature separation is an absolute rule**: Seoul-only data (designation list, 침수예상도) is used for labels and validation *only*, while model inputs are 13 nationally-available public features (표고, 대피 여유고, 지하층수, 하천 최단거리, …). Output is labelled 「서울시 지정기준 부합도」 with SHAP contributions — never 「부적합」, since not-designated does not mean unsuitable. Validation is **3-fold** (자치구 GroupKFold spatial-block CV · non-school recall@top-20% as the primary metric · lift over the 침수예상도 baseline); the fourth check (string/standard-field/model three-way comparison) was cut for the finals.
2. **침수 회피 경로 (Flood-avoiding route)** — OSM road network loaded into a graph (**OSMnx + networkx**; the submitted plan said OSRM — see the correction note below), every link tagged with flood-risk grade R0–R3; R2 (침수심 0.5–1.0m) and R3 (지하차도·하천변) links are removed *first*, then the shortest remaining path is chosen. If nothing is passable the answer is **「경로 없음」 and the shelter is re-selected** — not a shortest path through water.
3. **보호자 상황 확인 RAG (Guardian status RAG)** — retrieval over **event logs** (screen state, button clicks, arrival), not documents. The five-stage agentic loop 관측 → 계획·검색 → 행동·생성 → 응답 검증 → 전달·에스컬레이션 **re-enters at 관측 after 30 minutes of no response**; this loop is the entire basis of the "agentic" claim. Response verification splits each sentence into claims and matches them 1:1 against the log — **one unmatched claim blocks the whole sentence**. Retrieval scope is that session's log only; there is no document and no coordinate. Forbidden words: 「안전합니다」·「괜찮습니다」 — the chatbot restates the log, it does not judge safety.

Delivery is **PWA web push (FCM)**; the generated message goes out **verbatim, with no template-slot substitution** ([ADR-0005](docs/adr/0005-webpush-primary-channel.md) — do not reintroduce a rendering adapter). The user flow is ①특보 수신 → ②정보 입력 → ③상황 분기 → ④행동 권고 (3-step traffic light: 상황 주시 / 대피 준비 / 즉시 대피) → ⑤경로 안내. First-phase scope is **Android zero-install web push**; iOS needs A2HS before web push opens.

**Fallbacks never stop the guidance — they surface what was substituted.** 특보 API down → Redis cache; geocoding/DEM match failure → 「판정 불가」; log-verification failure → 최소안전문; no passable route → shelter re-selection. Every screen carries the judgement time and data-as-of time (「기상청 특보 21:12 기준 / 대피소 정보 21:20 기준」).

> The 국민행동요령 corpus RAG (chunking · Chroma indexing · conditional retrieval · guardrail prompt) survives from the prelim round in `apps/ai-engine`. The guardian RAG **passes the whole session log as context and uses no vector index** — do not merge the two.

### Tech stack by layer

| Layer | Tech |
|---|---|
| Data ingestion | 기상청·소방청·행정안전부 재난안전데이터 공유 플랫폼 Open API, Python/FastAPI scheduler |
| Location processing | Browser Geolocation API (client-side only), 카카오맵 역지오코딩 API, 행정동 code matching table |
| Shelter suitability | LightGBM + spy-technique PU learning, SHAP, 자치구 GroupKFold spatial-block CV; sources: 서울 열린데이터광장 (OA-21181 · OA-21172 · OA-15636), 국토지리정보원 DEM, 건축물대장 |
| Routing | OpenStreetMap → **OSMnx + networkx** in-memory graph, per-link flood-risk grades R0–R3 (pre-computed static table). **The submitted plan names OSRM in two places; the finals build uses the A-plan and the correction is recorded in [docs/공유_문서/서비스_기획서.md](docs/공유_문서/서비스_기획서.md). OSRM migration is the first roadmap item after the finals.** |
| Knowledge base | 행정안전부 국민행동요령 corpus, Chroma vector DB (corpus RAG); **event logs, no vector index** (guardian RAG) |
| Generation/control | LangChain orchestration, HyperCLOVA X, guardrail prompts, claim-level log-matching verifier |
| Delivery/accessibility | PWA web push (Firebase Cloud Messaging) as the **primary** channel — 카카오 알림톡 not adopted, in the preliminary round or the finals ([ADR-0005](docs/adr/0005-webpush-primary-channel.md)); the closed-loop **second dispatch rides the same FCM path and SMS is not adopted either** ([ADR-0014](docs/adr/0014-closed-loop-second-dispatch-channel.md), Accepted 2026-08-25), TTS, multilingual translation |
| Infra/ops | AWS **single VM** (Seoul region ap-northeast-2, CPU-only — HyperCLOVA X/embedding are external APIs, **no GPU**; backend + ai-engine via docker-compose, managed redundancy deferred — see [ADR-0003](docs/adr/0003-single-vm-seoul.md); the PWA is a static build served off-VM by Vercel — see [ADR-0008](docs/adr/0008-frontend-static-hosting.md)), log-based latency measurement, offline cache fallback mode |
=

## Non-negotiable design constraints

These came out of explicit risk mitigation decisions in the planning doc — don't casually "simplify" them away:

- **No continuous location tracking — coordinates are received per request and stored or logged nowhere.** Location is read once, at notification-open time, and is session-scoped only. The 「밖이에요」 branch sends `lat`/`lng` with `POST /v1/shelters/search` (`ShelterSearchRequest` in `packages/contracts/openapi.yaml`); the route uses them inside that request (`hazard_match`, `repository.search`) and writes them to no session, event log, DB, or file. The claim is therefore 「받되 저장하지 않는다」 — **not** 「받지 않는다」, even though 기획서 v3 ch.4 says the stronger form; that discrepancy is recorded, not papered over, in [ADR-0011](docs/adr/0011-m3-no-storage-not-no-receipt.md) (Accepted, 2026-08-24). Moving 행정동 resolution and shelter selection client-side — which would remove the endpoint but also move the **server-side safety filter** (지하 시설 제외 under 호우·침수, 계단 이용 불가자 정렬 — [docs/공통_가이드/워킹_스켈레톤_설명.md](docs/공통_가이드/워킹_스켈레톤_설명.md) §2-3) — was considered and rejected for the finals window. Verification checks *that nothing was stored or logged*, by scan.
- **SAVERS does not judge hazard itself.** The government's live assessment is authoritative; adding a self-derived warning would put the guidance ahead of the official 특보.
- **Generation must be evidence-grounded.** The agentic LLM layer must answer only from retrieved 국민행동요령 source text; the guardrail prompt exists specifically to suppress hallucination, and its on/off effect is a measured KPI (see below) — don't remove or bypass it for convenience.
- **Zero install burden on the vulnerable user.** Registration/setup is designed to be done by a guardian/복지관/지자체 on the person's behalf, not by the end user. Any feature that requires the vulnerable person to install an app or self-configure conflicts with this.
- **Offline/degraded fallback required.** If the public disaster APIs are down or slow, the system must fall back to a pre-cached shelter/action-manual mode rather than failing silently.
- **Minimal collection, encrypted.** Sensitive fields (location, disability status) are minimally collected and encrypted; treat this as a hard requirement when adding new user fields.
  **There is exactly one scoped exception, and it is not a general licence**: the session store writes its rows in plaintext — session token and generated message body, the latter carrying mobility constraints tied to a `user_id` ([ADR-0022](docs/adr/0022-session-store-plaintext.md), Accepted 2026-08-28).
  Application-level encryption is deferred past the finals there because the key would live on the same VM as the ciphertext, so it does not stop the threat it appears to; file permissions (0600) and the absence of a backup pipeline are what actually close the two reachable cases.
  **That exception holds only while the registry carries fabricated demo personas and no record identifying a real vulnerable person.** ADR-0022 names that as its own 유효 조건 — the moment such a record enters, the exception lapses and this constraint applies unamended.
  It covers the session store and nothing else: every other sensitive field stays under the rule above.

## Quality bar / evaluation methodology (build these as code, not manual review)

The team's differentiation strategy is that quality is proven by **reproducible automated scripts**, submitted alongside the code, not by human surveys. 기획서 v3 names **four metrics**, and the scoring script, eval set, and training code ship with them:

- **알림 도달 속도** — end-to-end latency from the moment `run_alert` starts handling that alert
  to the **first** `push_accepted` — the moment FCM accepts a send for the first of that recipient's ward devices
  **to be accepted**, which is not necessarily the first one tried: an earlier device can fail and a later one land.
  Target ≤30s, measured as p95 over `Delivery.latency_ms` (`AlertRun.p95_latency_ms`) — OpenTelemetry is not wired yet,
  so do not describe this as an OTel span.
  ⚠️ `Delivery.latency_ms` currently stops **after** that recipient's whole device loop, not at the first acceptance,
  so with two or more ward devices it reads higher than the definition — the code moves, not the definition
  ([ADR-0013](docs/adr/0013-m1-measures-push-acceptance.md) 후속 조치, Backend).
  The end is a contract event; the start is a run-level clock with no contract event of its own.
  The start is **not** `alert_dispatched`: that event is stamped inside the per-recipient loop,
  after shelter search and generation, so anchoring there would push the generation span outside the 30s.
  Acceptance is **not** device arrival —
  `push_delivered` is deliberately not used, since it reads acceptance as delivery.
  The start is **not** 특보 발령 (`DisasterEvent.issued_at`),
  so the intake delay before the pipeline sees the alert sits outside the 30 seconds:
  public-API polling is deferred past the finals, so that delay cannot be measured yet
  ([ADR-0013](docs/adr/0013-m1-measures-push-acceptance.md) **Accepted** — 2026-08-26 Tech Lead 승인).
  **Requires real FCM sending**; with the recording dispatcher this metric cannot be measured at all.
- **보호자 응답 정확도** — **zero statements not grounded in the log.** Scored against a 40-case guardian golden set (30 recommended questions + 10 free-form "기타"). When in doubt the system must refuse: under-refusal (answering something absent from the log) breaks the metric directly, over-refusal only costs coverage.
- **위치정보 무저장·무로깅 (coordinates are stored or logged nowhere)** — target is **zero points where a coordinate is written to a session, event log, DB, or file**. The proof is `scripts/check_privacy.py` scanning the tree for storage/logging sites — **the script is merged and wired into CI**, running as part of the [`e2e.yml`](.github/workflows/e2e.yml) end-to-end job and publishing a `privacy-check-report` artifact (details in [docs/공통_가이드/개인정보_체크리스트.md](docs/공통_가이드/개인정보_체크리스트.md) §4). Reworded twice: from 「위치정보 즉시 파기 준수율 100%」 to 「미수신」 on **2026-08-21** (`SessionStore` has no delete/purge method, so "purged" cannot be proven), then to 「무저장·무로깅」 on **2026-08-22** because `/v1/shelters/search` does receive `lat`/`lng`, so 「미수신」 was refutable from `openapi.yaml` alone. Decision record: [ADR-0011](docs/adr/0011-m3-no-storage-not-no-receipt.md) (**Accepted**, 2026-08-24); working rationale in [docs/공유_문서/정량목표_검증설계.md](docs/공유_문서/정량목표_검증설계.md) §3.
- **폐루프 2차 발송 성공률** — 100%. 30 minutes of no response must produce a guardian escalation that actually lands.
  **The escalation goes out on the same web push (FCM) path as the first dispatch —
  there is no second-dispatch-only channel, and SMS is adopted for neither**
  (same channel, different recipient device: first dispatch to the ward's,
  escalation to the guardian's, split by a role value in the contract)
  ([ADR-0014](docs/adr/0014-closed-loop-second-dispatch-channel.md) **Accepted** —
  2026-08-25 안은남·김도혁 확인, 확정),
  and the metric is measured from that path's `guardian_notified` event.
  기획서 2장 [그림 5]·5장의 「보호자 SMS(예정)」 is the stale wording that says otherwise;
  it is answered in the 정정 항목 표, not by adding a channel.

The shelter-suitability model is scored separately by the **3-fold validation** described above. Its third-stage (model) numbers are **not yet measured** — 기획서 [표3] currently carries target ranges quoted from comparable PU-learning studies, and they must be replaced with the team's own measurements before the finals. **If the model does not beat the rule-based second stage, that is recorded as a failure case** rather than dressed up; not packaging a rule-based result as a model is the line this team holds.

**Under-target results are published as failure cases, not hidden** — the 기획서 committed to that, and it is the basis of the team's credibility claim. The prelim-era metrics (근거 일치율, 환각 억제율, 메시지 명확성) measured the 국민행동요령 corpus RAG; their harness remains in `apps/ai-engine/eval/`, but the four metrics above are the submitted headline numbers.

## Team / module ownership

The team registered with six people; **two left for personal reasons, so it is now four**, and responsibilities were redistributed twice (the selection requirement of 3–6 members is still met). The two vanished roles were absorbed, not dropped: Frontend/UX went to AI/RAG, and QA/Security **plus infrastructure** went to PM.

| Person | Position | Owns |
|---|---|---|
| 안은남 | 팀장 · PM · QA/보안 · 인프라 | Integration, risk, finals presentation **+ quality/security adjudication** — writes no feature code, which is precisely what makes the verdict independent **+ infrastructure**: `infra/`, deployment, server ops, instrumentation **+ threshold experiments** (guardrail similarity floor, SUPPORT_THRESHOLD, over-refusal tuning). Also owns the 40-case guardian golden set and the **five-case failure-mode demo script**. |
| 신호정 | Tech Lead (design/contract only) | System architecture, **ownership of inter-module contracts**, verifier rules + closed-loop state-transition spec, design approval, **code-freeze declaration**, finals technical Q&A. **Writes no code** — two reasons: an implementer who also designs will diverge under a compressed schedule, and someone with no code in the tree can freeze it without a conflict of interest. Decisions are recorded as ADRs in `docs/adr/`. |
| 김소원 | AI 모델 · RAG · 프론트엔드 | Shelter-suitability model training/validation/SHAP, guardian RAG **generation + log-matching verifier**, frontend (3-step traffic light, SHAP map, Q&A block). Generation and verification are one flow, so one person owns both. **Zero schedule buffer** — the cut-down cards are pre-agreed (drop free-form "기타" first, then revert SHAP to three fixed cards). |
| 김도혁 | Backend | Flood-avoiding route (**OSMnx + networkx**, not OSRM), **event-log pipeline** (capture/store/query), FCM real-send reconnection, guardian second dispatch, closed-loop orchestration. The verifier and the generator both run on top of this log, so the foundation is his. |

> 등록 인원은 6명이었으나, 이진호는 초반에 이탈해 표에 실린 적이 없다.
> 이후 최혜리도 중도 하차했다 — 등록 6인 중 중도 하차 2인(이진호·최혜리)이 빠져 4인 체제가 됐다.
> 최혜리의 Frontend/UX는 김소원이, QA/Security·Infra는 안은남이 흡수했다.
> 전체 팀·모듈 오너십 서술은 위 표를 갱신 대상 원본으로 삼는다.

Two boundaries are load-bearing and easy to get wrong: **infrastructure belongs to PM** (but on finals day the *primary* on-site infra responder is Backend, because PM is on stage — judgement is PM's, hands are Backend's; the **8/29 demo deploy is done by PM alone**, which is why PM must have run the whole cycle solo on 8/26), and **Tech Lead writes no code**. Per-role detail lives in [docs/역할_가이드/](docs/역할_가이드/README.md), timing in [docs/역할_일정/](docs/역할_일정/README.md).

## Naming convention (documents & folders)

The rule has two halves — which half applies is decided by **what the folder holds, not where it sits**:

- **Documents → Korean.** Planning/design documents and the folders that group them are Korean-named (`아키텍처.md`, `리스크.md`, `docs/역할_가이드/`, `docs/역할_일정/`, …), using an underscore-separated `A_B` pattern for multi-word names.
- **Everything else → English, mandatory.** Any folder that is not a document folder — code, config, assets, tooling, data, test fixtures, CI — **must** be English-named, always, with no Korean-name exception available. This is not a stylistic preference: these paths are consumed by build tools, import statements, Docker/CI configs, and shell scripts, where non-ASCII path segments cause encoding and portability failures. A Korean folder name appearing anywhere under `apps/`, `packages/`, `infra/`, or `.github/` is a defect to be renamed, not a judgment call.

Within the Korean half, keep these agreed **English exceptions**: `CLAUDE.md`, `AGENTS.md`, `README`, `docs/adr/` (ADR filenames), and `docs/pr-checklist.md` (inherited from the repo template) — all of them tool- or convention-bound names. Apply this when creating any new planning doc: new project-level docs default to Korean names unless they fall under an exception; new non-document folders are English without exception.

All planning docs live under `docs/`; the repo root keeps only `AGENTS.md`, `CLAUDE.md`, and `README.md`. Put a new doc in the folder that matches its axis:

| Folder | Holds |
|---|---|
| `docs/공통_가이드/` | Project-wide design docs everyone reads — `개발자_가이드.md`, `환경_세팅_가이드.md`, `배포_절차.md`, `서버_운영.md`, `AWS_계정_발급_가이드.md`, `저장소_운영.md`, `아키텍처.md`, `워킹_스켈레톤_설명.md`, `워킹_스켈레톤_점검.md`, `리스크.md`, `구현_범위.md`, `외부_승인.md`, `비용_산정.md`, `개인정보_체크리스트.md`, `후속_과제.md` |
| `docs/역할_가이드/` | Per-role playbooks — who does what. `01-기획총괄.md` … `04-백엔드.md` (four positions since the 2026-08-11 reshuffle) |
| `docs/역할_일정/` | Per-role timelines — when it must be done. Same role numbering as `역할_가이드/` |
| `docs/공유_문서/` | Continuously revised working documents (인터뷰 가이드, 회의 결과, …) — **not** competition submission forms, which stay out of the repo per "Not in this repository". Its `README.md` is the index — every file listed with 최종 수정일 · 버전 · 핵심 내용 · 상태·근거, updated in the same PR as the file itself |
| `docs/adr/` | Architecture decision records (English filenames) |
| `docs/pr-checklist.md` | PR procedure, inherited from the template |

`역할_가이드/` and `역할_일정/` are 1:1 by role number — adding or removing a role means editing a file in both.

### Prose style and character set

Naming decides where a doc goes; **[docs/공통_가이드/문서_작성_규약.md](docs/공통_가이드/문서_작성_규약.md) decides how it reads.** Two axes, deliberately scoped differently:

- **경어체 for Korean docs**, with `docs/adr/` staying 평서형 — that is the register of a decision record and all nine existing ADRs already use it. Don't mix the two inside one file.
- **Keyboard-typable characters only in `docs/adr/` and `docs/공유_문서/`** — those texts get quoted by other documents or copied into submission forms that live outside this repo, and whoever retypes them cannot type a glyph their keyboard lacks. Everywhere else (guides, role docs, README, this file) ⚠️-style markers earn their keep as scan anchors, so they stay.

That guide carries the full scope table, the substitution table, the inherited-violation counts, and a pre-commit check script. One sub-rule applies to **every** markdown file regardless of scope: **space both sides of a tilde** (`1 ~ 2`), or GFM pairs it with the next one and strikes through everything between.

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

Given this team's constraints — 6 people at ADR-0001's decision time (four now — see "Team / module ownership" above), a short hackathon timeline, and a **front-loaded Tech Lead (early-concentration model)** — the coordination cost and integration debt of a multi-repo org outweigh its benefits. **This project uses a single monorepo**, while keeping AI as an independently deployable service inside it to satisfy the winning-pattern substance ([ADR-0001](docs/adr/0001-monorepo.md)). Actual layout:

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
- **Review comments follow a written format**, not taste: [docs/공통_가이드/코드_리뷰_가이드.md](docs/공통_가이드/코드_리뷰_가이드.md) — verdict-bearing headings, one of four handling labels (`머지 전 필수` / `이 PR에서 권장` / `후속 과제` / `참고, 조치 불필요`) next to each heading, and a confidence label on any claim you did not verify. Its §1-a checklist is the review counterpart of the architecture rules above. **Never comment on style, formatting, import order, or types** — ruff and mypy already decide those deterministically, and a human repeating them teaches the team to discount every review comment.
- **Team messenger text follows a different convention**: conclusion on the first line, details behind a link, 5 lines max — [docs/공통_가이드/메신저_규약.md](docs/공통_가이드/메신저_규약.md). It exists partly to enforce the rule below: anything agreed in a chat is 검토 중 until it lands in an ADR, so a long message is a sign the content belongs in the repo instead.
- CI (ruff · mypy · pytest) and pre-commit enforce the same rules on purpose. If they drift apart, people start ignoring the hooks — fix the drift, don't route around it.
- Repo settings (branch protection, merge strategy, labels) live only on GitHub's side — git does not track them and they never show up in a diff; they are re-applied by `scripts/setup-github.sh`. Details, the manual checklist, and the required-check contract: [docs/공통_가이드/저장소_운영.md](docs/공통_가이드/저장소_운영.md).
- Architecture decisions go in `docs/adr/` as they are made. This is the anti-bus-factor mechanism for the front-loaded Tech Lead model — an undocumented decision is a decision the team loses.
- **`docs/adr/` is the single source of truth for "확정" (confirmed).**
  An item that cannot be traced to an ADR number is **검토 중** (under review), not 확정 — this applies to everyone, no exceptions.
  Any document meant for outside readers (역할_가이드, 공통_가이드, etc.) marks each confirmed item with a one-line source, and **that source is an ADR number** — a path to another guide document does not qualify, because a guide citing itself is exactly the failure this rule exists to stop.
  An item with no source line is a signal it hasn't actually been decided yet.
  If something needs to be promoted to 확정, flag it to the Tech Lead to write the ADR — verbal agreement is not a contract in this repo (see the `Contracts before implementation` rule above), so writing it down is the Tech Lead's job, not the reporter's.
  Existing documents are brought into line when you are already editing them for another reason; no separate cleanup PR — same as the line-wrapping rule above.
