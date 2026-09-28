"""Smoke test: the package imports and reports a well-formed version.

Version-agnostic on purpose (#9): a release bump must not require editing this
test. It instead guards what can actually break — ``__version__`` drifting from
the ``[project].version`` that the build publishes.
"""

import re
import tomllib
from pathlib import Path

import forgejudge

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_version_is_well_formed():
    assert re.match(r"^\d+\.\d+\.\d+", forgejudge.__version__), forgejudge.__version__


def test_version_matches_pyproject():
    project_version = tomllib.loads(PYPROJECT.read_text())["project"]["version"]
    assert forgejudge.__version__ == project_version
