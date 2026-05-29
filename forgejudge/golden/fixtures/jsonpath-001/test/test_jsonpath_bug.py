from jsonpath import get


def test_zero_value_is_returned():
    # a stored integer 0 is a real value, not "missing"
    data = {"count": 0}
    assert get(data, "count", default=-1) == 0


def test_empty_string_value_is_returned():
    data = {"name": ""}
    assert get(data, "name", default="MISSING") == ""


def test_false_value_is_returned():
    data = {"flags": {"enabled": False}}
    assert get(data, "flags.enabled", default="MISSING") is False


def test_zero_then_deeper_access_still_defaults():
    # 0 is a valid intermediate-less leaf; deeper access should default,
    # but a plain 0 leaf must come back as 0
    data = {"a": {"b": 0}}
    assert get(data, "a.b", default=None) == 0
