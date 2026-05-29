from retry import retry


def test_succeeds_on_final_attempt():
    # With attempts=3 the function should be called a 3rd time; it succeeds then.
    calls = []

    @retry(attempts=3)
    def f():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("boom")
        return "ok"

    assert f() == "ok"
    assert len(calls) == 3


def test_all_attempts_are_used():
    calls = []

    @retry(attempts=4)
    def f():
        calls.append(1)
        raise ValueError("always")

    try:
        f()
    except ValueError:
        pass
    assert len(calls) == 4
