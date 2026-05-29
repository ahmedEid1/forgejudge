"""Run store: insert/read RunRecords and aggregate the leaderboard.

Runs against DATABASE_URL or FJ_LOCAL_DATABASE_URL (local pgvector docker);
skipped if neither is reachable."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

from forgejudge.store.db import connect, get_run, init_db, insert_run, leaderboard, upsert_task
from forgejudge.types import GradeResult, RunRecord, Task

pytestmark = pytest.mark.db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")


@pytest.fixture
def conn():
    dsn = os.getenv("DATABASE_URL") or os.getenv("FJ_LOCAL_DATABASE_URL")
    if not dsn:
        pytest.skip("no DATABASE_URL / FJ_LOCAL_DATABASE_URL")
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
    # model A: task1 resolved x2 seeds, task2 never -> pass@1 0.5, pass@3 0.5
    insert_run(conn, _run("a1", "task1", "A", 0, True))
    insert_run(conn, _run("a2", "task1", "A", 1, True))
    insert_run(conn, _run("a3", "task2", "A", 0, False))
    insert_run(conn, _run("a4", "task2", "A", 1, False))
    # model B: task1 1/2, task2 2/2 -> pass@1 0.75, pass@3 1.0
    insert_run(conn, _run("b1", "task1", "B", 0, True))
    insert_run(conn, _run("b2", "task1", "B", 1, False))
    insert_run(conn, _run("b3", "task2", "B", 0, True))
    insert_run(conn, _run("b4", "task2", "B", 1, True))

    rows = {r["model"]: r for r in leaderboard(conn)}
    assert rows["A"]["n_tasks"] == 2 and rows["A"]["n_runs"] == 4
    assert rows["A"]["pass_at_1"] == pytest.approx(0.5)
    assert rows["A"]["pass_at_3"] == pytest.approx(0.5)
    assert rows["B"]["pass_at_1"] == pytest.approx(0.75)
    assert rows["B"]["pass_at_3"] == pytest.approx(1.0)
    # leaderboard is ordered best pass@1 first
    assert [r["model"] for r in leaderboard(conn)][0] == "B"


def test_insert_run_is_idempotent_on_run_id(conn):
    insert_run(conn, _run("dup", "t", "A", 0, True))
    insert_run(conn, _run("dup", "t", "A", 0, False))  # upsert overwrites
    assert get_run(conn, "dup").resolved is False
