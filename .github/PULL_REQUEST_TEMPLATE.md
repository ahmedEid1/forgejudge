## What & why

<!-- What does this change, and why? Link any issue: Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Golden task added / changed
- [ ] Docs / tooling / CI
- [ ] Refactor (no behaviour change)

## Checklist

<!-- See CONTRIBUTING.md for the full marker map and dev loop. -->

- [ ] `uv run ruff check` is clean
- [ ] `uv run pytest -m "not slow"` passes
- [ ] If grading / the solver / a golden task changed:
      `uv run pytest -m "slow and not swebench"` passes
- [ ] New behaviour is covered by a test
- [ ] `CHANGELOG.md` updated under **Unreleased** (for user-facing changes)

## Golden tasks (if applicable)

- [ ] Rebuilt with `uv run python -m forgejudge.golden.build_dataset`
- [ ] Mutation-hardened with `uv run python -m forgejudge.golden.harden` (no `weak` tasks)
- [ ] Regenerated `golden/dataset.jsonl` / `golden/solutions.jsonl` committed
- [ ] `created_at` postdates the model cutoff (2026-01-31)

## Notes for reviewers

<!-- Anything that needs context: trade-offs, follow-ups, a trace link, screenshots. -->
