"""Tests for the golden-set JSONL loader."""

import pytest

from forgejudge.golden.loader import load_tasks, validate_dataset
from forgejudge.types import Task

VALID_LINE = (
    '{"instance_id":"fixture-a-001","family":"make_ci_green","repo":"fixture:a",'
    '"base_commit":"","problem_statement":"p","test_patch":"d","fail_to_pass":["t::x"],'
    '"pass_to_pass":["t::y"],"env_image":"img","source_license":"own","created_at":"2026-05-29"}'
)

# A Unicode line separator (U+2028) is a *legal* JSON-string character that
# Pydantic's model_dump_json emits raw, but str.splitlines() treats as a line
# boundary. Finding #20.
LS = "\u2028"  # LINE SEPARATOR
PS = "\u2029"  # PARAGRAPH SEPARATOR


def _line(instance_id: str) -> str:
    return VALID_LINE.replace("fixture-a-001", instance_id)


def test_load_valid(tmp_path):
    p = tmp_path / "dataset.jsonl"
    p.write_text(_line("fixture-a-001") + "\n" + _line("fixture-b-002") + "\n")
    tasks = load_tasks(p)
    assert len(tasks) == 2
    assert all(isinstance(t, Task) for t in tasks)
    assert [t.instance_id for t in tasks] == ["fixture-a-001", "fixture-b-002"]


def test_blank_lines_are_skipped(tmp_path):
    p = tmp_path / "dataset.jsonl"
    p.write_text(_line("fixture-a-001") + "\n\n   \n")
    assert len(load_tasks(p)) == 1


def test_malformed_line_names_line_number(tmp_path):
    p = tmp_path / "dataset.jsonl"
    p.write_text(_line("fixture-a-001") + "\n" + "{not json}\n")
    with pytest.raises(ValueError, match=r"line 2"):
        load_tasks(p)


def test_schema_violation_names_line_number(tmp_path):
    p = tmp_path / "dataset.jsonl"
    p.write_text('{"instance_id":"x"}\n')  # missing required fields
    with pytest.raises(ValueError, match=r"line 1"):
        load_tasks(p)


def test_duplicate_instance_id_raises(tmp_path):
    p = tmp_path / "dataset.jsonl"
    p.write_text(_line("dup-001") + "\n" + _line("dup-001") + "\n")
    with pytest.raises(ValueError, match=r"dup-001"):
        load_tasks(p)


def test_validate_dataset_flags_duplicates():
    t1 = Task.model_validate_json(_line("z-001"))
    t2 = Task.model_validate_json(_line("z-001"))
    with pytest.raises(ValueError, match=r"z-001"):
        validate_dataset([t1, t2])


def test_unicode_line_separator_round_trips(tmp_path):
    """Finding #20: a Task whose problem_statement contains U+2028/U+2029
    serializes to ONE physical line via model_dump_json; the loader must split on
    '\\n' only, so the single record survives a write->read round trip."""
    t = Task(
        instance_id="ls-001",
        family="make_ci_green",
        repo="fixture:ls",
        base_commit="",
        problem_statement=f"first part{LS}second part{PS}third part",
        test_patch="d",
        fail_to_pass=["t::x"],
        pass_to_pass=["t::y"],
        env_image="img",
        source_license="own",
        created_at="2026-05-29",
    )
    p = tmp_path / "dataset.jsonl"
    # Exactly the writer idiom from build_dataset.build_dataset.
    p.write_text(t.model_dump_json() + "\n", encoding="utf-8")
    tasks = load_tasks(p)
    assert len(tasks) == 1
    assert tasks[0].problem_statement == t.problem_statement


def test_crlf_lines_are_tolerated(tmp_path):
    """A CRLF-terminated JSONL must not leave a stray '\\r' that corrupts parsing."""
    p = tmp_path / "dataset.jsonl"
    p.write_text(_line("crlf-001") + "\r\n" + _line("crlf-002") + "\r\n", encoding="utf-8")
    tasks = load_tasks(p)
    assert [t.instance_id for t in tasks] == ["crlf-001", "crlf-002"]


# --- mine_owned.repo_slug (Finding #32) -------------------------------------

def test_repo_slug_parses_ssh_form():
    """Finding #32: SCP/SSH remotes (git@host:owner/name.git) must yield the
    'owner/name' slug, not 'git@host:owner/name'."""
    from forgejudge.golden import mine_owned

    assert (
        mine_owned._slug_from_url("git@github.com:ahmedEid1/thoth.git")
        == "ahmedEid1/thoth"
    )
    assert (
        mine_owned._slug_from_url("https://github.com/ahmedEid1/thoth.git")
        == "ahmedEid1/thoth"
    )
    assert (
        mine_owned._slug_from_url("https://github.com/ahmedEid1/thoth")
        == "ahmedEid1/thoth"
    )


# --- build_dataset key validation & cutoff invariant (Findings #33, #34) -----

def _write_meta(task_dir, **overrides):
    import yaml

    (task_dir / "base").mkdir(parents=True, exist_ok=True)
    (task_dir / "test").mkdir(parents=True, exist_ok=True)
    (task_dir / "fix").mkdir(parents=True, exist_ok=True)
    meta = {
        "instance_id": "meta-001",
        "family": "make_ci_green",
        "problem_statement": "p",
        "fail_to_pass": ["t::x"],
        "pass_to_pass": ["t::y"],
        "created_at": "2026-05-29",
        "source_license": "own",
        "env_image": "python:3.12-slim",
    }
    meta.update(overrides)
    for k in [k for k, v in list(meta.items()) if v is _MISSING]:
        del meta[k]
    (task_dir / "meta.yaml").write_text(yaml.safe_dump(meta))
    return task_dir


_MISSING = object()


def test_build_task_missing_key_names_task_dir(tmp_path):
    """Finding #33: a meta.yaml missing a required key must raise a descriptive
    ValueError naming the task_dir + key, not a bare KeyError."""
    from forgejudge.golden.build_dataset import build_task

    d = _write_meta(tmp_path / "bad-001", fail_to_pass=_MISSING)
    with pytest.raises(ValueError) as exc:
        build_task(d)
    msg = str(exc.value)
    assert "fail_to_pass" in msg
    assert "bad-001" in msg


def test_build_task_null_problem_statement_is_descriptive(tmp_path):
    """Finding #33: a null/non-string problem_statement must not raise a bare
    AttributeError from .strip()."""
    from forgejudge.golden.build_dataset import build_task

    d = _write_meta(tmp_path / "bad-002", problem_statement=None)
    with pytest.raises(ValueError) as exc:
        build_task(d)
    assert "problem_statement" in str(exc.value)
    assert "bad-002" in str(exc.value)


def test_build_task_rejects_pre_cutoff_created_at(tmp_path):
    """Finding #34: created_at on/before the pinned model cutoff is a contamination
    risk and must be rejected, naming the task."""
    from forgejudge.golden.build_dataset import build_task

    d = _write_meta(tmp_path / "old-001", created_at="2019-01-01")
    with pytest.raises(ValueError) as exc:
        build_task(d)
    assert "old-001" in str(exc.value)
    assert "cutoff" in str(exc.value).lower()


def test_build_task_rejects_non_date_created_at(tmp_path):
    """Finding #34: a non-ISO created_at must raise a descriptive ValueError."""
    from forgejudge.golden.build_dataset import build_task

    d = _write_meta(tmp_path / "nd-001", created_at="not-a-date-at-all")
    with pytest.raises(ValueError) as exc:
        build_task(d)
    assert "nd-001" in str(exc.value)
    assert "created_at" in str(exc.value)
