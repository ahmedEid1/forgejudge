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

    def fake_completion(*, model, messages):
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

    def fake_completion(*, model, messages):
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
    def fake_completion(*, model, messages):
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
    monkeypatch.setattr(router.litellm, "completion", lambda *, model, messages: _resp())
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
    monkeypatch.setattr(router.litellm, "completion", lambda *, model, messages: _resp())

    def boom(resp):
        raise RuntimeError("no pricing for this free model")

    monkeypatch.setattr(router.litellm, "completion_cost", boom)

    out = router.complete([{"role": "user", "content": "hi"}], role="judge", run_id="r1")
    assert out.cost_usd == 0.0
    assert router.run_cost("r1") == 0.0
