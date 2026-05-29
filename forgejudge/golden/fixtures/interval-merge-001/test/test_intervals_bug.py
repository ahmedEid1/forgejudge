from intervals import merge


def test_touching_intervals_merge():
    # closed intervals (1,3) and (3,5) share endpoint 3 -> (1,5)
    assert merge([(1, 3), (3, 5)]) == [(1, 5)]


def test_chain_of_touching_intervals():
    assert merge([(1, 2), (2, 3), (3, 4)]) == [(1, 4)]


def test_touching_then_gap():
    # (1,3)+(3,6) merge; (8,9) is separate
    assert merge([(1, 3), (3, 6), (8, 9)]) == [(1, 6), (8, 9)]


def test_touching_unsorted():
    assert merge([(5, 7), (1, 3), (3, 5)]) == [(1, 7)]
