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


def complete(messages: list[dict], *, role: Role, run_id: str) -> Completion:
    """Complete ``messages`` for ``role``, walking that role's fallback chain.

    Each model in the chain is tried in order; the first to return wins. The call's
    cost is added to the ledger for ``run_id``. If every model raises, a
    :class:`RuntimeError` is raised naming the chain that was attempted.
    """
    chain = _chain_for(role)
    errors: list[str] = []
    for model in chain:
        try:
            resp = litellm.completion(model=model, messages=messages)
        except Exception as exc:  # noqa: BLE001 — any provider error means "try next".
            errors.append(f"{model}: {exc!r}")
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
