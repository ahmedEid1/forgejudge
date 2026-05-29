"""The LLM router: role -> ordered model fallback chain over litellm, with
per-run_id cost accounting. litellm is fully mocked here — no network or API key.
"""

from types import SimpleNamespace

import pytest

from forgejudge.llm import router


def _resp(content="ok", prompt_tokens=11, completion_tokens=7):
    """Build an object shaped like a litellm ChatCompletion response."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


@pytest.fixture(autouse=True)
def _clean_ledger():
    """Each test starts (and ends) with no accumulated cost."""
    router._LEDGER.clear()
    yield
    router._LEDGER.clear()


def test_primary_model_used_and_completion_populated(monkeypatch):
    calls = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        return _resp(content="hello", prompt_tokens=42, completion_tokens=9)

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)

    out = router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")

    # "edit" chain primary is groq/openai/gpt-oss-120b — it must be tried first.
    assert calls[0] == "groq/openai/gpt-oss-120b"
    assert out.model == "groq/openai/gpt-oss-120b"
    assert out.text == "hello"
    assert out.tokens_in == 42
    assert out.tokens_out == 9


def test_falls_back_to_next_model_on_primary_failure(monkeypatch):
    calls = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        if model == "groq/openai/gpt-oss-120b":  # primary of the "edit" chain
            raise RuntimeError("primary is down")
        return _resp(content="from fallback")

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)

    out = router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")

    assert calls == ["groq/openai/gpt-oss-120b", "groq/llama-3.3-70b-versatile"]
    assert out.model == "groq/llama-3.3-70b-versatile"
    assert out.text == "from fallback"


def test_all_models_failing_raises_runtimeerror(monkeypatch):
    def fake_completion(*, model, messages, seed=None):
        raise RuntimeError(f"{model} exploded")

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)

    with pytest.raises(RuntimeError) as ei:
        router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")

    # The error names the chain that was attempted.
    msg = str(ei.value)
    assert "groq/openai/gpt-oss-120b" in msg
    assert "groq/llama-3.3-70b-versatile" in msg


def test_cost_accumulates_per_run_id(monkeypatch):
    monkeypatch.setattr(
        router.litellm, "completion", lambda *, model, messages, seed=None: _resp()
    )
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.25)

    assert router.run_cost("r1") == 0.0

    router.complete([{"role": "user", "content": "a"}], role="critic", run_id="r1")
    assert router.run_cost("r1") == pytest.approx(0.25)

    router.complete([{"role": "user", "content": "b"}], role="critic", run_id="r1")
    assert router.run_cost("r1") == pytest.approx(0.50)

    # A different run_id is independent.
    router.complete([{"role": "user", "content": "c"}], role="critic", run_id="r2")
    assert router.run_cost("r2") == pytest.approx(0.25)
    assert router.run_cost("r1") == pytest.approx(0.50)

    router.reset_run("r1")
    assert router.run_cost("r1") == 0.0
    assert router.run_cost("r2") == pytest.approx(0.25)


def test_completion_cost_failure_defaults_to_zero(monkeypatch):
    monkeypatch.setattr(router.litellm, "completion", lambda *, model, messages, seed=None: _resp())

    def boom(resp):
        raise RuntimeError("no pricing for this free model")

    monkeypatch.setattr(router.litellm, "completion_cost", boom)

    out = router.complete([{"role": "user", "content": "hi"}], role="judge", run_id="r1")
    assert out.cost_usd == 0.0
    assert router.run_cost("r1") == 0.0


# --- Finding #3: seed is forwarded to the underlying litellm call -----------


def test_seed_is_forwarded_to_litellm(monkeypatch):
    seen = {}

    def fake_completion(*, model, messages, seed=None):
        seen["seed"] = seed
        return _resp()

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)

    router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1", seed=7)
    assert seen["seed"] == 7


def test_distinct_seeds_reach_provider(monkeypatch):
    """Different seeds must produce distinct provider requests (the multi-seed
    CI gate depends on real per-seed variation, not a constant)."""
    seeds_seen = []

    def fake_completion(*, model, messages, seed=None):
        seeds_seen.append(seed)
        return _resp()

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)

    for s in (0, 1, 2):
        router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1", seed=s)
    assert seeds_seen == [0, 1, 2]


def test_seed_defaults_to_none_when_omitted(monkeypatch):
    seen = {}

    def fake_completion(*, model, messages, seed=None):
        seen["seed"] = seed
        return _resp()

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)

    router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")
    assert seen["seed"] is None


# --- Finding #23: bounded retry/backoff on rate-limit (429) errors ----------


def _rate_limit_error(model, retry_after=None):
    """Build a litellm RateLimitError, optionally carrying a Retry-After header."""
    response = None
    if retry_after is not None:
        import httpx

        response = httpx.Response(429, headers={"Retry-After": str(retry_after)})
    return router.litellm.RateLimitError(
        message="rate limited", llm_provider="groq", model=model, response=response
    )


def test_rate_limit_retries_same_model_before_falling_back(monkeypatch):
    """A transient 429 on the primary must retry the SAME model, not immediately
    fall through to the lower-quality fallback."""
    calls = []
    sleeps = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        # Primary 429s once, then succeeds on retry.
        if model == "groq/openai/gpt-oss-120b" and calls.count(model) == 1:
            raise _rate_limit_error(model)
        return _resp(content="primary recovered")

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)
    monkeypatch.setattr(router, "_sleep", lambda secs: sleeps.append(secs))

    out = router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")

    # Stayed on primary: retried it, never advanced to the fallback.
    assert calls == ["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-120b"]
    assert out.model == "groq/openai/gpt-oss-120b"
    assert out.text == "primary recovered"
    assert len(sleeps) == 1  # backed off exactly once before the successful retry


def test_rate_limit_retries_are_bounded_then_falls_back(monkeypatch):
    """If a model keeps 429ing past the retry budget, the chain advances."""
    calls = []
    sleeps = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        if model == "groq/openai/gpt-oss-120b":
            raise _rate_limit_error(model)
        return _resp(content="fallback served")

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)
    monkeypatch.setattr(router, "_sleep", lambda secs: sleeps.append(secs))

    out = router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")

    primary_attempts = calls.count("groq/openai/gpt-oss-120b")
    # Bounded: primary tried _MAX_RATE_LIMIT_ATTEMPTS times, no more.
    assert primary_attempts == router._MAX_RATE_LIMIT_ATTEMPTS
    # Backed off once per failed attempt that had a remaining retry.
    assert len(sleeps) == router._MAX_RATE_LIMIT_ATTEMPTS - 1
    assert out.model == "groq/llama-3.3-70b-versatile"
    assert out.text == "fallback served"


def test_rate_limit_honors_retry_after_header(monkeypatch):
    """When the 429 carries Retry-After, the backoff sleep honors it."""
    calls = []
    sleeps = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        if calls.count(model) == 1:
            raise _rate_limit_error(model, retry_after=9)
        return _resp()

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)
    monkeypatch.setattr(router, "_sleep", lambda secs: sleeps.append(secs))

    router.complete([{"role": "user", "content": "hi"}], role="localize", run_id="r1")

    assert sleeps == [9.0]  # honored Retry-After exactly


def test_single_entry_chain_retries_on_rate_limit_before_raising(monkeypatch):
    """Single-entry chains (localize/critic) must not raise on the first 429 —
    they have to retry the only model they have."""
    calls = []
    sleeps = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        if calls.count(model) == 1:
            raise _rate_limit_error(model)
        return _resp(content="recovered")

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)
    monkeypatch.setattr(router, "_sleep", lambda secs: sleeps.append(secs))

    out = router.complete([{"role": "user", "content": "hi"}], role="critic", run_id="r1")

    assert out.text == "recovered"
    assert calls == ["groq/llama-3.3-70b-versatile", "groq/llama-3.3-70b-versatile"]


def test_hard_error_does_not_retry_and_advances_immediately(monkeypatch):
    """A genuine (non-rate-limit) error advances to the next model with no retry
    and no backoff — fallback stays fast for real outages."""
    calls = []
    sleeps = []

    def fake_completion(*, model, messages, seed=None):
        calls.append(model)
        if model == "groq/openai/gpt-oss-120b":
            raise RuntimeError("auth/model error — permanent")
        return _resp(content="fallback")

    monkeypatch.setattr(router.litellm, "completion", fake_completion)
    monkeypatch.setattr(router.litellm, "completion_cost", lambda resp: 0.0)
    monkeypatch.setattr(router, "_sleep", lambda secs: sleeps.append(secs))

    out = router.complete([{"role": "user", "content": "hi"}], role="edit", run_id="r1")

    # Primary tried exactly once (no retry), then advanced; no backoff slept.
    assert calls == ["groq/openai/gpt-oss-120b", "groq/llama-3.3-70b-versatile"]
    assert sleeps == []
    assert out.model == "groq/llama-3.3-70b-versatile"
