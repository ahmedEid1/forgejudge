"""Smoke test: the package imports and reports its version."""

import forgejudge


def test_version():
    assert forgejudge.__version__ == "0.1.0"
