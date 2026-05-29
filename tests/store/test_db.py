"""Run store: insert/read RunRecords and aggregate the leaderboard.

Runs against DATABASE_URL or FJ_LOCAL_DATABASE_URL (local pgvector docker);
skipped if neither is reachable."""

from pathlib import Path

import pytest
from dotenv import load_dotenv

from forgejudge.store.db import connect, get_run, init_db, insert_run, leaderboard, upsert_task
from forgejudge.types import GradeResult, RunRecord, Task
from tests.conftest import _is_local_dsn, local_db_dsn

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")


@pytest.fixture
def conn():
    # Tests TRUNCATE — use ONLY the disposable LOCAL db, NEVER production Neon.
    # local_db_dsn() reads only FJ_LOCAL_DATABASE_URL and refuses non-local hosts.
    dsn = local_db_dsn()
    if not dsn:
        pytest.skip("no local FJ_LOCAL_DATABASE_URL (refusing to TRUNCATE prod)")
    try:
        c = connect(dsn)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unreachable: {exc}")
    init_db(c)
    c.execute("TRUNCATE runs, tasks")
    c.commit()
    yield c
    c.close()


def _run(run_id, task_id, model, seed, resolved, cost=0.0, tokens=100):
    g = GradeResult(
        f2p_passed=1 if resolved else 0, f2p_total=1,
        p2p_passed=1, p2p_total=1, logs="",
    )
    return RunRecord(
        run_id=run_id, task_id=task_id, model=model, scaffold_version="0.1.0", seed=seed,
        resolved=resolved, grade=g, patch="--- a\n+++ b\n", tokens_in=tokens, tokens_out=tokens // 2,
        cost_usd=cost, wall_clock_s=1.5, trace_url=f"https://lf/{run_id}", status="ok",
        created_at="2026-05-29T00:00:00Z",
    )


# --- Finding #11: destructive-fixture safety (these run WITHOUT a DB) -------

def test_local_db_dsn_never_falls_back_to_prod(monkeypatch):
    """With FJ_LOCAL_DATABASE_URL unset, resolution must NOT fall back to the
    production DATABASE_URL — it must return None so the fixture skips."""
    monkeypatch.delenv("FJ_LOCAL_DATABASE_URL", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@ep-snowy-boat.eu-central-1.aws.neon.tech/neondb",
    )
    assert local_db_dsn() is None


def test_local_db_dsn_refuses_neon_host():
    """Even if someone puts a Neon URL in FJ_LOCAL_DATABASE_URL, it is refused
    so TRUNCATE can never hit the production leaderboard DB."""
    neon = "postgresql://u:p@ep-snowy-boat.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    assert _is_local_dsn(neon) is False


def test_local_db_dsn_accepts_only_local_hosts(monkeypatch):
    for dsn in (
        "postgresql://test:test@localhost:5433/forgejudge",
        "postgresql://test:test@127.0.0.1:5433/forgejudge",
    ):
        assert _is_local_dsn(dsn) is True
        monkeypatch.setenv("FJ_LOCAL_DATABASE_URL", dsn)
        assert local_db_dsn() == dsn


