"""Evaluate arithmetic expressions written in Reverse Polish Notation.

Tokens are separated by whitespace. Supported binary operators: + - * /
Division is true (float) division. Raises ``ValueError`` on malformed input.
"""


def evaluate(expr: str) -> float:
    """Evaluate an RPN expression string and return the numeric result."""
    stack: list = []
    ops = {
        "+": lambda a, b: a + b,
        "-": lambda a, b: a - b,
        "*": lambda a, b: a * b,
        "/": lambda a, b: a / b,
    }
    for tok in expr.split():
        if tok in ops:
            if len(stack) < 2:
                raise ValueError(f"not enough operands for {tok!r}")
            b = stack.pop()
            a = stack.pop()
            stack.append(ops[tok](a, b))
        else:
            try:
                stack.append(float(tok))
            except ValueError:
                raise ValueError(f"invalid token: {tok!r}")
    if len(stack) != 1:
        raise ValueError("malformed expression")
    return stack[0]
