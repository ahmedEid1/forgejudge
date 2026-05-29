"""Postgres/pgvector run store + leaderboard query.

Works against Neon (DATABASE_URL) in production or a local pgvector container in
dev/CI. The canonical golden set stays in Git; this DB holds run records.
"""

import os
from pathlib import Path

import psycopg

from forgejudge.types import GradeResult, RunRecord, Task

MIGRATION = Path(__file__).resolve().parent.parent.parent / "migrations" / "001_init.sql"


def dsn_from_env() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("FJ_LOCAL_DATABASE_URL")


def connect(dsn: str | None = None) -> psycopg.Connection:
    dsn = dsn or dsn_from_env()
    if not dsn:
        raise RuntimeError("no DATABASE_URL / FJ_LOCAL_DATABASE_URL set")
    return psycopg.connect(dsn, autocommit=False)


def init_db(conn: psycopg.Connection) -> None:
    conn.execute(MIGRATION.read_text())
    conn.commit()


def upsert_task(conn: psycopg.Connection, task: Task) -> None:
    conn.execute(
        """
        INSERT INTO tasks (instance_id, family, repo, source_license, language,
                           problem_statement, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (instance_id) DO UPDATE SET
            family=EXCLUDED.family, repo=EXCLUDED.repo,
            source_license=EXCLUDED.source_license, language=EXCLUDED.language,
            problem_statement=EXCLUDED.problem_statement, created_at=EXCLUDED.created_at
        """,
        (task.instance_id, task.family, task.repo, task.source_license, task.language,
         task.problem_statement, task.created_at),
    )
    conn.commit()


def upsert_tasks(conn: psycopg.Connection, tasks: list[Task]) -> None:
    for t in tasks:
        upsert_task(conn, t)


def insert_run(conn: psycopg.Connection, run: RunRecord) -> None:
    g = run.grade
    conn.execute(
        """
        INSERT INTO runs (run_id, task_id, model, scaffold_version, seed, resolved,
            f2p_passed, f2p_total, p2p_passed, p2p_total, grade_logs, patch,
            tokens_in, tokens_out, cost_usd, wall_clock_s, trace_url, judge_score,
            status, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (run_id) DO UPDATE SET
            task_id=EXCLUDED.task_id, model=EXCLUDED.model,
            scaffold_version=EXCLUDED.scaffold_version, seed=EXCLUDED.seed,
            resolved=EXCLUDED.resolved, f2p_passed=EXCLUDED.f2p_passed,
            f2p_total=EXCLUDED.f2p_total, p2p_passed=EXCLUDED.p2p_passed,
            p2p_total=EXCLUDED.p2p_total, grade_logs=EXCLUDED.grade_logs,
            patch=EXCLUDED.patch, tokens_in=EXCLUDED.tokens_in,
            tokens_out=EXCLUDED.tokens_out, cost_usd=EXCLUDED.cost_usd,
            wall_clock_s=EXCLUDED.wall_clock_s, trace_url=EXCLUDED.trace_url,
            judge_score=EXCLUDED.judge_score, status=EXCLUDED.status,
            created_at=EXCLUDED.created_at
        """,
        (run.run_id, run.task_id, run.model, run.scaffold_version, run.seed, run.resolved,
         g.f2p_passed, g.f2p_total, g.p2p_passed, g.p2p_total, g.logs, run.patch,
         run.tokens_in, run.tokens_out, run.cost_usd, run.wall_clock_s, run.trace_url,
         run.judge_score, run.status, run.created_at),
    )
    conn.commit()


def insert_runs(conn: psycopg.Connection, runs: list[RunRecord]) -> None:
    for r in runs:
        insert_run(conn, r)


