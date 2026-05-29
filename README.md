<div align="center">

# ForgeJudge

**An open, always-on leaderboard and CI gate for autonomous coding agents — every patch runs in a sandbox, every run has a public trace, every regression fails the build.**

[![CI](https://github.com/ahmedEid1/forgejudge/actions/workflows/ci.yml/badge.svg)](https://github.com/ahmedEid1/forgejudge/actions/workflows/ci.yml)
[![regression gate](https://github.com/ahmedEid1/forgejudge/actions/workflows/gate.yml/badge.svg)](https://github.com/ahmedEid1/forgejudge/actions/workflows/gate.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org)

**▶ Live leaderboard: [forgejudge.pages.dev](https://forgejudge.pages.dev)** · [methodology](https://forgejudge.pages.dev/methodology) · [model swap](https://forgejudge.pages.dev/model-swap)

</div>

> **Current numbers** (hidden-test, $0 free tier, same harness): `llama-3.3-70b` resolves **10/12 (83.3%)**, `llama-3.1-8b` **8/12 (66.7%)** — the score rises with the better model while the harness stays fixed. Every run [deep-links its Langfuse trace](https://forgejudge.pages.dev).

ForgeJudge is the only open-source autonomous software-engineering agent that **proves its quality in public on every commit**: a hand-rolled single-agent solver, a deterministic execution-as-judge harness, an always-on leaderboard with per-run traces, and a CI gate that blocks regressions — all on a **`$0` / self-hostable** stack against a **contamination-resistant, intrinsically-verifiable** golden set.

> **The engineered harness, observability, and gate are the deliverable — not a high resolution rate.** A `$0` free-model agent will score modestly *by design*. We prove value with a **model-swap comparison**: the score rises with a better model while the harness stays fixed.

## How it works

```
golden set (Git, canonical) ──▶ agent: localize ─▶ repair ─▶ validate ──▶ unified diff
   12 intrinsically-verifiable        (BM25)      (LLM router,  (run tests)
   make-CI-green tasks                            critic, edit-gate)
        │                                              │ every step traced (OTel → Langfuse)
        ▼                                              ▼
   deterministic harness  ◀── apply test_patch + patch, run F2P/P2P in a sandbox ──┐
   resolved ⇔ all FAIL_TO_PASS pass ∧ all PASS_TO_PASS stay green                  │
   (verified equivalent to the official swebench grading; cheat-resistant)         │
        │                                                                          │
        ▼                                                                          │
   run store (Neon) ─▶ leaderboard (pass@1/pass@3, $/task, tokens, trace link) ────┘
   multi-seed CI gate: a PR that lowers the resolution rate fails the build
```

- **Solver** — a single, phase-structured loop (`localize → repair → validate`), *not* a multi-agent swarm: cheapest, most deterministic, most debuggable. BM25 localization, an LLM router over free tiers, a syntax edit-gate, a cheap critic pre-filter, and a cost/step budget with autosubmit.
- **Harness** — encodes the SWE-bench `RESOLVED_FULL` rule and is **verified equivalent to `swebench.harness.grading`** in CI. Patches are **cheat-resistant**: the canonical test files are restored before grading, so a patch can't neuter the oracle.
- **Golden set** — 9 purpose-built post-cutoff fixtures + 3 tasks mined from the author's own repos (real commit SHAs, MIT/own license — zero leak/copyleft risk). Each is **mutation-hardened**: a wrong fix to the patched region is caught (7 mutation-hardened at mean score 0.89; 5 inconclusive for regex/string code; **0 weak**).
- **Sandbox / CI / cron** — GitHub Actions on a public repo does triple duty (ephemeral isolated VM sandbox + regression gate + scheduled sweep) at `$0`.
- **Observability** — OpenTelemetry GenAI spans (`invoke_agent → retrieval / chat / execute_tool`, `gen_ai.usage.*`, a `gen_ai.evaluation.result` pass/fail verdict) exported to Langfuse Cloud; every run is a clickable trace.

## Quickstart

```bash
git clone https://github.com/ahmedEid1/forgejudge && cd forgejudge
uv sync                       # Python 3.12, deps via uv

# Run the deterministic harness self-test (no API key, no network):
uv run python -m forgejudge.harness.runner_actions --patch-source gold   # 12/12 resolved

# Solve a task with a free model (set GROQ_API_KEY) and grade it:
uv run python - <<'PY'
from forgejudge.golden.loader import load_tasks
from forgejudge.agent.solver import solve
from forgejudge.harness.grade import grade
task = {t.instance_id: t for t in load_tasks("golden/dataset.jsonl")}["fixture-semver-001"]
res = solve(task, run_id="demo", budget_usd=0.10, seed=0)
print(res.status, "→ resolved:", grade(task, res.patch).resolved)
PY
```

Fast tests: `uv run pytest -m "not slow"`. Full golden validation + mutation hardening: `uv run pytest -m slow`. Sweep the leaderboard: `uv run python -m forgejudge.eval.sweep --model groq/llama-3.3-70b-versatile --seeds 0,1,2`.

## Six objections, pre-empted

1. **"Your benchmark is contaminated / cherry-picked."** The golden set is freshly authored / post-cutoff, sourced only from the author's own repos + fixtures (no third-party leak surface), and **mutation-hardened** so a wrong patch can't pass. SWE-bench Verified is now widely held contaminated — OpenAI [stopped reporting it](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/) (2026-02); >32% of "passed" cases [leaked the solution](https://arxiv.org/abs/2410.06992) and ~31% passed on weak tests. Decontamination here is a documented, tested property — not a footnote.
2. **"Thin wrapper around an LLM / a framework."** The orchestrator is hand-rolled (no LangChain): the control loop, the sandbox-and-score harness, the cheat-resistant grader, the mutation hardener, the OTel instrumentation, and the multi-seed CI gate are the work.
3. **"Your resolution rate is low vs SOTA."** SOTA is ~88–94% with premium models and budgets; a `$0` free-model number is modest *on purpose*. The deliverable is the engineered system; the **model-swap comparison** (score rises with a better model, harness fixed) is the proof.
4. **"Is it actually autonomous or staged?"** Every run has a public OpenTelemetry/Langfuse trace and a deterministic, reproducible score. The replay-first playground demos a real solve without exposing cost/abuse surface.
5. **"Three agent projects — one-trick pony?"** One eval methodology — golden set + judge + traces + CI gate — across three domains at rising autonomy (Lumen → Thoth → ForgeJudge).
6. **Determinism.** temperature=0 does [not guarantee determinism](https://arxiv.org/pdf/2602.07150) (pass@1 varies 2–6pp). The scorer is fully deterministic; the **gate is multi-seed** (fail only when the candidate's CI upper bound is below the baseline's CI lower bound), so flaky single runs don't break the build.

## Repository layout

| Path | What |
|---|---|
| `forgejudge/golden/` | golden-set loader, fixture contract, dataset builder, mutation hardener |
| `forgejudge/harness/` | deterministic `grade()`, cheat-resistant runner, swebench-equivalence check, sandbox executor |
| `forgejudge/agent/` | `localize → repair → validate` solve loop, critic |
| `forgejudge/llm/` | role-based LiteLLM router with fallback + cost accounting |
| `forgejudge/obs/` | OpenTelemetry GenAI tracing → Langfuse / Phoenix |
| `forgejudge/eval/` | scheduled sweep, multi-seed regression gate, LLM-as-judge + Cohen's κ |
| `forgejudge/store/` | Neon (Postgres + pgvector) run store + leaderboard query |
| `golden/dataset.jsonl` | canonical golden set (one `Task` per line) |
| `.github/workflows/` | `ci`, `eval` (sandbox), `sweep` (cron), `gate` (regression) |

## License

[MIT](./LICENSE) © 2026 Ahmed Hobeishy. Imports and attributes the MIT-licensed [`swebench`](https://github.com/SWE-bench/SWE-bench) grading harness.
