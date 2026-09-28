# ForgeJudge — archive notes

**Status: archived on 2026-09-28.** Nothing runs on a schedule any more, nothing
deploys automatically, and the project is not maintained. The leaderboard is
frozen at the last sweep that completed end to end (2026-07-02). This page
records those final results, what no longer works and why, and everything a fork
needs to run the whole pipeline again.

Contents:

1. [Final results (frozen)](#1-final-results-frozen)
2. [What no longer works](#2-what-no-longer-works)
3. [Rerun it in a fork](#3-rerun-it-in-a-fork)
4. [Gotchas](#4-gotchas)

---

## 1. Final results (frozen)

**Source:** the nightly `sweep` workflow run
[#34](https://github.com/ahmedEid1/forgejudge/actions/runs/28573886970), which ran
the three models one after another on 2026-07-02 from 07:43 to 08:11 UTC.
It exported the snapshot at 08:12:38 UTC and committed it as `fe324f2`.
The files are
[`dashboard/public/data/leaderboard.json`](../dashboard/public/data/leaderboard.json)
and [`runs.json`](../dashboard/public/data/runs.json). They are the archive
record and are what the dashboard renders. The setup was hidden-test mode (the
agent never sees the failing test), 18 tasks × 3 seeds = 54 runs per model, 162
runs in total, scaffold `0.1.0`, on the Groq free tier ($0).

| Model | pass@1 | pass@3 | resolved runs | tasks solved (any seed) | status on 2026-09-28 |
|---|---|---|---|---|---|
| `groq/llama-3.3-70b-versatile` | **98.1%** | 100% | 53 / 54 | 18 / 18 | retired by Groq on 2026-08-16 |
| `groq/openai/gpt-oss-120b` | **94.4%** | 94.4% | 51 / 54 | 17 / 18 | available |
| `groq/llama-3.1-8b-instant` | **57.4%** | 72.2% | 31 / 54 | 13 / 18 | retired by Groq on 2026-08-16 |

- **pass@1** is the mean over tasks of each task's resolve rate across the seeds.
  **pass@3** is the fraction of tasks that any seed resolved. Both come from
  `leaderboard()` in [`forgejudge/store/db.py`](../forgejudge/store/db.py).
- It ran on Groq's free tier, so nothing was paid. Every run recorded
  `cost_usd` 0.00, including models LiteLLM has prices for, so treat the cost
  column as unmeasured rather than as a price. A run took about 10 s and about
  1.1–1.3k tokens.
- Run outcomes: 151 `ok`, 9 `error`, 2 `budget_exceeded`. All 9 errored runs are
  on two of the three `owned-*` tasks (`owned-handson-metrics` and
  `owned-raschka-tokenizer`). `owned-handson-metrics` was the hardest task: only
  `llama-3.3-70b` solved it (3/3), and the other two models errored on every seed
  of it. Every task was solved by at least one model. Eight tasks were solved on
  every seed by every model.
- **What the table shows.** With the harness fixed, the 8B model trails the
  70B/120B models by about 40 percentage points. That is the model-swap signal.
  pass@3 ≥ pass@1 everywhere. It is strictly greater for both Llama models, and
  equal for `gpt-oss-120b`, whose only misses are the three seeds of one task.
- **Reproducible grading.** `runs.json` stores the patch from every run. Grading
  is deterministic: re-grading all 162 patches against the golden set on
  2026-09-28 reproduced every stored verdict (162/162). See [§3.1](#31-local-reproduction-only-groq_api_key)
  for the command.

**Why nothing later is published.** The nightly sweep kept running until the
archive, but nothing after 2026-07-02 reached git or the live site. From
2026-07-04 the Cloudflare deploy token was rejected (`Invalid access token [code:
9109]`), and the snapshot commit only runs after a successful deploy. The
quality-gated publish still wrote each night's healthy models to the Neon run
store, which therefore holds later, mixed-date runs that were never published.
For reference, the log of run #80 on 2026-08-17, the last night all three
models still ran, printed resolution rates of 0.907 (`gpt-oss-120b`), 0.944
(`llama-3.3-70b`) and 0.537 (`llama-3.1-8b`), in line with the frozen numbers.
From run #81 on 2026-08-18 every call to the two Llama models failed.

Older copies of the README quoted 90.7% / 88.9% / 48.1%. Those numbers came from
the 2026-05-29 sweep, and the table above supersedes them.

The judge calibration
([`calibration.json`](../dashboard/public/data/calibration.json)) is a separate,
one-off artifact from 2026-05-30. It used `gemini-2.5-flash` on 8 labelled pairs
and got κ = 1.0. The planned ~200-example calibration set was never completed.

## 2. What no longer works

Provider status as of 2026-09-28. Model availability comes from the providers'
deprecation notices (as quoted in public issues) and LiteLLM's current model
registry. The two Groq retirements are also visible first-hand in this repo's
sweep logs.

| Thing | Status | What to use instead |
|---|---|---|
| `groq/llama-3.3-70b-versatile` | Retired by Groq for free and developer tiers on 2026-08-16 (announced 2026-06-17). This repo's calls still succeeded on 2026-08-17 and have failed since 2026-08-18. | `groq/openai/gpt-oss-120b` or `groq/qwen/qwen3.8-27b` |
| `groq/llama-3.1-8b-instant` | Retired on the same date. | `groq/openai/gpt-oss-20b` |
| `gemini/gemini-2.5-flash` (judge, primary) | Google restricted the 2.5 models to existing users in September 2026 (not verified from here). | A current Gemini Flash model in [`models.yaml`](../forgejudge/llm/models.yaml). The judge chain already falls back to `groq/openai/gpt-oss-120b`. |
| OpenRouter `qwen3-coder:free` (suggested in older copies of `.env.example`) | Free variant withdrawn in July 2026. Nothing in the code routes through OpenRouter. | Not needed. |
| The live dashboard (Cloudflare Pages) | Still serves the 2026-07-02 deploy, which predates this archive: the data is the frozen snapshot, but the pages have no archive banner and still say "always-on". The deploy token has been invalid since 2026-07-04, and deploys are manual now. | Maintainer, once: create a Cloudflare API token with *Cloudflare Pages: Edit*, update `CLOUDFLARE_API_TOKEN`, run *Actions → pages-deploy*, or take the site down. Everyone else: serve `dashboard/public` locally, or deploy your own copy (§3). |
| The hosted live playground (Hugging Face Space) | Not maintained. Nothing in this repository deploys or stops it. | Maintainer: pause or delete the Space and its `GROQ_API_KEY` secret. Everyone else: self-host `playground_api/` (Dockerfile included); the dashboard's replay playground needs no backend. |
| Langfuse trace links in `runs.json` | They point at the original Langfuse project. They probably need project access and are past the free plan's retention window, so expect them not to resolve. | Patches and verdicts are in `runs.json`. Re-grade them locally (§3.1). |
| `eval/baseline_scores.json` (regression-gate baseline) | Holds `llama-3.3-70b`'s per-seed rates from 2026-05-29 (`[0.9444, 0.8889, 0.8333]`), a retired model. | Regenerate it from your own sweep (§3.5). |
| PyPI `forgejudge==0.1.0` | Its `models.yaml` still lists the retired `llama-3.3-70b-versatile` as primary for plan/localize/critic and as the edit and judge fallback. `solve()` and the MCP `solve_issue` tool still work, because they only call the `edit` role, whose primary is `gpt-oss-120b`; a fallback to the retired model fails. | Install from git (`pip install git+https://github.com/<you>/forgejudge`) for the current chains. |

The current defaults already avoid every retired model: `gpt-oss-120b`,
`gpt-oss-20b` and `qwen3.8-27b` in
[`sweep.yml`](../.github/workflows/sweep.yml) and in
[`models.yaml`](../forgejudge/llm/models.yaml). A test fails if a retired id
comes back. Note that `gpt-oss-20b` and `qwen3.8-27b` were never actually swept
in this repository, so there are no results for them.

## 3. Rerun it in a fork

### 3.1 Local reproduction (only `GROQ_API_KEY`)

Prerequisites: [`uv`](https://docs.astral.sh/uv/) (it provisions Python 3.12)
and git. You need Node only for deploying and Docker only for a local database.

```bash
git clone https://github.com/<you>/forgejudge && cd forgejudge
uv sync

# No key, no network: the deterministic harness self-test (expects 18/18 resolved)
uv run python -m forgejudge.harness.runner_actions --patch-source gold
uv run ruff check && uv run pytest -m "not slow" -q

# Re-grade the frozen snapshot: all 162 stored verdicts reproduce (about 10 minutes)
uv run python - <<'PY'
import json
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.grade import grade
tasks = {t.instance_id: t for t in load_tasks("golden/dataset.jsonl")}
runs = json.load(open("dashboard/public/data/runs.json"))["runs"]
bad = [r["run_id"] for r in runs if grade(tasks[r["task_id"]], r["patch"]).resolved != r["resolved"]]
print(f"{len(runs) - len(bad)}/{len(runs)} verdicts reproduced", bad)
PY

# Sweep one model with no database (the CLIs do not read .env by themselves)
cp .env.example .env            # then fill in GROQ_API_KEY
uv run --env-file .env python -m forgejudge.eval.sweep \
  --model groq/openai/gpt-oss-120b --seeds 0,1,2 --no-store --out runs-0.jsonl

# Browse the dashboard (frozen snapshot) at http://localhost:8000/
python3 -m http.server 8000 --directory dashboard/public
```

For a publishable leaderboard you also need a Postgres database with the
`pgvector` extension. The schema migration runs `CREATE EXTENSION vector`, so
plain Postgres fails. A throwaway local database works like this:

```bash
docker run -d --name fj-pg -e POSTGRES_USER=forgejudge -e POSTGRES_PASSWORD=forgejudge \
  -e POSTGRES_DB=forgejudge -p 5433:5432 pgvector/pgvector:pg17
export FJ_LOCAL_DATABASE_URL=postgresql://forgejudge:forgejudge@localhost:5433/forgejudge
# quality-gated publish; --out keeps the frozen snapshot in dashboard/public/data untouched
uv run python -m forgejudge.eval.publish --runs 'runs-*.jsonl' --out ./snapshot-local
```

### 3.2 Secrets and variables

Set these under the fork's *Settings → Secrets and variables → Actions*.

| Name | Needed for | Required? |
|---|---|---|
| `GROQ_API_KEY` | Every agent call (all default models are Groq). Get a free key at console.groq.com. | **Yes** |
| `DATABASE_URL` | The quality-gated publish step, and the MCP `get_leaderboard`/`get_run` tools. Use Postgres with `pgvector` (Neon works). Publish creates the schema and fills the task table itself. | **Yes** (full pipeline) |
| `CLOUDFLARE_API_TOKEN` | Deploying the dashboard. The token needs the *Cloudflare Pages: Edit* permission. | **Yes** (to deploy) |
| `CLOUDFLARE_ACCOUNT_ID` | Deploying the dashboard. | **Yes** (to deploy) |
| `CLOUDFLARE_PAGES_PROJECT` (a repository **variable**, not a secret) | Your Pages project name. The workflows fall back to `forgejudge`. | Only if your project has another name |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Per-run traces. Set all three or none (see §4). | Optional |
| `GEMINI_API_KEY` | The LLM-as-judge primary (`python -m forgejudge.eval.calibrate`), or sweeping a `gemini/*` model. The judge falls back to Groq. | Optional |
| `OPENROUTER_API_KEY` | Only for sweeping an `openrouter/*` model id. | Optional |
| `PYPI_API_TOKEN` | `release.yml`. You must rename the package first, because the `forgejudge` name on PyPI is taken. | Optional |
| `GITHUB_TOKEN` | The sweep's snapshot commit-back. GitHub provides it automatically. Allow *Read and write* under *Settings → Actions → General → Workflow permissions*. | Automatic |

`MISTRAL_API_KEY`, `NPM_TOKEN` and `HF_TOKEN` appear in `.env.example`, but
nothing reads them.

### 3.3 One-time setup outside GitHub

- **Groq:** create an API key, and check which models are currently offered
  before sweeping.
- **Database:** create a Neon project, or any Postgres with `pgvector`, and put
  its connection string (`...?sslmode=require`) in `DATABASE_URL`. No manual
  setup is needed: every publish applies `migrations/001_init.sql` (`init_db()`)
  and upserts the 18 golden tasks, which the export reads for the task count and
  the problem statements.
- **Cloudflare Pages:** run `npx wrangler pages project create <name>
  --production-branch main`, set `CLOUDFLARE_PAGES_PROJECT=<name>`, and
  optionally attach a custom domain in the Cloudflare dashboard.
- **Langfuse (optional):** create a project and copy its API key pair. The
  project id in the trace links is looked up automatically.
- **GitHub:** forks start with Actions disabled. Enable them in the *Actions*
  tab.

### 3.4 Values to change in a fork

- **Site URL** `forgejudge.ahmedhobeishy.tech` appears in `README.md`,
  `docs/DESIGN.md`, `pyproject.toml` (Homepage), `forgejudge/cli.py`
  (`HOMEPAGE`, asserted in `tests/test_cli.py`), `forgejudge/mcp/server.json`,
  `dashboard/public/index.html` (canonical and Open Graph tags),
  `dashboard/public/sitemap.xml`, `dashboard/public/robots.txt`,
  `dashboard/og_card.html`, `playground_api/app.py` and
  `playground_api/README.md`.
- **Repository URL** `github.com/ahmedEid1/forgejudge` appears in the README,
  `CONTRIBUTING.md`, `SECURITY.md`, `pyproject.toml` (`[project.urls]`), the
  dashboard nav, footers and archive banners, `forgejudge/cli.py` (`REPO`,
  asserted in `tests/test_cli.py`), `forgejudge/mcp/server.json`,
  `playground_api/README.md`, and `playground_api/Dockerfile`, which clones it
  at build time.
- **Archive notices:** remove the `archive-banner` block from
  `dashboard/public/{index,playground,model-swap,methodology,calibration}.html`;
  in `dashboard/public/app.js`, change the `final snapshot … (archived; no
  further sweeps)` label and the `RETIRED` map; update the "Archived" meta
  description in `index.html`, the 8B-vs-70B/120B sentence in `model-swap.html`
  (meta description and lede), and the tagline and numbers in
  `dashboard/og_card.html`. Then re-render `dashboard/public/og.png` with
  `node dashboard/render_og.mjs` (it imports a global Playwright install).
- **Package and registry names:** the PyPI distribution `forgejudge`
  (`pyproject.toml`, `release.yml`, `cli.py`, `server.json`) and the MCP
  registry name `io.github.ahmedEid1/forgejudge` (`server.json`, plus the
  `mcp-name` comment at the top of the README).
- **Personal/legal pages:** `dashboard/public/impressum.html`,
  `dashboard/public/privacy.html` and `SECURITY.md` carry the original author's
  contact details. Replace them or remove them.

### 3.5 Run the pipeline

1. Go to *Actions → sweep → Run workflow*. The inputs are a comma-separated list
   of model ids and the seeds. With the defaults (three models × 18 tasks × 3
   seeds) it takes about 30 minutes. The workflow sweeps each model with
   `--no-store`, runs the quality-gated publish (which skips a model if more
   than 25% of its runs errored), rebuilds `dashboard/public/data`, deploys it to Pages, and
   commits the snapshot back to `main`.
2. To make it nightly again, add a `schedule:` trigger to
   `.github/workflows/sweep.yml` (see the comment at the top of that file) and
   delete `test_archived_no_workflow_runs_on_a_schedule` in
   `tests/ci/test_workflows.py`.
3. Regression gate: after sweeping your model, write its per-seed resolution
   rates to `eval/baseline_scores.json`, then run *Actions → regression-gate*.
4. To turn Dependabot back on, set `open-pull-requests-limit` back to 5 in
   `.github/dependabot.yml` and drop the matching archive test.

## 4. Gotchas

- **Publishing overwrites the frozen snapshot.** `publish` and `store.export`
  write to `dashboard/public/data` by default and rebuild it entirely from the
  database they connect to. Pass `--out <dir>` (or `publish --no-export`) to
  keep the archived files.
- **`--no-store` is not the default.** Without it, the sweep connects to the
  database first, and it fails if `DATABASE_URL`/`FJ_LOCAL_DATABASE_URL` is
  unset. `DATABASE_URL` takes precedence over `FJ_LOCAL_DATABASE_URL`.
- **`.env` is not loaded automatically.** Use `uv run --env-file .env ...` or
  export the variables.
- **Langfuse:** if the keys are set but the `LANGFUSE_HOST` secret is missing,
  the workflow passes an empty string rather than the default host, and trace
  export breaks. Set all three secrets together.
- **Security:** grading executes model-written code with the full process
  environment. Never run a local sweep in a shell that has production database
  or deploy credentials exported.
- **Publish exits non-zero when every model was gated out.** That stops the
  deploy and the commit-back. The sweep log prints the most common error cause
  per model, such as a retired model id or a missing key.
- **The bot's snapshot commit does not trigger other workflows.** Pushes made
  with `GITHUB_TOKEN` never do, which is why `sweep.yml` deploys by itself
  instead of relying on `pages-deploy.yml`.
