import pytest

from retry import retry


def test_success_first_try():
    calls = []

    @retry(attempts=3)
    def f():
        calls.append(1)
        return "ok"

    assert f() == "ok"
    assert len(calls) == 1


def test_recovers_on_second_attempt():
    calls = []

    @retry(attempts=3)
    def f():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("boom")
        return "ok"

    assert f() == "ok"
    assert len(calls) == 2


def test_raises_when_all_attempts_fail():
    @retry(attempts=3)
    def f():
        raise ValueError("always")

    with pytest.raises(ValueError):
        f()


def test_only_listed_exceptions_are_retried():
    calls = []

    @retry(attempts=3, exceptions=(KeyError,))
    def f():
        calls.append(1)
        raise ValueError("not retried")

    with pytest.raises(ValueError):
        f()
    assert len(calls) == 1


def test_invalid_attempts_rejected():
    with pytest.raises(ValueError):
        retry(attempts=0)