def test_local_db_dsn_none_when_unset(monkeypatch):
    monkeypatch.delenv("FJ_LOCAL_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert local_db_dsn() is None


def test_insert_and_get_run_round_trips(conn):
    t = Task(instance_id="t1", family="make_ci_green", repo="fixture:t1", base_commit="",
             problem_statement="p", test_patch="d", fail_to_pass=["a::x"], pass_to_pass=["a::y"],
             env_image="img", source_license="own", created_at="2026-05-29")
    upsert_task(conn, t)
    insert_run(conn, _run("r1", "t1", "groq/llama", 0, True, cost=0.0, tokens=200))
    got = get_run(conn, "r1")
    assert got is not None
    assert got.run_id == "r1" and got.resolved is True
    assert got.grade.f2p_passed == got.grade.f2p_total
    assert got.tokens_in == 200 and got.trace_url == "https://lf/r1"


def test_leaderboard_aggregates_pass_at_k(conn):
    # model A: task1 resolved x2 seeds, task2 never -> pass@1 0.5, pass@k 0.5
    insert_run(conn, _run("a1", "task1", "A", 0, True))
    insert_run(conn, _run("a2", "task1", "A", 1, True))
    insert_run(conn, _run("a3", "task2", "A", 0, False))
    insert_run(conn, _run("a4", "task2", "A", 1, False))
    # model B: task1 1/2, task2 2/2 -> pass@1 0.75, pass@k 1.0
    insert_run(conn, _run("b1", "task1", "B", 0, True))
    insert_run(conn, _run("b2", "task1", "B", 1, False))
    insert_run(conn, _run("b3", "task2", "B", 0, True))
    insert_run(conn, _run("b4", "task2", "B", 1, True))

    rows = {r["model"]: r for r in leaderboard(conn)}
    assert rows["A"]["n_tasks"] == 2 and rows["A"]["n_runs"] == 4
    # finding #39: pass@k is named generically; n_seeds reports the real k
    assert rows["A"]["n_seeds"] == 2
    assert rows["A"]["pass_at_1"] == pytest.approx(0.5)
    assert rows["A"]["pass_at_k"] == pytest.approx(0.5)
    assert rows["B"]["pass_at_1"] == pytest.approx(0.75)
    assert rows["B"]["pass_at_k"] == pytest.approx(1.0)
    # finding #28: cost/tokens/wall are per-TASK (summed within a task), not
    # per-run. tokens_in=100, tokens_out=50 -> 150/run; 2 runs/task -> 300/task.
    assert rows["A"]["mean_tokens"] == pytest.approx(300.0)
    assert rows["A"]["mean_wall_s"] == pytest.approx(3.0)  # 1.5s/run * 2 runs/task
    # leaderboard is ordered best pass@1 first
    assert [r["model"] for r in leaderboard(conn)][0] == "B"


def test_pass_at_k_denominator_is_full_task_universe(conn):
    """Finding #38: a model that skipped a task must NOT be scored only over the
    tasks it attempted. The universe is every task seen across all runs, so a
    skipped task counts as not-resolved and the score does not inflate."""
    # complete model: both tasks present, both resolved on every seed
    insert_run(conn, _run("c1", "task1", "complete", 0, True))
    insert_run(conn, _run("c2", "task1", "complete", 1, True))
    insert_run(conn, _run("c3", "task2", "complete", 0, True))
    insert_run(conn, _run("c4", "task2", "complete", 1, True))
    # partial model: only ran task1 (resolved). task2 crashed/skipped -> absent.
    insert_run(conn, _run("p1", "task1", "partial", 0, True))
    insert_run(conn, _run("p2", "task1", "partial", 1, True))

    rows = {r["model"]: r for r in leaderboard(conn)}
    # universe = {task1, task2}; partial is scored over BOTH, not just task1
    assert rows["partial"]["n_tasks"] == 2
    assert rows["partial"]["pass_at_1"] == pytest.approx(0.5)  # task1=1.0, task2=0
    assert rows["partial"]["pass_at_k"] == pytest.approx(0.5)  # 1 of 2 tasks
    # complete model is perfect and must rank above the would-be-inflated one
    assert rows["complete"]["pass_at_1"] == pytest.approx(1.0)
    assert rows["complete"]["pass_at_k"] == pytest.approx(1.0)
    assert [r["model"] for r in leaderboard(conn)][0] == "complete"


def test_pass_at_k_n_seeds_reflects_actual_seed_count(conn):
    """Finding #39: the metric is any-seed-resolves over the seeds actually run;
    n_seeds exposes the real k so the label can't silently lie as 'pass@3'."""
    # only 2 seeds swept -> n_seeds == 2 (not a hard-coded 3)
    insert_run(conn, _run("s1", "task1", "twoseed", 0, False))
    insert_run(conn, _run("s2", "task1", "twoseed", 1, True))
    row = leaderboard(conn)[0]
    assert row["n_seeds"] == 2
    assert "pass_at_k" in row and "pass_at_3" not in row  # column renamed
    assert row["pass_at_k"] == pytest.approx(1.0)  # any of the 2 seeds resolved


def test_insert_run_is_idempotent_on_run_id(conn):
    insert_run(conn, _run("dup", "t", "A", 0, True))
    insert_run(conn, _run("dup", "t", "A", 0, False))  # upsert overwrites
    assert get_run(conn, "dup").resolved is False
