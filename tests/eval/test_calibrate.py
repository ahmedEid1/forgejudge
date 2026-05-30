"""Hermetic tests for the judge calibration (Cohen's kappa) feature.

No real LLM, DB, or network: ``compute_calibration`` is pure, and the CLI/runner
is driven with an INJECTED fake ``complete_fn``. We pin the kappa edge cases
(perfect agreement -> 1.0, chance-level -> ~0, a known confusion -> exact kappa)
and the JSON artifact shape written by the CLI.
"""

import json
from pathlib import Path

import pytest

from forgejudge.eval.calibrate import (
    GOOD_THRESHOLD,
    compute_calibration,
    run_calibration,
    score_to_verdict,
    write_calibration,
)
from forgejudge.llm.router import Completion

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JUDGE_GOLD = REPO_ROOT / "golden" / "judge_gold.jsonl"

T = True
F = False


def _fake_complete(text: str):
    """An injected fake judge model: always replies with ``text`` (no network)."""

    def fn(messages, *, role, run_id):
        assert role == "judge"
        return Completion(text=text, tokens_in=1, tokens_out=1, cost_usd=0.0, model="fake")

    return fn


# --- score_to_verdict ----------------------------------------------------------


def test_score_to_verdict_thresholds_at_four():
    assert score_to_verdict(GOOD_THRESHOLD) is True
    assert score_to_verdict(5) is True
    assert score_to_verdict(GOOD_THRESHOLD - 1) is False
    assert score_to_verdict(1) is False


# --- compute_calibration: kappa edge cases -------------------------------------


def test_perfect_agreement_gives_kappa_one():
    pairs = [(T, T), (F, F), (T, T), (F, F)]
    out = compute_calibration(pairs)
    assert out["kappa"] == 1.0
    assert out["agreement"] == 1.0
    assert out["n"] == 4
    assert out["confusion"] == {"tp": 2, "fp": 0, "fn": 0, "tn": 2}


def test_chance_level_agreement_is_near_zero():
    # Judge and reference are independent / perfectly anti-correlated on a
    # balanced set: observed agreement equals chance agreement -> kappa ~ 0.
    # Swapped labels on a balanced 2x2 give po=0, pe=0.5 -> kappa = -1 (<= 0),
    # while an independent split lands at 0. Use a no-signal judge (constant)
    # against a balanced reference: po == pe -> kappa == 0.
    pairs = [(T, T), (T, F), (T, T), (T, F)]  # judge always "good"
    out = compute_calibration(pairs)
    assert out["kappa"] == pytest.approx(0.0, abs=1e-12)


def test_known_confusion_matches_hand_computed_kappa():
    # tp=3, tn=3, fp=1, fn=1  (n=8). po = 6/8 = 0.75.
    # marginals: judge good = 4/8, ref good = 4/8 -> pe = .5*.5 + .5*.5 = 0.5.
    # kappa = (0.75 - 0.5) / (1 - 0.5) = 0.5.
    pairs = (
        [(T, T)] * 3  # tp
        + [(F, F)] * 3  # tn
        + [(T, F)] * 1  # fp
        + [(F, T)] * 1  # fn
    )
    out = compute_calibration(pairs)
    assert out["confusion"] == {"tp": 3, "fp": 1, "fn": 1, "tn": 3}
    assert out["agreement"] == pytest.approx(0.75)
    assert out["kappa"] == pytest.approx(0.5, abs=1e-12)


def test_empty_pairs_is_graceful_empty_state():
    out = compute_calibration([])
    assert out["n"] == 0
    assert out["kappa"] is None
    assert out["agreement"] is None
    assert out["confusion"] == {"tp": 0, "fp": 0, "fn": 0, "tn": 0}


def test_by_label_recall_is_reported():
    pairs = [(T, T)] * 3 + [(F, F)] * 3 + [(T, F)] + [(F, T)]
    out = compute_calibration(pairs)
    assert out["by_label"]["good"]["reference"] == 4  # tp + fn
    assert out["by_label"]["good"]["correct"] == 3  # tp
    assert out["by_label"]["good"]["recall"] == pytest.approx(3 / 4)
    assert out["by_label"]["bad"]["reference"] == 4  # tn + fp
    assert out["by_label"]["bad"]["recall"] == pytest.approx(3 / 4)


# --- CLI / runner over the real gold set, with an injected fake judge ----------


def test_run_calibration_with_perfect_fake_judge():
    """A fake judge that scores gold patches 5 and (empty) bad patches 1 should
    perfectly recover the human reference verdicts -> kappa 1.0."""
    # Gold rows carry the gold patch -> judge replies 5 (good). Bad rows are
    # judged as empty patches, which the judge shortcuts to 1 WITHOUT calling the
    # model, so the fake's text is only used for the gold rows.
    summary = run_calibration(complete_fn=_fake_complete("Score: 5\ngood"), model="fake")
    assert summary["kappa"] == 1.0
    assert summary["n"] >= 6
    # 4 gold rows (good) + 4 bad rows (bad) in the seed set.
    assert summary["confusion"]["tp"] >= 1
    assert summary["confusion"]["tn"] >= 1
    assert summary["confusion"]["fp"] == 0
    assert summary["confusion"]["fn"] == 0
    assert summary["model"] == "fake"
    assert "generated_at" in summary


def test_cli_writes_expected_json_shape(tmp_path):
    summary = run_calibration(complete_fn=_fake_complete("Score: 5\ngood"), model="fake")
    out = write_calibration(summary, tmp_path / "calibration.json")
    data = json.loads(out.read_text())
    assert set(data) == {
        "generated_at",
        "model",
        "kappa",
        "n",
        "agreement",
        "confusion",
        "by_label",
    }
    assert set(data["confusion"]) == {"tp", "fp", "fn", "tn"}
    assert set(data["by_label"]) == {"good", "bad"}
    assert data["kappa"] == 1.0
    assert data["model"] == "fake"


def test_main_dry_run_writes_empty_state_without_network(tmp_path, monkeypatch):
    # --dry-run must not import/touch the live judge path at all.
    import forgejudge.eval.calibrate as calib

    def _boom(*a, **k):
        raise AssertionError("--dry-run must not run the live judge")

    monkeypatch.setattr(calib, "run_calibration", _boom)
    out = tmp_path / "calibration.json"
    calib.main(["--dry-run", "--out", str(out), "--model", "none"])
    data = json.loads(out.read_text())
    assert data["kappa"] is None
    assert data["n"] == 0
    assert data["model"] == "none"
