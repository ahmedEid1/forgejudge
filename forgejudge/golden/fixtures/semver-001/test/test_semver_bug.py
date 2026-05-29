from semver import compare


def test_double_digit_minor():
    # 1.10.0 is newer than 1.9.0
    assert compare("1.10.0", "1.9.0") == 1


def test_double_digit_symmetry():
    assert compare("1.9.0", "1.10.0") == -1
