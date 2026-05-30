# ForgeJudge developer tasks. Thin wrappers over the `uv` commands CI runs.
# `make help` lists targets. Override the sweep model/seeds: make sweep MODEL=... SEEDS=0,1,2

.DEFAULT_GOAL := help
.PHONY: help sync test test-fast lint format selftest build sweep clean

# --- sweep knobs (override on the CLI) ---
MODEL ?= groq/llama-3.3-70b-versatile
SEEDS ?= 0,1,2

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

sync: ## Install/refresh deps into .venv (uv sync)
	uv sync

test-fast: ## Fast unit tests — no key, no network, no DB
	uv run pytest -m "not slow" -q

test: ## Fast unit tests + full golden validation & mutation hardening
	uv run pytest -m "not slow" -q
	uv run pytest -m "slow and not swebench" -q

lint: ## Ruff lint (what CI enforces; must be clean)
	uv run ruff check

format: ## Ruff format + import/auto fixes
	uv run ruff format
	uv run ruff check --fix

selftest: ## Deterministic harness self-test — grade gold patches (18/18, no key)
	uv run python -m forgejudge.harness.runner_actions --patch-source gold

build: ## Build the sdist + wheel into dist/
	uv build

sweep: ## Run the eval sweep (MODEL=... SEEDS=...) — needs GROQ_API_KEY
	uv run python -m forgejudge.eval.sweep --model $(MODEL) --seeds $(SEEDS)

clean: ## Remove build/test caches and artifacts
	rm -rf dist build .pytest_cache .ruff_cache .coverage htmlcov *.egg-info
