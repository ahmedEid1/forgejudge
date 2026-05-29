from csv_parser import parse_line


def test_plain_fields():
    assert parse_line("a,b,c") == ["a", "b", "c"]


def test_empty_fields():
    assert parse_line("a,,c") == ["a", "", "c"]


def test_quoted_comma():
    assert parse_line('"a,b",c') == ["a,b", "c"]


def test_quoted_field_is_unwrapped():
    assert parse_line('"hello","world"') == ["hello", "world"]


def test_single_field():
    assert parse_line("solo") == ["solo"]
