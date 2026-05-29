from intervals import merge


def test_empty():
    assert merge([]) == []


def test_single():
    assert merge([(1, 4)]) == [(1, 4)]


def test_disjoint_kept_separate():
    assert merge([(1, 3), (5, 8)]) == [(1, 3), (5, 8)]


def test_strict_overlap_merges():
    # (1,5) and (3,8) clearly overlap (3 < 5)
    assert merge([(1, 5), (3, 8)]) == [(1, 8)]


def test_contained_interval():
    # (2,4) is fully inside (1,10)
    assert merge([(1, 10), (2, 4)]) == [(1, 10)]


def test_unsorted_input():
    assert merge([(6, 9), (1, 4)]) == [(1, 4), (6, 9)]
