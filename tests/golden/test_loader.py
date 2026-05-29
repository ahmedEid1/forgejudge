"""Tests for the golden-set JSONL loader."""

import pytest

from forgejudge.golden.loader import load_tasks, validate_dataset
from forgejudge.types import Task

VALID_LINE = (
    '{"instance_id":"fixture-a-001","family":"make_ci_green","repo":"fixture:a",'
    '"base_commit":"","problem_statement":"p","test_patch":"d","fail_to_pass":["t::x"],'
    '"pass_to_pass":["t::y"],"env_image":"img","source_license":"own","created_at":"2026-05-29"}'
)


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
