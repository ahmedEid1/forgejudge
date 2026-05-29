from csv_parser import parse_line


def test_escaped_quote_in_field():
    # "" inside a quoted field is one literal double-quote character.
    assert parse_line('"a""b",c') == ['a"b', "c"]


def test_escaped_quote_with_inner_comma():
    assert parse_line('"she said ""hi, there"""') == ['she said "hi, there"']
