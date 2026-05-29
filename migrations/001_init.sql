-- ForgeJudge run store (Postgres + pgvector). Canonical golden set lives in Git;
-- this DB holds run records + task metadata for the leaderboard.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS tasks (
    instance_id        text PRIMARY KEY,
    family             text NOT NULL,
    repo               text NOT NULL,
    source_license     text NOT NULL,
    language           text NOT NULL DEFAULT 'python',
    problem_statement  text NOT NULL DEFAULT '',
    created_at         text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS runs (
    run_id           text PRIMARY KEY,
    task_id          text NOT NULL,
    model            text NOT NULL,
    scaffold_version text NOT NULL,
    seed             integer NOT NULL,
    resolved         boolean NOT NULL,
    f2p_passed       integer NOT NULL DEFAULT 0,
    f2p_total        integer NOT NULL DEFAULT 0,
    p2p_passed       integer NOT NULL DEFAULT 0,
    p2p_total        integer NOT NULL DEFAULT 0,
    grade_logs       text NOT NULL DEFAULT '',
    patch            text NOT NULL DEFAULT '',
    tokens_in        integer NOT NULL DEFAULT 0,
    tokens_out       integer NOT NULL DEFAULT 0,
    cost_usd         double precision NOT NULL DEFAULT 0,
    wall_clock_s     double precision NOT NULL DEFAULT 0,
    trace_url        text NOT NULL DEFAULT '',
    judge_score      double precision,
    status           text NOT NULL DEFAULT 'ok',
    created_at       text NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_model ON runs (model);
CREATE INDEX IF NOT EXISTS idx_runs_task ON runs (task_id);
