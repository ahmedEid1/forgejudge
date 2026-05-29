import pytest
from window_stats import mean


def test_mean_basic():
    assert mean([2.0, 4.0, 6.0]) == 4.0


def test_mean_single_value():
    assert mean([7.0]) == 7.0


def test_mean_with_negatives():
    assert mean([-3.0, 3.0, -6.0, 6.0]) == 0.0


def test_mean_empty_raises():
    with pytest.raises(ValueError):
        mean([])
