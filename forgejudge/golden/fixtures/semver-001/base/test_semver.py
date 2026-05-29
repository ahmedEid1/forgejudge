from semver import compare


def test_equal():
    assert compare("1.0.0", "1.0.0") == 0


def test_simple_greater():
    assert compare("1.2.0", "1.1.0") == 1


def test_simple_less():
    assert compare("1.0.0", "2.0.0") == -1
