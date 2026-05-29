"""Hermetic unit tests for forgejudge.store.db.

These tests exercise the PURE-PYTHON logic of the run store WITHOUT touching a
real database: no sockets, no psycopg.connect to a live server. We inject a fake
connection/cursor whose ``execute`` records the SQL+params and returns canned
rows, so we can verify:

* DSN selection precedence (DATABASE_URL vs FJ_LOCAL_DATABASE_URL),
* connect() error handling and that it forwards the resolved DSN to psycopg,
* the param tuples bound by upsert_task / insert_run (the row->columns mapping),
* the row->RunRecord reconstruction in get_run (incl. the None branch),
* the row->dict zip mapping returned by leaderboard().

The db-MARKED integration tests in tests/store/test_db.py cover the SQL itself
against a real pgvector container; this file deliberately marks NOTHING as db.
"""

import forgejudge.store.db as db
from forgejudge.store.db import (
    connect,
    dsn_from_env,
    get_run,
    init_db,
    insert_run,
    insert_runs,
    leaderboard,
    upsert_task,
    upsert_tasks,
)
from forgejudge.types import GradeResult, RunRecord, Task

# ---------------------------------------------------------------------------
# Fakes: a connection whose .execute records calls and hands back canned rows.
# ---------------------------------------------------------------------------


class FakeResult:
    """Mimics the cursor psycopg's Connection.execute() returns."""

    def __init__(self, fetchone=None, fetchall=None):
        self._fetchone = fetchone
        self._fetchall = fetchall if fetchall is not None else []

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class FakeConn:
    """Records every execute()/commit() and returns scripted results in order."""

    def __init__(self, results=None):
        self.executed = []  # list of (sql, params)
        self.commits = 0
        # results: an iterable of FakeResult handed out one per execute() call
        self._results = list(results) if results is not None else []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self._results:
            return self._results.pop(0)
        return FakeResult()

    def commit(self):
        self.commits += 1


def _task(**over):
    base = {
        "instance_id": "t1",
        "family": "make_ci_green",
        "repo": "fixture:t1",
        "base_commit": "",
        "problem_statement": "fix it",
        "test_patch": "--- a\n+++ b\n",
        "fail_to_pass": ["a::x"],
        "pass_to_pass": ["a::y"],
        "env_image": "img:1",
        "source_license": "own",
        "created_at": "2026-05-29",
    }
    base.update(over)
    return Task(**base)


