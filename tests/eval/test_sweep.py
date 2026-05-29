"""The sweep runs every task x seed through the agent + grader and persists
RunRecords. Uses an injected fake router (no LLM) and the local DB."""

from pathlib import Path

import pytest
from dotenv import load_dotenv

from forgejudge.eval.sweep import run_sweep
from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.golden.loader import load_tasks
from forgejudge.llm.router import Completion
from tests.conftest import local_db_dsn

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(REPO_ROOT / ".env")
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
SEMVER = "fixture-semver-001"


def _gold_fake():
    gold = (source_dir_for(SEMVER) / "fix" / "semver.py").read_text()

    def fn(messages, *, role, run_id, seed=None):
        return Completion(text=f"```python\n{gold}```", tokens_in=100, tokens_out=40,
                          cost_usd=0.0, model="fake-model")
    return fn


@pytest.mark.slow
def test_run_sweep_returns_resolution_rate():
    res = run_sweep("fake-model", seeds=[0, 1], tasks=[TASKS[SEMVER]],
                    complete_fn=_gold_fake(), now="2026-05-29T00:00:00Z")
    assert len(res.records) == 2
    assert res.resolution_rate == 1.0
    assert all(r.resolved for r in res.records)
    assert res.records[0].tokens_in == 100  # carried from the solve


@pytest.mark.slow
@pytest.mark.db
def test_run_sweep_persists_to_store():
    # Tests TRUNCATE — use ONLY the disposable LOCAL db, NEVER production Neon.
    dsn = local_db_dsn()
    if not dsn:
        pytest.skip("no local FJ_LOCAL_DATABASE_URL (refusing to TRUNCATE prod)")
    from forgejudge.store.db import connect, init_db, leaderboard

    try:
        conn = connect(dsn)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unreachable: {exc}")
    init_db(conn)
    conn.execute("TRUNCATE runs, tasks")
    conn.commit()

    run_sweep("fake-model", seeds=[0, 1], tasks=[TASKS[SEMVER]],
              complete_fn=_gold_fake(), store_conn=conn, now="2026-05-29T00:00:00Z")
    board = leaderboard(conn)
    assert len(board) == 1
    assert board[0]["model"] == "fake-model"
    assert board[0]["pass_at_1"] == 1.0
    assert board[0]["pass_at_k"] == 1.0
    assert board[0]["n_runs"] == 2
    assert board[0]["n_seeds"] == 2  # finding #39: label reflects real seed count
    conn.close()
