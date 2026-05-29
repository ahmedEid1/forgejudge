import pytest
from window_stats import sample_variance


def test_sample_variance_two_values():
    # Bessel-corrected: divide sum of squared deviations by n-1 = 1, not n = 2.
    # mean=3, deviations 1 and 1 -> 2 / 1 == 2.0 (a biased estimator gives 1.0).
    assert sample_variance([2.0, 4.0]) == 2.0


def test_sample_variance_three_values():
    # mean=3, squared deviations 9 + 0 + 9 = 18, divided by n-1 = 2 -> 9.0
    # (dividing by n=3 would give the biased 6.0).
    assert sample_variance([0.0, 3.0, 6.0]) == 9.0


def test_sample_variance_wide_spread():
    # mean=5, squared deviations 25 + 25 = 50, divided by n-1 = 1 -> 50.0.
    assert sample_variance([0.0, 10.0]) == 50.0


def test_sample_variance_single_value_raises():
    # One value has zero degrees of freedom: sample variance is undefined.
    with pytest.raises(ValueError):
        sample_variance([5.0])
