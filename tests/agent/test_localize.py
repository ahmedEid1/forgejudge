"""BM25 fault localization: rank the buggy source file ahead of unrelated ones,
never surface test files, and degrade gracefully on an empty repo.
"""

import shutil
from pathlib import Path

from forgejudge.agent.localize import localize
from forgejudge.types import Task

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEMVER_BASE = REPO_ROOT / "forgejudge" / "golden" / "fixtures" / "semver-001" / "base"

# A repo whose discount.py is the obvious culprit for the problem statement, plus
# four unrelated source files and a test file that must never be returned.
_SOURCES = {
    "discount.py": (
        "def calculate_discount(total, coupon):\n"
        '    """Apply a coupon to an order total and return the discounted total."""\n'
        "    return total - coupon  # BUG: ignores percentage coupons\n"
    ),
    "utils.py": (
        "def slugify(text):\n"
        "    return text.strip().lower().replace(' ', '-')\n"
    ),
    "parser.py": (
        "def parse(tokens):\n"
        "    return [t for t in tokens if t]\n"
    ),
    "config.py": (
        "SETTINGS = {'debug': False, 'timeout': 30}\n"
    ),
    "models.py": (
        "class User:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
    ),
}

_TEST_FILE = (
    "from discount import calculate_discount\n\n\n"
    "def test_calculate_discount_with_coupon():\n"
    "    assert calculate_discount(100, 10) == 90\n"
)


def _make_task(repo: str = "fixture:synthetic", *, problem: str, f2p: list[str]) -> Task:
    return Task(
        instance_id="fixture-synthetic-001",
        family="make_ci_green",
        repo=repo,
        base_commit="",
        problem_statement=problem,
        test_patch="",
        fail_to_pass=f2p,
        pass_to_pass=[],
        env_image="python:3.12-slim",
        source_license="own",
        created_at="2026-05-29",
    )


def _build_synthetic_repo(root: Path) -> Path:
    for name, body in _SOURCES.items():
        (root / name).write_text(body)
    (root / "test_discount.py").write_text(_TEST_FILE)
    return root


def test_buggy_file_is_localized(tmp_path):
    repo = _build_synthetic_repo(tmp_path)
    task = _make_task(
        problem="calculate_discount returns the wrong total when a coupon is applied",
        f2p=["test_discount.py::test_calculate_discount_with_coupon"],
    )
    result = localize(task, repo, top_k=3)
    assert "discount.py" in result
    assert len(result) <= 3


def test_test_files_are_never_returned(tmp_path):
    repo = _build_synthetic_repo(tmp_path)
    # Add files matching every excluded shape, all packed with query terms so a
    # broken filter would surface them.
    body = (
        "def calculate_discount(total, coupon):\n"
        "    return total - coupon\n"
    )
    (repo / "test_extra.py").write_text(body)
    (repo / "discount_test.py").write_text(body)
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "helpers.py").write_text(body)  # under tests/ -> excluded

    task = _make_task(
        problem="calculate_discount returns the wrong total when a coupon is applied",
        f2p=["test_discount.py::test_calculate_discount_with_coupon"],
    )
    result = localize(task, repo, top_k=10)

    assert result, "expected at least one source candidate"
    for path in result:
        name = Path(path).name
        assert not name.startswith("test_")
        assert not name.endswith("_test.py")
        assert "tests/" not in path and not path.startswith("test/")


def test_empty_repo_returns_empty(tmp_path):
    # No .py files at all.
    (tmp_path / "README.md").write_text("nothing to localize here\n")
    task = _make_task(problem="anything", f2p=[])
    assert localize(task, tmp_path, top_k=5) == []


def test_missing_repo_dir_returns_empty(tmp_path):
    task = _make_task(problem="anything", f2p=[])
    assert localize(task, tmp_path / "does-not-exist", top_k=5) == []


def test_top_k_is_respected(tmp_path):
    repo = _build_synthetic_repo(tmp_path)
    task = _make_task(
        problem="calculate_discount returns the wrong total when a coupon is applied",
        f2p=["test_discount.py::test_calculate_discount_with_coupon"],
    )
    assert len(localize(task, repo, top_k=2)) <= 2


def test_real_fixture_semver_ranked_first(tmp_path):
    # Materialize the semver-001 base (semver.py + test_semver.py) and confirm the
    # single source file is the top-1 candidate.
    repo = tmp_path / "semver"
    shutil.copytree(SEMVER_BASE, repo)
    task = _make_task(
        repo="fixture:semver",
        problem=(
            "compare('1.10.0', '1.9.0') returns -1, but 1.10.0 is newer so it should "
            "return 1. Version ordering is wrong when one component has more digits."
        ),
        f2p=[
            "test_semver_bug.py::test_double_digit_minor",
            "test_semver_bug.py::test_double_digit_symmetry",
        ],
    )
    result = localize(task, repo, top_k=5)
    assert result, "expected semver.py to be localized"
    assert result[0] == "semver.py"
    assert "test_semver.py" not in result
