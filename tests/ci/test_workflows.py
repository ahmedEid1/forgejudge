"""Structural assertions on the GitHub Actions workflow YAML (unit L-ci-workflows).

These tests parse the committed workflow files and assert the *orchestration*
properties that the source-side fixes rely on. They guard against silent-pass CI
(findings #1, #36), the wrong-variance-axis gold gate (#2, #4), and supply-chain
hygiene in the privileged publish workflow (#15, #16). No workflow is executed;
we only read and parse the YAML.
"""

import re
from pathlib import Path

import pytest
import yaml

WF_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WF_DIR / name).read_text())


def _steps_text(job: dict) -> str:
    """Flatten every step's run/uses/with into one searchable blob."""
    parts: list[str] = []
    for step in job.get("steps", []):
        for key in ("run", "uses", "name"):
            if key in step and step[key] is not None:
                parts.append(str(step[key]))
        for v in (step.get("with") or {}).values():
            parts.append(str(v))
    return "\n".join(parts)


def _all_uses() -> list[str]:
    """Every ``uses:`` reference across all workflow files."""
    refs: list[str] = []
    for f in sorted(WF_DIR.glob("*.yml")):
        wf = yaml.safe_load(f.read_text())
        for job in (wf.get("jobs") or {}).values():
            for step in job.get("steps", []):
                if "uses" in step:
                    refs.append(step["uses"])
    return refs


def test_all_workflows_parse():
    files = sorted(WF_DIR.glob("*.yml"))
    assert files, "no workflow files found"
    for f in files:
        assert yaml.safe_load(f.read_text()) is not None, f"{f.name} did not parse"


# ---------------------------------------------------------------------------
# Finding #1: extra-gated jobs must not silently pass when the extra is missing.
# Each job that installs an optional extra must hard-verify the extra imports
# (so an install/resolution failure fails the job loudly, not silently green).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("job_name", "module"),
    [
        ("swebench-equivalence", "swebench"),
        ("mcp-server", "fastmcp"),
        ("playground", "fastapi"),
    ],
)
def test_extra_gated_job_verifies_import(job_name, module):
    ci = _load("ci.yml")
    job = ci["jobs"][job_name]
    blob = _steps_text(job)
    # A hard import check of the extra's top-level module must run BEFORE the
    # marker-selected pytest run, so a missing extra fails the job rather than
    # turning it into a zero-test no-op green check.
    assert re.search(rf"import {re.escape(module)}\b", blob), (
        f"{job_name}: no `python -c 'import {module}'` precondition — a failed "
        f"extra install would let the marker run collect zero tests and pass green"
    )


@pytest.mark.parametrize("job_name", ["swebench-equivalence", "mcp-server", "playground"])
def test_extra_gated_job_has_no_silent_masking(job_name):
    ci = _load("ci.yml")
    job = ci["jobs"][job_name]
    for step in job.get("steps", []):
        assert step.get("continue-on-error") is not True, (
            f"{job_name}: a step has continue-on-error: true (masks failures)"
        )
        run = step.get("run") or ""
        # `|| true` on the install or the pytest invocation would swallow a real
        # failure; the import-verify step's whole point is to fail loudly.
        assert "|| true" not in run, f"{job_name}: `|| true` masks a step failure"


# ---------------------------------------------------------------------------
# Findings #2 & #4: the gold gate must NOT feed task-shards into the multi-seed
# statistical CI. gate.yml must (a) run the deterministic gold smoke as an exact
# gate (mode exact / exact_gold_gate), and (b) keep the stochastic CI for seeds.
# ---------------------------------------------------------------------------

def test_gate_uses_exact_gold_mode_not_seed_ci():
    gate = _load("gate.yml")
    blob = "\n".join(_steps_text(j) for j in gate["jobs"].values())
    # The deterministic gold gate must run in exact mode (pooled 12/12 == 1.0),
    # never the per-seed regression_gate (which would treat the 4 shard rates as
    # noisy seeds and PASS a real partial breakage of 1/12 gold tasks).
    assert "--mode exact" in blob, (
        "gate.yml must invoke `forgejudge.eval.gate --mode exact` for the "
        "deterministic gold smoke; shard rates are NOT per-seed samples"
    )
    assert "--baseline eval/baseline_scores.json" not in blob, (
        "gate.yml must not feed the gold shards into the multi-seed CI baseline; "
        "that is the wrong variance axis (findings #2/#4)"
    )


# ---------------------------------------------------------------------------
# Finding #36: eval.yml gold self-test must actually fail when a gold task does
# not resolve. The runner exits non-zero on gold non-resolution; the workflow
# must not mask that exit (no `|| true`, no continue-on-error on grade/agg).
# ---------------------------------------------------------------------------