def get_run(conn: psycopg.Connection, run_id: str) -> RunRecord | None:
    row = conn.execute(
        """SELECT run_id, task_id, model, scaffold_version, seed, resolved, f2p_passed,
                  f2p_total, p2p_passed, p2p_total, grade_logs, patch, tokens_in, tokens_out,
                  cost_usd, wall_clock_s, trace_url, judge_score, status, created_at
           FROM runs WHERE run_id=%s""",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    (rid, task_id, model, scaffold, seed, resolved, f2p_p, f2p_t, p2p_p, p2p_t, logs, patch,
     tin, tout, cost, wall, trace, judge, status, created) = row
    return RunRecord(
        run_id=rid, task_id=task_id, model=model, scaffold_version=scaffold, seed=seed,
        resolved=resolved,
        grade=GradeResult(f2p_passed=f2p_p, f2p_total=f2p_t, p2p_passed=p2p_p, p2p_total=p2p_t,
                          logs=logs),
        patch=patch, tokens_in=tin, tokens_out=tout, cost_usd=cost, wall_clock_s=wall,
        trace_url=trace, judge_score=judge, status=status, created_at=created,
    )


def leaderboard(conn: psycopg.Connection) -> list[dict]:
    """Aggregate per model over the FULL task universe.

    Returns, per (model, scaffold_version):

    * ``pass_at_1``  — expected single-sample resolve rate, averaged over every
      task in the universe (missing/skipped tasks count as 0), not just the runs
      that happened to execute (finding #38: denominator is the full golden set).
    * ``pass_at_k``  — fraction of universe tasks where *any* seed resolved.
      ``k`` varies with the number of seeds actually swept, so the metric is
      named generically (finding #39); ``n_seeds`` reports the real k so the UI
      can label it honestly (e.g. "pass@3" only when 3 seeds were run).
    * ``mean_cost_usd`` / ``mean_tokens`` / ``mean_wall_s`` — per-TASK, not
      per-run: cost/tokens/latency are summed within a task then averaged across
      the universe (finding #28: matches the dashboard's "$/task" labels).

    The universe is the set of all distinct ``task_id``s present in ``runs`` (the
    full golden set a complete sweep covers), so a model that skipped a task is
    penalised relative to one that completed it. Best pass@1 first.
    """
    rows = conn.execute(
        """
        WITH universe AS (
            -- the full task set a complete sweep covers
            SELECT DISTINCT task_id FROM runs
        ),
        models AS (
            SELECT DISTINCT model, scaffold_version FROM runs
        ),
        grid AS (
            -- every (model, scaffold) crossed with every task in the universe
            SELECT m.model, m.scaffold_version, u.task_id
            FROM models m CROSS JOIN universe u
        ),
        per_task AS (
            -- per-task rollup for the (model, task) pairs that actually ran
            SELECT model, scaffold_version, task_id,
                   bool_or(resolved) AS any_resolved,
                   AVG(resolved::int)::float AS task_pass_rate,
                   SUM(cost_usd)::float AS task_cost,
                   SUM(tokens_in + tokens_out)::float AS task_tokens,
                   SUM(wall_clock_s)::float AS task_wall
            FROM runs GROUP BY model, scaffold_version, task_id
        ),
        per_task_full AS (
            -- left-join the grid so missing tasks COALESCE to 0 (not resolved)
            SELECT g.model, g.scaffold_version, g.task_id,
                   COALESCE(p.any_resolved, false) AS any_resolved,
                   COALESCE(p.task_pass_rate, 0.0) AS task_pass_rate,
                   COALESCE(p.task_cost, 0.0) AS task_cost,
                   COALESCE(p.task_tokens, 0.0) AS task_tokens,
                   COALESCE(p.task_wall, 0.0) AS task_wall
            FROM grid g
            LEFT JOIN per_task p USING (model, scaffold_version, task_id)
        ),
        runagg AS (
            SELECT model, scaffold_version,
                   COUNT(*) AS n_runs,
                   COUNT(DISTINCT seed) AS n_seeds
            FROM runs GROUP BY model, scaffold_version
        ),
        taskagg AS (
            SELECT model, scaffold_version,
                   COUNT(*) AS n_tasks,
                   AVG(task_pass_rate)::float AS pass_at_1,
                   AVG(any_resolved::int)::float AS pass_at_k,
                   AVG(task_cost)::float AS mean_cost_usd,
                   AVG(task_tokens)::float AS mean_tokens,
                   AVG(task_wall)::float AS mean_wall_s
            FROM per_task_full GROUP BY model, scaffold_version
        )
        SELECT t.model, t.scaffold_version, t.n_tasks, r.n_runs, r.n_seeds,
               t.pass_at_1, t.pass_at_k, t.mean_cost_usd, t.mean_tokens, t.mean_wall_s
        FROM taskagg t JOIN runagg r USING (model, scaffold_version)
        ORDER BY t.pass_at_1 DESC, t.mean_cost_usd ASC
        """
    ).fetchall()
    cols = ["model", "scaffold_version", "n_tasks", "n_runs", "n_seeds", "pass_at_1",
            "pass_at_k", "mean_cost_usd", "mean_tokens", "mean_wall_s"]
    return [dict(zip(cols, r, strict=True)) for r in rows]