def _run(run_id="r1", task_id="t1", model="groq/llama", seed=0, resolved=True,
         cost=0.25, tokens_in=200, tokens_out=100):
    g = GradeResult(
        f2p_passed=1 if resolved else 0, f2p_total=1,
        p2p_passed=1, p2p_total=1, logs="grade-log",
    )
    return RunRecord(
        run_id=run_id, task_id=task_id, model=model, scaffold_version="0.1.0",
        seed=seed, resolved=resolved, grade=g, patch="--- a\n+++ b\n",
        tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost, wall_clock_s=1.5,
        trace_url=f"https://lf/{run_id}", judge_score=0.9, status="ok",
        created_at="2026-05-29T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# dsn_from_env: precedence of DATABASE_URL over FJ_LOCAL_DATABASE_URL.
# ---------------------------------------------------------------------------


def test_dsn_from_env_prefers_database_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://prod/db")
    monkeypatch.setenv("FJ_LOCAL_DATABASE_URL", "postgresql://localhost/local")
    assert dsn_from_env() == "postgresql://prod/db"


def test_dsn_from_env_falls_back_to_local(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FJ_LOCAL_DATABASE_URL", "postgresql://localhost/local")
    assert dsn_from_env() == "postgresql://localhost/local"


def test_dsn_from_env_none_when_neither_set(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FJ_LOCAL_DATABASE_URL", raising=False)
    assert dsn_from_env() is None


# ---------------------------------------------------------------------------
# connect: error path, env resolution, explicit dsn — all without a socket.
# ---------------------------------------------------------------------------


def test_connect_raises_when_no_dsn(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FJ_LOCAL_DATABASE_URL", raising=False)
    # psycopg.connect must NOT be called; guard it to prove the early raise.
    monkeypatch.setattr(
        db.psycopg, "connect",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not connect")),
    )
    try:
        connect()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "DATABASE_URL" in str(exc)


def test_connect_uses_explicit_dsn_and_autocommit_false(monkeypatch):
    captured = {}

    def fake_connect(dsn, autocommit=None):
        captured["dsn"] = dsn
        captured["autocommit"] = autocommit
        return "FAKE_CONN"

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    out = connect("postgresql://localhost:5433/forgejudge")
    assert out == "FAKE_CONN"
    assert captured["dsn"] == "postgresql://localhost:5433/forgejudge"
    assert captured["autocommit"] is False


def test_connect_resolves_dsn_from_env(monkeypatch):
    captured = {}
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("FJ_LOCAL_DATABASE_URL", "postgresql://localhost/fromenv")

    def fake_connect(dsn, autocommit=None):
        captured["dsn"] = dsn
        return "C"

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    assert connect() == "C"
    assert captured["dsn"] == "postgresql://localhost/fromenv"


# ---------------------------------------------------------------------------
# init_db: reads the migration file and commits.
# ---------------------------------------------------------------------------


def test_init_db_executes_migration_and_commits(monkeypatch):
    monkeypatch.setattr(db, "MIGRATION", _FakeMigration("CREATE TABLE runs(...);"))
    conn = FakeConn()
    init_db(conn)
    assert conn.executed[0][0] == "CREATE TABLE runs(...);"
    assert conn.commits == 1


class _FakeMigration:
    """Stand-in for the Path object so init_db reads canned SQL, not the file."""

    def __init__(self, text):
        self._text = text

    def read_text(self):
        return self._text


# ---------------------------------------------------------------------------
# upsert_task / upsert_tasks: param tuple mapping + commit-per-task.
# ---------------------------------------------------------------------------


def test_upsert_task_binds_columns_in_order_and_commits():
    conn = FakeConn()
    t = _task(instance_id="abc", family="make_ci_green", repo="fixture:abc",
              language="python", source_license="MIT", problem_statement="ps",
              created_at="2026-01-01")
    upsert_task(conn, t)
    sql, params = conn.executed[0]
    assert "INSERT INTO tasks" in sql
    assert "ON CONFLICT (instance_id) DO UPDATE" in sql
    # The exact bind order the schema expects.
    assert params == (
        "abc", "make_ci_green", "fixture:abc", "MIT", "python", "ps", "2026-01-01",
    )
    assert conn.commits == 1


def test_upsert_tasks_inserts_each_task():
    conn = FakeConn()
    upsert_tasks(conn, [_task(instance_id="a"), _task(instance_id="b")])
    ids = [params[0] for _, params in conn.executed]
    assert ids == ["a", "b"]
    assert conn.commits == 2  # one commit per task


# ---------------------------------------------------------------------------
# insert_run / insert_runs: the grade is unpacked + the 20-col bind order.
# ---------------------------------------------------------------------------


def test_insert_run_binds_grade_fields_and_run_fields():
    conn = FakeConn()
    run = _run(run_id="r9", task_id="t9", model="m", seed=3, resolved=True,
               cost=1.5, tokens_in=10, tokens_out=4)
    insert_run(conn, run)
    sql, params = conn.executed[0]
    assert "INSERT INTO runs" in sql
    assert "ON CONFLICT (run_id) DO UPDATE" in sql
    # 20 bind params, matching the 20 %s placeholders in the VALUES clause.
    assert len(params) == 20
    # leading run identity columns
    assert params[0] == "r9"
    assert params[1] == "t9"
    assert params[2] == "m"
    assert params[4] == 3       # seed
    assert params[5] is True    # resolved
    # grade fields are pulled off run.grade (f2p_passed, f2p_total, p2p_*, logs)
    assert params[6] == run.grade.f2p_passed
    assert params[7] == run.grade.f2p_total
    assert params[8] == run.grade.p2p_passed
    assert params[9] == run.grade.p2p_total
    assert params[10] == "grade-log"
    # cost/tokens
    assert params[12] == 10     # tokens_in
    assert params[13] == 4      # tokens_out
    assert params[14] == 1.5    # cost_usd
    assert params[17] == 0.9    # judge_score
    assert params[18] == "ok"   # status
    assert conn.commits == 1


def test_insert_runs_inserts_each_run():
    conn = FakeConn()
    insert_runs(conn, [_run(run_id="x"), _run(run_id="y")])
    rids = [params[0] for _, params in conn.executed]
    assert rids == ["x", "y"]
    assert conn.commits == 2


# ---------------------------------------------------------------------------
# get_run: None branch + full row->RunRecord reconstruction.
# ---------------------------------------------------------------------------


def test_get_run_returns_none_when_missing():
    conn = FakeConn(results=[FakeResult(fetchone=None)])
    assert get_run(conn, "nope") is None
    # it still queried with the run_id bound.
    sql, params = conn.executed[0]
    assert "FROM runs WHERE run_id=%s" in sql
    assert params == ("nope",)


def test_get_run_maps_row_to_runrecord():
    # 20-tuple in the SELECT column order get_run unpacks.
    row = (
        "r1", "t1", "groq/llama", "0.1.0", 0, True,   # rid..resolved
        1, 1, 1, 1, "logtext",                        # f2p_p,f2p_t,p2p_p,p2p_t,logs
        "--- patch ---",                              # patch
        200, 100, 0.25, 1.5,                          # tin,tout,cost,wall
        "https://lf/r1", 0.9, "ok", "2026-05-29T00:00:00Z",  # trace,judge,status,created
    )
    conn = FakeConn(results=[FakeResult(fetchone=row)])
    rec = get_run(conn, "r1")
    assert isinstance(rec, RunRecord)
    assert rec.run_id == "r1"
    assert rec.task_id == "t1"
    assert rec.model == "groq/llama"
    assert rec.scaffold_version == "0.1.0"
    assert rec.seed == 0
    assert rec.resolved is True
    assert rec.grade.f2p_passed == 1 and rec.grade.p2p_total == 1
    assert rec.grade.logs == "logtext"
    assert rec.patch == "--- patch ---"
    assert rec.tokens_in == 200 and rec.tokens_out == 100
    assert rec.cost_usd == 0.25 and rec.wall_clock_s == 1.5
    assert rec.trace_url == "https://lf/r1"
    assert rec.judge_score == 0.9
    assert rec.status == "ok"
    assert rec.created_at == "2026-05-29T00:00:00Z"


# ---------------------------------------------------------------------------
# leaderboard: row->dict zip mapping (the SQL math is covered by the db tests).
# ---------------------------------------------------------------------------


def test_leaderboard_maps_rows_to_named_dicts():
    # Two canned rows in the SELECT column order; leaderboard() zips them to keys.
    rows = [
        ("B", "0.1.0", 2, 4, 2, 0.75, 1.0, 0.5, 300.0, 3.0),
        ("A", "0.1.0", 2, 4, 2, 0.50, 0.5, 0.0, 300.0, 3.0),
    ]
    conn = FakeConn(results=[FakeResult(fetchall=rows)])
    out = leaderboard(conn)
    assert [r["model"] for r in out] == ["B", "A"]  # preserves DB ordering
    b = out[0]
    assert b == {
        "model": "B",
        "scaffold_version": "0.1.0",
        "n_tasks": 2,
        "n_runs": 4,
        "n_seeds": 2,
        "pass_at_1": 0.75,
        "pass_at_k": 1.0,
        "mean_cost_usd": 0.5,
        "mean_tokens": 300.0,
        "mean_wall_s": 3.0,
    }
    # Sanity: the SQL emitted is the leaderboard CTE, not some other query.
    sql, _ = conn.executed[0]
    assert "WITH universe AS" in sql
    assert "ORDER BY t.pass_at_1 DESC" in sql


def test_leaderboard_empty_returns_empty_list():
    conn = FakeConn(results=[FakeResult(fetchall=[])])
    assert leaderboard(conn) == []
