# Transcribe Runtime-Neutral Migration Plan

> **For Hermes:** execute phase by phase, verify locally after each phase, then send a concise status update to Grok before continuing.

**Goal:** Make the shared transcribe skill feel runtime-neutral across Hermes, OpenClaw, pi agent, nanobot, Codex CLI, and similar hosts, while preserving Step 3 execution stability and backward compatibility for existing Hermes users.

**Architecture:** Keep the skill layout intact under `skills/transcribe/`. First clean up public docs and prompts without changing runtime behavior. Then add a compatibility layer so Step 2A prefers OpenAI-compatible `base_url + api_key` config while still falling back to Hermes host config. Finish by adding repo-level CI and running verification.

**Tech Stack:** Python 3.11+, TOML config, dotenv-style local env files, GitHub Actions, pytest.

---

## Phase 1 — Public wording + repo hygiene

**Objective:** Remove Hermes-first public wording while preserving Step 3 role-binding and improve repo maturity signals.

**Files:**
- Modify: `README.md`
- Modify: `skills/transcribe/SKILL.md`
- Modify: `skills/transcribe/prompts/final_delivery/final_adjudication.md`
- Modify: `skills/transcribe/.env.example`
- Create: `.github/workflows/ci.yml`

**Acceptance criteria:**
- Public docs describe the skill as cross-agent or runtime-neutral.
- Step 3 language still binds the currently-running live agent as the sole final adjudicator.
- `.env.example` asks for `FUNASR_API_KEY`, `AUXILIARY_BASE_URL`, and `AUXILIARY_API_KEY`.
- CI workflow lives under repo root and runs tests from `skills/transcribe/`.

## Phase 2 — Runtime compatibility layer for config resolution

**Objective:** Make Step 2A config OpenAI-compatible first, Hermes-compatible second, without breaking existing Hermes installs.

**Files:**
- Modify: `skills/transcribe/scripts/auxiliary_config.py`
- Modify: `skills/transcribe/scripts/funasr_config.py`
- Modify: `skills/transcribe/config/models.toml`
- Create: `skills/transcribe/config/auxiliary.local.example.toml`
- Modify: `skills/transcribe/tests/test_auxiliary_config.py`
- Modify: `skills/transcribe/tests/test_pipeline.py`
- Add or update any other focused tests touched by the config change

**Acceptance criteria:**
- Step 2A can resolve config from skill-local env/config using `AUXILIARY_BASE_URL` and `AUXILIARY_API_KEY`.
- Hermes config remains as fallback.
- FunASR still works with current local TOML/env flow and also recognizes `FUNASR_API_KEY` cleanly.
- Tests cover both new generic flow and Hermes fallback flow.

## Phase 3 — Verification + polish

**Objective:** Run tests, inspect diffs, and tighten any stale wording or compatibility gaps discovered during implementation.

**Files:**
- Modify only if verification reveals necessary follow-up fixes

**Acceptance criteria:**
- Targeted config tests pass.
- Prompt-focused tests pass.
- Full repo diff is coherent.
- Grok sign-off after the final phase shows no obvious architecture regressions.