def test_eval_does_not_mask_gold_self_test_failure():
    ev = _load("eval.yml")
    for job in ev["jobs"].values():
        for step in job.get("steps", []):
            assert step.get("continue-on-error") is not True, (
                "eval.yml: continue-on-error would mask the gold self-test failure"
            )
            run = step.get("run") or ""
            if "runner_actions" in run:
                assert "|| true" not in run, (
                    "eval.yml: `|| true` on a runner_actions step masks the "
                    "gold self-test's non-zero exit (finding #36)"
                )
                # `tee` pipes the runner's stdout but, with default bash, the
                # pipeline exit status is tee's (0). The runner's non-zero exit
                # must be propagated via pipefail.
                if "tee" in run:
                    assert "pipefail" in run, (
                        "eval.yml: a runner_actions step piped through `tee` "
                        "must `set -o pipefail` so the runner's non-zero exit "
                        "is not swallowed by tee (finding #36)"
                    )


# ---------------------------------------------------------------------------
# Finding #15: every third-party action must be SHA-pinned (40-hex), especially
# in the privileged OIDC publish workflow.
# ---------------------------------------------------------------------------

_SHA_PINNED = re.compile(r"^[^@]+@[0-9a-f]{40}(\s|$)")


def test_all_actions_are_sha_pinned():
    unpinned = [u for u in _all_uses() if not _SHA_PINNED.match(u)]
    assert not unpinned, (
        "these actions are not pinned to a full 40-char commit SHA "
        f"(mutable tag = supply-chain risk): {unpinned}"
    )


def test_publish_workflow_actions_sha_pinned():
    pub = _load("publish-mcp.yml")
    for job in pub["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert _SHA_PINNED.match(step["uses"]), (
                    f"publish-mcp.yml uses an unpinned action in an OIDC "
                    f"token-minting job: {step['uses']}"
                )


# ---------------------------------------------------------------------------
# Finding #16: the mcp-publisher binary must be checksum-verified before the
# privileged sudo-install, and the install must not be masked with `|| true`.
# ---------------------------------------------------------------------------

def test_publish_verifies_binary_checksum():
    pub = _load("publish-mcp.yml")
    install_runs = [
        step.get("run", "")
        for job in pub["jobs"].values()
        for step in job.get("steps", [])
        if "mcp-publisher" in (step.get("run") or "") and "curl" in (step.get("run") or "")
    ]
    assert install_runs, "could not find the mcp-publisher curl install step"
    blob = "\n".join(install_runs)
    assert "sha256sum -c" in blob, (
        "publish-mcp.yml must verify the downloaded mcp-publisher tarball against "
        "a pinned SHA256 (`sha256sum -c`) before sudo-installing it (finding #16)"
    )
    assert "| tar" not in blob, (
        "publish-mcp.yml must download to a file and verify before extracting, "
        "not pipe curl straight into tar (finding #16)"
    )
    assert "|| true" not in blob, (
        "publish-mcp.yml install must not swallow failures with `|| true` (#16)"
    )


# --------------------------------------------------------------------------- #
# sweep.yml — the auto-publish pipeline (sweep all models -> quality-gated
# publish -> deploy -> commit). Guards the end-to-end leaderboard refresh.
# --------------------------------------------------------------------------- #


def test_sweep_publishes_and_deploys_end_to_end():
    wf = _load("sweep.yml")
    job = wf["jobs"]["sweep"]
    blob = _steps_text(job)
    # writes back the refreshed snapshot, so it needs contents: write
    assert (wf.get("permissions") or {}).get("contents") == "write", (
        "sweep.yml must grant contents: write to commit the refreshed snapshot"
    )
    # sweeps with --no-store so a degraded run cannot poison Neon directly
    assert "--no-store" in blob, "sweep must use --no-store and publish via the quality gate"
    # quality-gated publish, dashboard deploy, and commit-back are all present
    assert "forgejudge.eval.publish" in blob, "sweep must run the quality-gated publish step"
    assert "pages deploy" in blob, "sweep must deploy the refreshed dashboard to Cloudflare Pages"
    assert "dashboard/public/data" in blob, "sweep must commit the refreshed leaderboard snapshot back"


def test_sweep_covers_multiple_models():
    """The leaderboard's model-swap story needs every model swept, not just one."""
    wf = _load("sweep.yml")
    on = wf.get("on") or wf.get(True)  # PyYAML parses the `on:` key as boolean True
    default_models = on["workflow_dispatch"]["inputs"]["models"]["default"]
    assert default_models.count(",") >= 2, "sweep should default to sweeping all leaderboard models"
