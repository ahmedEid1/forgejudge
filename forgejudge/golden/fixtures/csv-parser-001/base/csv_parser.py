"""Parse a single CSV record into a list of field strings.

Supports comma separators and double-quoted fields. Inside a quoted field a
comma is a literal character (not a separator), and a doubled quote (``""``)
represents a single literal quote. Surrounding quotes are stripped from the
returned field.
"""


def parse_line(line: str) -> list[str]:
    fields: list[str] = []
    buf: list[str] = []
    in_quotes = False
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if in_quotes:
            if ch == '"':
                in_quotes = False
                i += 1
                continue
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_quotes = True
            i += 1
            continue
        if ch == ",":
            fields.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    fields.append("".join(buf))
    return fields
