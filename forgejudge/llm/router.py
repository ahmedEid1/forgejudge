"""Role-based LLM router over litellm with per-run cost accounting.

Every agent role (``plan``, ``localize``, ``edit``, ``critic``, ``judge``) maps to
an *ordered* fallback chain of litellm model ids, loaded from ``models.yaml``. A
:func:`complete` call walks the chain, returning the first model that succeeds; if
all fail it raises a clear :class:`RuntimeError` naming the chain it tried.

Cost is accumulated per ``run_id`` in a module-level ledger so a single agent run's
spend can be capped/inspected via :func:`run_cost` (and cleared via :func:`reset_run`).
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

import litellm
import yaml
from pydantic import BaseModel

Role = Literal["plan", "localize", "edit", "critic", "judge"]

# Optional override for the chain config; an env var takes precedence over this.
models_path: str | Path | None = None

_DEFAULT_MODELS_YAML = Path(__file__).parent / "models.yaml"

# run_id -> accumulated cost in USD across every complete() call for that run.
_LEDGER: dict[str, float] = {}

# Rate-limit (429) handling: the free-tier chains in models.yaml are routinely
# throttled, so a 429 is transient — retry the SAME model with bounded
# exponential backoff before advancing the fallback chain. Hard errors
# (auth/model/provider) still advance immediately.
_MAX_RATE_LIMIT_ATTEMPTS = 3  # total tries of one model on repeated 429s
_BACKOFF_BASE_SECONDS = 1.0  # exponential base: 1s, 2s, 4s, ...
_BACKOFF_MAX_SECONDS = 30.0  # cap any single backoff (incl. Retry-After)


def _sleep(seconds: float) -> None:
    """Indirection over ``time.sleep`` so tests can stub backoff deterministically."""
    time.sleep(seconds)


def _retry_after_seconds(exc: Exception) -> float | None:
    """Parse a ``Retry-After`` header (delay-seconds form) off a rate-limit error.

    Returns the delay in seconds when the provider sent one, else ``None``. Any
    malformed/absent header yields ``None`` so we fall back to exponential backoff.
    """
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None  # HTTP-date form is unsupported here; use exponential backoff.


def _backoff_seconds(exc: Exception, attempt: int) -> float:
    """How long to wait before the next retry: honor Retry-After, else exponential.

    ``attempt`` is 1-based (the attempt that just failed). The result is capped at
    :data:`_BACKOFF_MAX_SECONDS`.
    """
    retry_after = _retry_after_seconds(exc)
    if retry_after is not None:
        return min(max(retry_after, 0.0), _BACKOFF_MAX_SECONDS)
    return min(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)), _BACKOFF_MAX_SECONDS)


class Completion(BaseModel):
    """The normalized result of one successful model call."""

    text: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str


def _models_yaml_path() -> Path:
    """Resolve the chain-config path: env override > module override > default."""
    env = os.environ.get("FORGEJUDGE_MODELS_YAML")
    if env:
        return Path(env)
    if models_path is not None:
        return Path(models_path)
    return _DEFAULT_MODELS_YAML


def _load_chains() -> dict[str, list[str]]:
    """Load the full role -> fallback-chain mapping from ``models.yaml``."""
    data = yaml.safe_load(_models_yaml_path().read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{_models_yaml_path()} must be a mapping of role -> [model, ...]")
    return data


def _chain_for(role: Role) -> list[str]:
    """Return the ordered fallback chain for ``role`` (must be non-empty)."""
    chains = _load_chains()
    chain = chains.get(role)
    if not chain:
        raise ValueError(f"no model chain configured for role {role!r} in {_models_yaml_path()}")
    return chain


def complete(
    messages: list[dict],
    *,
    role: Role,
    run_id: str,
    model: str | None = None,
    seed: int | None = None,
) -> Completion:
    """Complete ``messages`` for ``role``, walking that role's fallback chain.

    Each model in the chain is tried in order; the first to return wins. The call's
    cost is added to the ledger for ``run_id``. If every model raises, a
    :class:`RuntimeError` is raised naming the chain that was attempted.

    ``model`` overrides the chain with a single model (used by the leaderboard's
    model-swap comparison — same harness, different model).

    ``seed`` is forwarded to the provider so multi-seed sweeps actually perturb
    sampling (providers that honor ``seed`` give reproducible-but-distinct draws).

    Rate limits (litellm ``RateLimitError`` / 429) are treated as transient: the
    *same* model is retried with bounded exponential backoff (honoring
    ``Retry-After`` when present) up to :data:`_MAX_RATE_LIMIT_ATTEMPTS` before the
    chain advances. Genuine provider/auth/model errors advance immediately.
    """
    chain = [model] if model else _chain_for(role)
    errors: list[str] = []
    for model in chain:
        resp = None
        for attempt in range(1, _MAX_RATE_LIMIT_ATTEMPTS + 1):
            try:
                resp = litellm.completion(model=model, messages=messages, seed=seed)
                break
            except litellm.RateLimitError as exc:
                if attempt < _MAX_RATE_LIMIT_ATTEMPTS:
                    _sleep(_backoff_seconds(exc, attempt))
                    continue
                errors.append(f"{model}: rate-limited after {attempt} attempts: {exc!r}")
            except Exception as exc:  # noqa: BLE001 — hard error: try next model now.
                errors.append(f"{model}: {exc!r}")
                break
        if resp is None:
            continue

        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        tokens_in = getattr(usage, "prompt_tokens", 0) or 0
        tokens_out = getattr(usage, "completion_tokens", 0) or 0
        try:
            cost = float(litellm.completion_cost(resp))
        except Exception:  # noqa: BLE001 — free tiers / unknown models cost nothing.
            cost = 0.0

        _LEDGER[run_id] = _LEDGER.get(run_id, 0.0) + cost
        return Completion(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            model=model,
        )

    raise RuntimeError(
        f"all models failed for role {role!r} (chain {chain}): " + "; ".join(errors)
    )


def run_cost(run_id: str) -> float:
    """Total USD accumulated for ``run_id`` so far (0.0 if unseen)."""
    return _LEDGER.get(run_id, 0.0)


def reset_run(run_id: str) -> None:
    """Forget any accumulated cost for ``run_id``."""
    _LEDGER.pop(run_id, None)
