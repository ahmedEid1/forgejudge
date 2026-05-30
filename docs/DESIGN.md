# ForgeJudge — Technical Design

> An open, always-on leaderboard and CI gate for autonomous coding agents: every
> patch runs in a sandbox, every run has a public trace, every regression fails
> the build.

This document is the engineering deep-dive behind
[`forgejudge.ahmedhobeishy.tech`](https://forgejudge.ahmedhobeishy.tech). It is
written to be checked against the code — every claim below points at a file you
can read. Where a number appears, it is the current measured value, not an
aspiration.

## Table of contents

1. [Thesis](#1-thesis)
2. [Architecture and data flow](#2-architecture-and-data-flow)
3. [Components in depth](#3-components-in-depth)
   - [3.1 BM25 localization](#31-bm25-localization)
   - [3.2 The LLM router](#32-the-llm-router)
   - [3.3 The repair step: edit-gate + critic pre-filter](#33-the-repair-step-edit-gate--critic-pre-filter)
   - [3.4 The cheat-resistant grader](#34-the-cheat-resistant-grader)
4. [Credibility properties](#4-credibility-properties)
   - [4.1 Decontamination](#41-decontamination)
   - [4.2 Mutation hardening](#42-mutation-hardening)
   - [4.3 SWE-bench equivalence — and where it is deliberately stricter](#43-swe-bench-equivalence--and-where-it-is-deliberately-stricter)
5. [The multi-seed regression gate](#5-the-multi-seed-regression-gate)
6. [Observability](#6-observability)
7. [The $0 / self-hostable stack](#7-the-0--self-hostable-stack)
8. [Engineering quality](#8-engineering-quality)
9. [Key design decisions, trade-offs, and limitations](#9-key-design-decisions-trade-offs-and-limitations)

---

## 1. Thesis

**The engineered harness, observability, and gate are the deliverable — not a
high resolution rate.**

A `$0` free-model agent will score modestly *by design*. ForgeJudge does not try
to win a resolution-rate race; it tries to be a *trustworthy measuring
instrument* for autonomous coding agents, and then proves that the instrument
works by swapping the model underneath it while holding everything else fixed.

The proof is the **model-swap comparison**. Same golden set, same
`localize → repair → validate` loop, same deterministic grader, same seeds — only
the model id changes. The score tracks the model:

| Model | pass@1 | pass@3 |
|---|---|---|
| `groq/openai/gpt-oss-120b` | 90.7% | 100% |
| `groq/llama-3.3-70b-versatile` | 88.9% | 94.4% |
| `groq/llama-3.1-8b-instant` | 48.1% | 66.7% |

(18 tasks × 3 seeds = 54 runs per model, **162 runs total**; numbers are the live
values in [`dashboard/public/data/leaderboard.json`](../dashboard/public/data/leaderboard.json),
produced by the `db.leaderboard()` query in
[`forgejudge/store/db.py`](../forgejudge/store/db.py).)

Two things in that table are load-bearing:

- The rate **rises with the stronger model** while the harness is fixed. That is
  the evidence that the harness measures *agent capability*, not harness quirks —
  an 8B model cannot fake its way to 90%.
- `pass@3 > pass@1` on every row. That gap is real run-to-run variance (the agent
  is stochastic), which is *exactly why the CI gate is multi-seed* — a single
  flaky run must never break the build. See [§5](#5-the-multi-seed-regression-gate).

The orchestrator is hand-rolled. There is no LangChain, no agent framework, no
multi-agent swarm. The control loop, the sandbox-and-score harness, the
cheat-resistant grader, the mutation hardener, the OpenTelemetry instrumentation,
and the multi-seed CI gate **are the work**.

---

## 2. Architecture and data flow

```
                          golden set (Git, canonical)
                          18 intrinsically-verifiable
                          make-CI-green tasks
                          golden/dataset.jsonl
                                   │
                                   │ load_tasks()            forgejudge/golden/loader.py
                                   ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  SOLVER  (single agent, phase-structured loop)                 │
        │  forgejudge/agent/solver.py — solve()                          │
        │                                                                │
        │   localize ──▶ repair ─────────────▶ validate                  │
        │   (BM25)       (LLM router →          (run PASS_TO_PASS in a    │
        │                 syntax edit-gate →     sandbox; no-regression   │
        │                 critic pre-filter)     gate; hidden oracle)     │
        │   localize.py   repair.py / router.py  materialize.py          │
        │                 / critic.py                                    │
        │                                                                │
        │   every step traced (OTel GenAI spans → Langfuse)  obs/tracing.py │
        └───────────────────────────────┬───────────────────────────────┘
                                         │ unified diff (source only)
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  HARNESS  (deterministic execution-as-judge)                   │
        │  forgejudge/harness/grade.py → runner_local.py → materialize.py│
        │                                                                │
        │   1. copy base/  →  git init  →  apply test_patch  →  commit   │
        │   2. apply candidate patch (3-way; non-apply = unresolved)     │
        │   3. CHEAT-RESISTANCE: restore every test_patch path to HEAD;  │
        │      strip/revert candidate-added conftest/sitecustomize       │
        │   4. run each F2P + P2P node id in its own pytest process,      │
        │      per-node timeout, junit-xml → real PASSED/FAILED/SKIPPED  │
        │   resolved ⇔ all FAIL_TO_PASS pass ∧ all PASS_TO_PASS stay green│
        └───────────────────────────────┬───────────────────────────────┘
                                         │ RunRecord (resolved, counts, cost, tokens, trace_url)
                                         ▼
        ┌───────────────────────────────────────────────────────────────┐
        │  RUN STORE (Neon: Postgres + pgvector)   store/db.py           │
        │  leaderboard(): pass@1 / pass@k / $-per-task / tokens / trace  │
        │      │ export_snapshot()  store/export.py                      │
        │      ▼                                                          │
        │  static JSON → Cloudflare Pages dashboard (always-on, $0)      │
        └───────────────────────────────────────────────────────────────┘

   GATES (GitHub Actions on every PR / on cron)
   ├─ gate.yml  → exact_gold_gate()  : deterministic, re-grade gold, rate must == 1.0
   └─ sweep + regression_gate()      : stochastic multi-seed CI (Student-t / Wilson)
```

Three properties of this shape matter:

- **`localize → repair → validate` are sequential *stages of one loop*, not
  concurrent sub-agents.** The roles (`plan`, `localize`, `edit`, `critic`,
  `judge`) are prompt roles routed to models, not autonomous actors. This is an
  Agentless-style design chosen for being the cheapest, most deterministic, and
  most debuggable option. See the module docstring in
  [`forgejudge/agent/solver.py`](../forgejudge/agent/solver.py).
- **The grader is the only thing that decides pass/fail, and it is deterministic.**
  The agent is stochastic; `grade()` is not. `GradeResult.resolved` is a
  *computed* property (`forgejudge/types.py`) — it can never disagree with the
  underlying test counts.
- **The canonical golden set lives in Git, not the database.** The Neon copy is
  derived (`store/db.py`, `store/export.py`); a fresh clone reproduces every
  task and every gold patch offline.

---

## 3. Components in depth

### 3.1 BM25 localization

File: [`forgejudge/agent/localize.py`](../forgejudge/agent/localize.py).

The agent edits *source*, so before it can propose a patch it must pick *which*
file to touch. `localize(task, repo_dir, *, top_k)` does this with **BM25 lexical
retrieval** over the `bm25s` library — pure-Python, no database, no network, `$0`.

- Each non-test `.py` file becomes a document of `file contents + path tokens`,
  so a filename like `semver.py` that echoes a symbol in the issue contributes to
  the score (`_collect_candidates`, `documents` construction).
- The query is the task's `problem_statement` plus the basenames/symbols pulled
  out of the failing-test node ids (`_build_query` — e.g.
  `test_semver.py::test_compare` contributes `test`, `semver`, `compare`).
- Identifiers are split before scoring: `calculate_discount` and `parseUrl` each
  also match as their snake/camel components (`_expand_identifiers`). This is the
  difference between a query term matching a real function and matching nothing.
- Test files are excluded from the candidate set by `_is_test_file` (the same
  predicate the solver reuses for its fallback target, so localizer and fallback
  can never disagree about what counts as editable source).
- Only positively-scored hits are returned, so the localizer never surfaces a
  file that shares no terms with the task; the solver falls back to the first
  non-test `.py` file when BM25 returns nothing (`_fallback_target` in
  `solver.py`).

The module documents a deliberate non-goal: a dense pgvector + cross-encoder
rerank stage could slot in *behind the same `localize(...) -> list[str]`
signature* without callers noticing. That work is out of scope; the current
stage is BM25-only with no DB, and the public contract is pinned so the upgrade
is non-breaking.

### 3.2 The LLM router

File: [`forgejudge/llm/router.py`](../forgejudge/llm/router.py), config
[`forgejudge/llm/models.yaml`](../forgejudge/llm/models.yaml).

Every agent role maps to an **ordered fallback chain** of litellm model ids.
`complete(messages, *, role, run_id, model=None, seed=None)` walks the chain and
returns the first model that succeeds; if all fail it raises a `RuntimeError`
that names the chain it tried. The current chains favour free-tier Groq, with
Gemini preferred for the (secondary) judge:

```yaml
edit:    [groq/openai/gpt-oss-120b, groq/llama-3.3-70b-versatile]
critic:  [groq/llama-3.3-70b-versatile]
judge:   [gemini/gemini-2.5-flash, groq/llama-3.3-70b-versatile]
```

Four things the router does that a thin wrapper would not:

- **Cost ledger.** Each successful call adds `litellm.completion_cost(resp)` to a
  per-`run_id` ledger (`_LEDGER`), queryable via `run_cost()` and clearable via
  `reset_run()`. That ledger is what backs the agent's budget cap and the
  `$/task` column on the leaderboard. Unknown/free models cost `0.0` rather than
  crashing the run.
- **Rate-limit backoff that is distinct from hard failure.** Free tiers are
  routinely throttled, so a `litellm.RateLimitError` (429) is treated as
  *transient*: the **same** model is retried with bounded exponential backoff
  (`1s, 2s, 4s …`, capped at 30s), honoring a `Retry-After` header when present
  (`_retry_after_seconds`, `_backoff_seconds`), up to `_MAX_RATE_LIMIT_ATTEMPTS`
  (3) before the chain advances. A genuine auth/model/provider error advances to
  the next model immediately. This is the difference between "wait out the quota"
  and "this model is broken."
- **Real seed forwarding.** `seed` is passed through to `litellm.completion(...)`,
  so multi-seed sweeps actually perturb sampling on providers that honor it
  (reproducible-but-distinct draws). The seeds are not cosmetic — they are what
  the multi-seed gate's variance estimate is built from.
- **Single-model override.** Passing `model=` bypasses the chain with one fixed
  model. That is the mechanism behind the model-swap comparison
  (`forced_model_complete` in `forgejudge/eval/sweep.py`): same harness, one
  model, swept over seeds.

### 3.3 The repair step: edit-gate + critic pre-filter

Files: [`forgejudge/agent/repair.py`](../forgejudge/agent/repair.py),
[`forgejudge/agent/critic.py`](../forgejudge/agent/critic.py), driven from
`solve()` in [`forgejudge/agent/solver.py`](../forgejudge/agent/solver.py).

Each repair step asks the model for the **complete corrected contents of one
file** in a single fenced block, then runs the candidate through two filters
before it is allowed to touch the working tree:

1. **The syntax edit-gate.** `extract_code()` pulls the right block out of the
   reply — not the last block (models append usage examples that would silently
   overwrite the file with a one-liner) but **the longest block that parses as
   Python**, tolerating a missing closing fence on truncated output and CRLF.
   `is_valid_python()` then `ast.parse`s it; a syntactically broken edit is
   *reverted, never submitted* — the loop feeds the syntax error back and
   regenerates (`reverted_edits` is counted on the result).

2. **The critic pre-filter.** A cheap reviewer (`critique()`) sees the issue, the
   failing test, and the proposed file and must answer `APPROVE` or
   `REJECT: <reason>` on the first line. It runs *before* the expensive test
   execution, so an edit that plainly does not address the bug is rejected and
   the loop regenerates without paying for a full pytest run
   (`critic_rejections` is counted). The critic's spend is folded back into the
   run's cost ledger via the `_critique` tap in `solve()`, so the budget cap
   accounts for it.

Only after both filters pass is the file written and the tests run. The loop is
bounded by `max_steps` (default 6) and a USD `budget_usd` cap (default `0.10`)
with **autosubmit** — when the budget is spent the best diff so far is returned
rather than nothing.

The default mode is the **hidden-oracle** setup (`show_failing_test=False`),
which is the credible benchmark: the agent sees only the issue text and the buggy
code, the `FAIL_TO_PASS` test is *never shown* and is applied only at grading. In
that mode the in-loop success gate is "the existing `PASS_TO_PASS` tests still
pass (no regression)"; the hidden oracle decides resolution. (`show_failing_test=True`
is the easier test-driven mode used only for harness tests and demos.)

### 3.4 The cheat-resistant grader

Files: [`forgejudge/harness/grade.py`](../forgejudge/harness/grade.py),
[`forgejudge/harness/runner_local.py`](../forgejudge/harness/runner_local.py),
[`forgejudge/golden/materialize.py`](../forgejudge/golden/materialize.py).

`grade(task, patch)` materializes the task in a fresh temp tree and scores it.
The verdict is the exact SWE-bench rule, encoded once in
`GradeResult.resolved`:

```python
resolved = (f2p_passed == f2p_total) and (p2p_passed == p2p_total)
```

The interesting work is making that verdict **un-gameable**. A naive grader is
easy to cheat: a patch can neuter the oracle, register a pytest hook, or make the
failing test *skip*. `run_task_patch` closes each of these:

- **Restore every `test_patch` path before grading.** After applying the
  candidate, the grader resets each path the `test_patch` touched back to `HEAD`
  (`_test_patch_paths` parses `git apply --numstat`; the loop runs
  `git checkout HEAD -- <path>`). The canonical oracle is pinned, so a patch
  cannot weaken or delete the test. Crucially this resets *paths*, not node-id
  prefixes — a legitimate source edit that happens to share a file with a test is
  preserved (finding #35), where the old prefix-allowlist would have reverted the
  whole shared file.
- **Strip candidate-added auto-load files.** `conftest.py`, `sitecustomize.py`,
  and `usercustomize.py` are auto-imported by pytest/CPython *by name*, so a
  candidate that adds or edits one can register collection hooks, autouse
  fixtures, or `sys.modules` shadows that fake a FAIL→PASS without touching
  source. `_strip_candidate_autoload_files` diffs the tree against HEAD: a
  candidate-*added* hook file is deleted, a *modified/renamed/deleted* one is
  restored to HEAD (finding #7).
- **A failed candidate patch is a clean miss, never a crash.** If `git apply`
  (with a 3-way fallback) cannot apply the patch, the tree is reset to
  `base + test_patch` and the task is simply unresolved.

The execution engine lives in `materialize.run_nodeids_status_map`:

- **Per-node grading.** Each `FAIL_TO_PASS` / `PASS_TO_PASS` node id runs in its
  *own* pytest subprocess.
- **The status is pytest's *real* outcome, parsed from junit-xml — never the
  process exit code.** `_parse_junit_statuses` maps each `<testcase>` to a
  swebench `TestStatus`: no child → `PASSED`, `<failure>` → `FAILED` (incl.
  strict XPASS), `<error>` → `ERROR`, `<skipped type="pytest.xfail">` → `XFAIL`,
  any other `<skipped>` → `SKIPPED`. A node counts as *passed* only when its
  status is in `_PASSING_STATUSES = {PASSED, XFAIL}` — mirroring swebench's
  `test_passed`. This is why a `SKIPPED` test (which exits pytest with `rc==0`)
  is **not** read as a pass. (The junit parser also rejects any report containing
  a `DOCTYPE`/`ENTITY` to defend against XXE / billion-laughs, even though our
  own pinned pytest never emits one.)
- **Per-node timeout.** A candidate patch is applied to the source the oracle
  imports, so `while True: pass`, unbounded recursion, a deadlock, or a
  catastrophic-backtracking regex would otherwise hang the grader forever.
  `_run_pytest` runs each node in its own session (`start_new_session=True`) and,
  on timeout (`NODE_TIMEOUT_DEFAULT = 120s`), `killpg`s the *entire process
  group* so any subprocess the patch spawned is reaped. A timed-out node is
  recorded as `FAILED` with a `[timeout]` note.
- **No stale bytecode.** Tests run with `python -B` /
  `PYTHONDONTWRITEBYTECODE=1` and `-p no:cacheprovider`. When a source file is
  patched in place and the edit preserves its byte size within the same
  wall-clock second, CPython's `(mtime, size)` `.pyc` cache would otherwise serve
  *stale* bytecode for the newly-patched file — a silent wrong grade. (The same
  class of bug is why `staged_diff_against_base` uses `git add --renormalize`.)

---

## 4. Credibility properties

A benchmark is only worth as much as its resistance to the standard objections:
contamination, weak tests, and a grader that disagrees with the reference. Each
is addressed as a *tested* property, not a footnote.

### 4.1 Decontamination

The golden set is **18 intrinsically-verifiable `make_ci_green` tasks**, all
`source_license: own`:

- **15 purpose-built post-cutoff fixtures**
  ([`forgejudge/golden/fixtures/`](../forgejudge/golden/fixtures/) —
  `semver`, `roman-numeral`, `lru-cache`, `rpn-eval`, `jsonpath`, `luhn`,
  `csv-parser`, `interval-merge`, `bitset`, `fraction`, `duration`,
  `base-convert`, `window-stats`, `rate-limiter`, `retry-decorator`).
- **3 tasks mined from the author's own repositories**
  ([`golden/owned/`](../golden/owned/)): `owned-handson-metrics`,
  `owned-handbook-clean-text`, `owned-raschka-tokenizer` — real commit SHAs,
  own license, so there is **no third-party leak, GPL, or attribution surface**.

Decontamination is enforced at build time, not asserted in prose. In
[`forgejudge/golden/build_dataset.py`](../forgejudge/golden/build_dataset.py),
`_validate_meta` rejects any task whose `created_at` is on or before
`MODEL_CUTOFF = 2026-01-31`. Each fixture is three plain directory states
(`base/` buggy source + passing tests, `test/` the failing test, `fix/` the gold
solution); the `test_patch` and `gold_patch` are *derived with git* (authors
never hand-write diffs), and `validate_task` proves the invariants by actually
running pytest: the failing test must FAIL on the buggy base, the existing tests
must PASS on base, and the gold fix must turn everything green and break nothing.

Problem statements are symptom-only (they describe the observable bug, never the
fix), and by default the agent solves against a **hidden oracle** ([§3.3](#33-the-repair-step-edit-gate--critic-pre-filter)).

This is a direct response to the SWE-bench Verified contamination findings —
OpenAI [stopped reporting it](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/)
(Feb 2026); independent work found >32% of "passed" cases leaked the solution and
~31% passed on weak tests. ForgeJudge treats both failure modes as things to
*test against*, which leads to the next property.

### 4.2 Mutation hardening

File: [`forgejudge/golden/harden.py`](../forgejudge/golden/harden.py).

Intrinsic verifiability proves the failing test *executes* the patched region (it
could not distinguish buggy from fixed otherwise). Mutation hardening goes
further and proves the tests **constrain behaviour** — that a *wrong* fix to the
patched region gets caught.

How it works: for each task, generate single-point AST mutants of the gold-fixed
source (swap comparison/arithmetic/boolean operators, flip booleans, perturb int
constants — `_CMP`/`_BIN`/`_BOOL` tables), splice each mutant into an
otherwise-correct materialized tree, and run the task's full `FAIL_TO_PASS +
PASS_TO_PASS` suite. A mutant is **killed** if any test fails; a *survivor* is a
mutant the suite let through — a weak test.

Two refinements make the score meaningful:

- **Mutation is scoped to the lines the gold patch changed**
  (`changed_line_numbers` via `difflib`), so a large surrounding module does not
  dilute the score; what is probed is a wrong fix *at the patch site*. A
  pure-deletion fix (no added lines) falls back to whole-file mutation rather
  than silently probing nothing (finding #5).
- A node is scoped by its **full line span** (`lineno..end_lineno`), so a
  multi-line expression whose operator sits on a continuation line is still
  mutated (finding #21).

The status taxonomy (`HardenResult.status`) is honest about what mutation can and
cannot say:

- **`hardened`** — mutation score ≥ threshold (0.5); the tests killed the
  mutants.
- **`inconclusive`** — the AST mutator produced *no applicable mutants* (e.g.
  pure string/regex code with no arithmetic/comparison/boolean nodes). This is
  **not** weak: intrinsic verifiability already proves the oracle executes the
  patched region; mutation is simply uninformative for that code shape.
- **`weak`** — mutants survived above the threshold. This is the failure mode
  that gets a task rejected.

Current golden set: **16 mutation-hardened (mean score 0.94), 2 inconclusive
(regex/string code with no mutable operators), 0 weak** — the same figures shown
on the public [methodology page](https://forgejudge.ahmedhobeishy.tech/methodology),
reproducible via `uv run python -m forgejudge.golden.harden`.

### 4.3 SWE-bench equivalence — and where it is deliberately stricter

Files: [`forgejudge/harness/swebench_grade.py`](../forgejudge/harness/swebench_grade.py),
test [`tests/harness/test_swebench_grade.py`](../tests/harness/test_swebench_grade.py).

ForgeJudge encodes the SWE-bench resolution rule directly (so the core scorer
carries no heavy runtime dependency), and then **proves that encoding correct by
cross-checking it against the official `swebench.harness.grading` in CI on every
commit.** The CI job (`swebench-equivalence` in `.github/workflows/ci.yml`)
installs the optional `forgejudge[harness]` extra, hard-imports `swebench` so a
failed install is a loud failure rather than a silently-skipped test, and runs
`pytest -m swebench`. The equivalence test drives `is_resolved_by_swebench` from
the harness's **real per-node junit statuses** (gold patch → resolved, empty
patch → not, a `PASS_TO_PASS`-breaking patch → not), so it is a genuine
cross-check, not a re-grade of ForgeJudge's own heuristic.

**The nuance worth featuring — and the one place ForgeJudge intentionally
diverges:**

ForgeJudge is verified *equivalent* to swebench on real `PASS/FAIL/ERROR/XFAIL`
outcomes, **and deliberately *stricter* on a SKIPPED `FAIL_TO_PASS`.**

Empirically (swebench 4.1.0), a `SKIPPED` test is neither a `success` nor a
`failure` inside `get_eval_tests_report`. With an empty failure list the run is
rated `RESOLVED_FULL`. So a candidate that makes the oracle `FAIL_TO_PASS` tests
*skip* (rather than run and pass) is graded **RESOLVED by the official swebench
grading** — a silent cheat vector.

ForgeJudge closes that gap. A node passes **only** when pytest reports
`PASSED`/`XFAIL` (`_PASSING_STATUSES`), so a skipped `FAIL_TO_PASS` is not-passed
and the task is *unresolved*. This divergence is pinned from both sides by a CI
test against real swebench
(`test_forgejudge_is_stricter_than_swebench_on_skipped_f2p`):

```python
# Official swebench rates a skipped f2p RESOLVED_FULL...
assert is_resolved_by_swebench(task, status_map) is True
# ...ForgeJudge treats the skip as a miss → unresolved.
fj_f2p_passed = all(status_map[n] in _PASSING_STATUSES for n in task.fail_to_pass)
assert fj_f2p_passed is False
```

So the claim is precise: **equivalent on real test outcomes, stricter on a
skip-to-resolve cheat, and both halves are pinned in CI so neither can drift.**

---

## 5. The multi-seed regression gate

File: [`forgejudge/eval/gate.py`](../forgejudge/eval/gate.py), workflows
`.github/workflows/gate.yml` (exact) and `sweep.yml` (stochastic).

There are **two distinct gates**, because there are two different variance axes,
and conflating them produces either a flaky build or a false sense of safety.

**Why `temperature=0` is not enough.** Even at `temperature=0`, LLM inference is
not bitwise deterministic (batching, kernel non-associativity, provider routing),
so pass@1 wanders a few points run to run — visible directly in the
`pass@3 > pass@1` gap in [§1](#1-thesis). A gate that compares two single runs
would fail honest noise.

### Gate 1 — stochastic multi-seed regression gate (`regression_gate`)

For a model swap or scaffold change, ForgeJudge runs **each side over several
seeds** (genuine independent reruns of the *same* task set — never partitions of
one run), turns the per-seed resolution rates into a **small-sample confidence
interval**, and **fails only when the candidate's CI upper bound sits strictly
below the baseline's CI lower bound** — i.e. even being generous to the candidate
and harsh to the baseline, the candidate still loses. Equal, overlapping,
flaky-but-overlapping, or improved distributions all pass.

The interval is `mean ± t · (sample_stdev / √n)` using a **Student-t** critical
value for `n-1` degrees of freedom (`mean_ci`, with a small vendored `_T_975`
table for the realistic `n = 2..11` seed counts and a normal `z = 1.96` fallback
for large `n`). Student-t — not the normal `z` — is the statistically correct
multiplier for a small-sample CI of a mean; using `z` would make the interval too
narrow and the gate over-eager to fail ordinary seed noise. (The same conjugate
small-sample / Wilson-style reasoning underpins the project's interval treatment
of a bounded resolution rate.)

A side with a single seed has no variance estimate, so the gate **refuses** it
(`ValueError`) rather than acting on a meaningless point estimate — both the
committed baseline ([`eval/baseline_scores.json`](../eval/baseline_scores.json),
currently `[0.9444, 0.8889, 0.8333]`, a real ≥3-seed sample) and the candidate
must carry ≥2 seeds. The whole gate is pure standard library — no scipy, no numpy.

### Gate 2 — deterministic gold-integrity gate (`exact_gold_gate`)

Grading the gold patches is `$0` and **deterministic**, so the per-shard rates
are a *partition of one run*, not noisy seeds — a confidence interval over them
would be statistically meaningless. This gate instead **pools every shard record
into one overall resolution rate and requires it to be exactly `1.0`** (every
gold task must resolve). Any partial breakage — even one gold task — fails, and
empty artifacts fail too.

This separation is the point: the **stochastic** gate guards "did the agent get
worse?" with a noise-aware CI rule; the **deterministic** gate guards "did
someone break patch application / the grader?" with zero tolerance. They run on
different events (`gate.yml` re-grades gold on every PR; the multi-seed
`regression_gate` is reserved for the scheduled sweep), and keeping them separate
means a flaky agent run never masks a real harness regression, and a real harness
regression is never excused as noise.

The gold-integrity invariant is enforced in more than one place: the sandbox
grade executor itself (`runner_actions.py`) exits non-zero if a `--patch-source
gold` run leaves any task unresolved (finding #36), and `eval.yml` uses
`set -o pipefail` so that failure propagates through `tee` and reds the job.

---

## 6. Observability

File: [`forgejudge/obs/tracing.py`](../forgejudge/obs/tracing.py).

Every agent run emits **OpenTelemetry GenAI spans** following the GenAI semantic
conventions, wired into the solve loop in `solver.py`:

- An `invoke_agent` root span carries `gen_ai.conversation.id` (the `run_id`),
  the task id, and the seed.
- Child spans mark each phase: `retrieval` (localization), `chat` (each model
  call, including the critic), and `execute_tool` (the pytest run, tagged
  `gen_ai.tool.name = pytest`).
- Model spans carry `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens` (`set_model_usage`). Per-call USD cost is recorded
  under the **vendor-namespaced** `forgejudge.usage.cost_usd` — deliberately
  *not* `gen_ai.usage.cost`, because cost is not part of the OTel GenAI
  convention and the code refuses to squat on the `gen_ai.*` namespace. Cost is
  only set when actually known (a literal `0.0` from a free model is omitted, so
  it can't skew cost dashboards).
- The final verdict is attached as a `gen_ai.evaluation.result` event
  (`record_evaluation`) carrying the pass/fail label and an explanation.

Spans are exported to **Langfuse Cloud** over OTLP/HTTP (with an optional
self-hosted Phoenix collector for bulk), using a `BatchSpanProcessor` so a slow
endpoint never stalls the agent hot path. Each run's `trace_url` is a best-effort
Langfuse deep link (`trace_url_for`) — and notably it returns `""` when Langfuse
export is *not* configured, so the public leaderboard never advertises a dead
`404` link to a trace that was never sent. The result: **every run on the
leaderboard is a clickable, public trace.**

---

## 7. The $0 / self-hostable stack

ForgeJudge runs end-to-end on free tiers, and every paid component has a
self-hostable substitute:

| Layer | Service | Cost | Notes |
|---|---|---|---|
| Models | Groq (`gpt-oss-120b`, `llama-3.3-70b`, `llama-3.1-8b`) + Gemini Flash, all behind **LiteLLM** | free tier | role→fallback chains in `models.yaml`; swap any model id |
| Sandbox + CI + cron | **GitHub Actions** on a public repo | free | the ephemeral isolated VM *is* the sandbox boundary; `ci`/`gate`/`eval`/`sweep` workflows |
| Dashboard | **Cloudflare Pages** (static) | free | renders from exported JSON snapshots, always-on even when live quotas are spent |
| Run store | **Neon** (Postgres + `pgvector`) | free tier | `migrations/001_init.sql`; canonical golden set stays in Git, DB holds runs |
| Tracing | **Langfuse Cloud** (Phoenix optional self-host) | free tier | OTLP/HTTP export |
| Distribution | **MCP server** published to the official registry | free | `forgejudge/mcp/server.py`, OIDC-published `server.json` |

The single most leveraged insight: **GitHub Actions does triple duty** —
ephemeral isolated VM sandbox, regression gate, *and* scheduled sweep — so the
benchmark needs no dedicated execution infrastructure. The static-snapshot
dashboard (`store/export.py` → `dashboard/public/data/*.json`) keeps the public
site `$0` and always-on: it renders historical runs and their traces even when
live API quotas are exhausted.

The MCP server (`forgejudge/mcp/server.py`, FastMCP over stdio) exposes the agent
and leaderboard as tools (`get_leaderboard`, `get_run`, `solve_issue`) with the
logic in unit-testable `_impl` functions; it is published to the registry via
GitHub OIDC, with the publisher binary checksum-verified before a sudo-install in
the token-minting job (finding #16).

---

## 8. Engineering quality

This is not a prototype that happens to run once. It went through a deliberate
**audit → fix → coverage → golden-set-expansion** hardening pass, and the
fingerprints are visible in the code: dozens of fixes are annotated inline with
their finding number (e.g. `#5`, `#7`, `#21`, `#35`, `#36`) — the stale-`.pyc`
grading bug, the skip-as-pass cheat, the SCP/SSH remote-URL mis-parse, the
shared-file revert, the silent gold-self-test pass, and more.

- **~300 tests** (282 test functions across `tests/`, spanning agent, harness,
  golden, llm, eval, store, obs, mcp, ci, and playground suites).
- **~93% line coverage on the non-DB / non-swebench surface** (the heavy
  swebench-equivalence and Postgres paths are covered by their own dedicated CI
  jobs rather than the line-coverage run).
- **Tests are partitioned by marker** so CI can fan them out and a missing
  optional extra fails *loudly* instead of skipping green: `slow` (end-to-end
  golden validation + mutation), `swebench`, `db`, `mcp`, `playground`. The fast
  unit suite is `pytest -m "not slow"`.
- **Determinism is built into the test infrastructure**, not bolted on: backoff
  sleeps are stubbable (`_sleep`), the tracer accepts an in-memory exporter, and
  every grading path runs in isolated temp trees so no test can be poisoned by
  another's bytecode cache.

Verification harness, not vibes: the **gold self-test resolves 18/18** every time
the harness runs (`uv run python -m forgejudge.harness.runner_actions
--patch-source gold` → 18/18; the runner exits non-zero on any miss), which is
the canary that catches a broken grader before it can mislabel an agent run.

---

## 9. Key design decisions, trade-offs, and limitations

**Decisions (and why):**

- **Single phase-structured loop, not multi-agent / not LangChain.** Cheapest,
  most deterministic, most debuggable, and it makes the *harness* — not framework
  glue — the thing being demonstrated. The role chains in `models.yaml` give the
  flexibility of multiple models without the nondeterminism of concurrent agents.
- **Deterministic execution-as-judge as the primary gate; LLM-as-judge strictly
  secondary.** Pass/fail is always a test transition. The LLM judge
  (`forgejudge/eval/judge.py`) produces only an advisory 1–5 quality score, and
  even that is *calibrated* against human labels with **Cohen's κ**
  (`cohen_kappa`, `golden/judge_gold.jsonl`) so its trustworthiness is itself
  measured. `PRIMARY_GATE = "test_execution"` is asserted in code.
- **Two separate gates for two variance axes** (§5) — the single most important
  statistical decision in the project.
- **Golden set in Git, runs in Neon.** Reproducibility and zero-infra cloning win
  over a single source of truth in the DB.

**Honest limitations:**

- **Small benchmark.** 18 tasks. It is enough to demonstrate the model-swap
  signal and the credibility properties, but it is not a broad capability
  benchmark. The architecture (fixture contract + miner + build/validate
  pipeline) is built to scale the set; the current size is a deliberate
  MVP scope, not a ceiling.
- **Self-authored / own-repo tasks.** The decontamination strategy (own-source
  only) trades third-party realism for zero leak/license risk. These are
  self-contained pure-Python utility bugs, not multi-file framework issues.
- **`make_ci_green` only.** The `raise_coverage` family is declared in the type
  system (`TaskFamily`) but not yet populated; every current task is a
  fix-the-bug task.
- **Localization is BM25-only.** No dense retrieval / rerank yet. The hook is
  designed (§3.1) but unimplemented, and BM25 can mis-rank on a large repo whose
  buggy file shares few lexical terms with the issue.
- **The judge calibration set is a partial seed** (8 rows, flagged as such in the
  data). κ is wired and tested, but the human-label set is small.
- **Free-tier dependence.** The headline numbers are free-model numbers and will
  move if providers change their free models; the model-swap framing is precisely
  what makes that acceptable — the *instrument* is the deliverable, and any model
  id can be dropped in behind it.

---

*Numbers in this document — 18 tasks, 162 runs, pass@1 90.7% / 88.9% / 48.1%,
mutation hardening 16 hardened (mean 0.94) / 2 inconclusive / 0 weak, gold
self-test 18/18 — are the live values from `golden/dataset.jsonl`,
`dashboard/public/data/leaderboard.json`, and the mutation/self-test runs as of
this writing.*
