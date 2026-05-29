from jsonpath import get


def test_nested_dict():
    data = {"user": {"address": {"city": "Cairo"}}}
    assert get(data, "user.address.city") == "Cairo"


def test_list_index():
    data = {"items": [{"name": "a"}, {"name": "b"}]}
    assert get(data, "items[1].name") == "b"


def test_missing_key_returns_default():
    data = {"a": {"b": 1}}
    assert get(data, "a.c", default="x") == "x"


def test_index_out_of_range():
    data = {"items": [1, 2]}
    assert get(data, "items[5]", default=None) is None
