# CLAUDE.md

This file provides guidance to **Claude Code** (claude.ai/code) when working in this repository.

Project context (what SAVERS is, architecture, tech stack, non-negotiable constraints, quality bar, team ownership, monorepo layout) lives in the shared, tool-neutral brief so that every agent — Claude Code, Codex, Antigravity — reads the same source of truth:

@AGENTS.md

Read `AGENTS.md` first; treat it as authoritative. Everything below is **Claude-Code-specific** and does not belong in the shared brief.

## Claude-Code-specific notes

- **Persistent memory.** Standing project decisions are tracked in Claude's auto-memory (indexed in `MEMORY.md` under the memory dir): monorepo-vs-multirepo + Tech-Lead front-loading, the single-CPU-VM infra decision (ADR-0003), the 2-stage prelim/finals timeline, and the 한글 문서 명명 규약. Recall/update these instead of re-deriving them; they reflect state at write-time, so verify any file/flag they name still exists before acting on it.
- **Response contract.** Follow the global `~/.claude/CLAUDE.md`: reply in Korean, English code comments, label uncertain technical claims (확실한 사실 / 높은 신뢰 / 추정 / 불확실), minimal output for coding tasks, and no scope expansion without approval.
- **Keeping the brief in sync.** When a change alters project-wide facts (architecture, constraints, KPIs, team, repo layout), edit `AGENTS.md` — not this file. Add here only guidance that is meaningful solely to Claude Code.
