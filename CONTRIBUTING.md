# Contributing to ForgeJudge

Thanks for helping. ForgeJudge lives or dies on a credible eval, so the bar is:
**tests green, `ruff` clean, and any new golden task is validated + mutation-hardened.**

## Dev setup

Prereq: [`uv`](https://docs.astral.sh/uv/) and Python 3.12 (the pinned version lives in
[`.python-version`](./.python-version)).

```bash
git clone https://github.com/ahmedEid1/forgejudge && cd forgejudge
uv sync                       # base deps into .venv
cp .env.example .env          # only needed for solve/sweep/trace/db work
```

Optional extras are phase-scoped — install only what your change touches:

```bash
uv sync --extra harness       # swebench grading equivalence
uv sync --extra mcp           # the fastmcp MCP server
uv sync --extra playground    # the FastAPI live playground
```

A `Makefile` wraps the common loops: `make test-fast`, `make test`, `make lint`,
`make selftest`, `make build`, `make sweep MODEL=... SEEDS=0,1,2`.

## Lint

```bash
uv run ruff check             # what CI runs; must be clean
uv run ruff check --fix       # auto-fix the trivial ones
uv run ruff format            # formatter
```

Config is in [`ruff.toml`](./ruff.toml) (line-length 100; `E,F,I,UP,B,C4,SIM`). The
golden **subject** code under `forgejudge/golden/fixtures/` and `golden/owned/` is
deliberately excluded from lint — it is the agent's *input*, sometimes buggy by design.

## Tests & the marker map

Fast unit tests need no key, no network, no DB:

```bash
uv run pytest -m "not slow"   # the default dev loop
```

Markers gate the slow / environment-dependent suites (defined in `pyproject.toml`):

| Marker | What it needs | Run it |
|---|---|---|
| `slow` | nothing extra (spawns many pytest subprocesses) | `uv run pytest -m "slow and not swebench"` |
| `swebench` | the `harness` extra (`uv sync --extra harness`) | `uv run pytest -m swebench` |
| `db` | a **local** pgvector at `FJ_LOCAL_DATABASE_URL` | `uv run pytest -m db` |
| `mcp` | the `mcp` extra (`uv sync --extra mcp`) | `uv run pytest -m mcp` |
| `playground` | the `playground` extra (`uv sync --extra playground`) | `uv run pytest -m playground` |

Notes:

- `slow` includes the full golden-set validation **and** mutation hardening — it runs
  pytest per task, so it is minutes, not seconds.
- The `swebench`, `mcp`, and `playground` suites `importorskip` their extra: without
  the extra installed they are *skipped*, so always install the extra before claiming
  the suite passed (CI hard-imports the extra to fail loud instead of skipping green).
- `db` tests **TRUNCATE**, so they read **only** `FJ_LOCAL_DATABASE_URL` and refuse any
  non-loopback host. Never point that var at the production Neon leaderboard DB. Spin up
  a disposable one:
  ```bash
  docker run -d --name fj-pg -e POSTGRES_USER=forgejudge -e POSTGRES_PASSWORD=forgejudge \
    -e POSTGRES_DB=forgejudge -p 5433:5432 pgvector/pgvector:pg17
  ```

The deterministic harness self-test (graded gold patches, no key, no network) is the
quickest signal the harness still works:

```bash
forgejudge selftest                                         # or:
uv run python -m forgejudge.harness.runner_actions --patch-source gold   # 18/18 resolved
```

## Adding a golden task

A task is a directory following the **fixture contract** under
`forgejudge/golden/fixtures/<name>/` (post-cutoff authored fixtures) or
`golden/owned/<name>/` (mined from your own repos). Each holds three tree states plus
metadata:

```
forgejudge/golden/fixtures/<name>/
  base/      # buggy source + its passing baseline tests (PASS_TO_PASS)
  test/      # the NEW failing test(s) that encode the bug — FAIL_TO_PASS
  fix/       # the corrected source (the reference gold patch)
  meta.yaml  # instance_id, family, problem_statement, fail_to_pass, pass_to_pass, created_at
```

`meta.yaml` requires these keys (read without defaults): `instance_id`, `family`,
`problem_statement`, `fail_to_pass`, `pass_to_pass`, `created_at`. `created_at` **must**
postdate the model cutoff (2026-01-31) or the build rejects it as contamination-prone.
See `forgejudge/golden/fixtures/semver-001/` for a worked example.

Then validate and harden:

```bash
# Builds golden/dataset.jsonl + solutions.jsonl by diffing base→test (test_patch) and
# base→fix (gold_patch); FAILS unless each new test FAILS on base and PASSES on fix,
# with PASS_TO_PASS staying green:
uv run python -m forgejudge.golden.build_dataset

# Mutation hardening — proves the tests would catch a *wrong* fix (a high kill rate);
# surviving mutants mean the tests are too weak:
uv run python -m forgejudge.golden.harden
```

`harden_check()` (`forgejudge/golden/harden.py`) is the per-task contract the slow suite
enforces; a task that can't kill its mutants is `weak` and should not land.

## PR expectations

Before opening a PR, confirm locally:

- [ ] `uv run ruff check` is clean.
- [ ] `uv run pytest -m "not slow"` passes; if you touched grading, the solver, or a
      golden task, also run `uv run pytest -m "slow and not swebench"`.
- [ ] New golden tasks are built (`build_dataset`) and hardened (`harden`) — commit the
      regenerated `golden/dataset.jsonl` / `golden/solutions.jsonl`.
- [ ] Behaviour changes are covered by a test; the change is noted in
      [`CHANGELOG.md`](./CHANGELOG.md) under `Unreleased`.

CI re-runs ruff, the fast suite, the slow golden validation, and (in matrixed jobs) the
swebench / db / mcp / playground suites. Keep PRs focused; describe *why*, not just *what*.

See also [`SECURITY.md`](./SECURITY.md) — this project executes untrusted, model-authored
code in a sandbox, so report vulnerabilities privately rather than in a public issue.
