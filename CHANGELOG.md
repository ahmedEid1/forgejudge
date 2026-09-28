# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Nightly `sweep`: Groq retired `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`
  from its free tier on 2026-08-16, so every run on them errored and the publish gate
  skipped them each night. The sweep now covers `gpt-oss-120b`, `gpt-oss-20b` and
  `qwen3.8-27b`, and the router chains in `models.yaml` no longer route through the
  retired models.
- Errored sweep runs now carry the exception text, the sweep log prints the most
  common causes, and the publish gate reports a 100%-error sweep as a hard failure
  (retired model / bad key) instead of "likely rate-limited".
- `sweep.yml` uploads the raw runs even when a later step fails, and a failed
  Cloudflare Pages deploy now explains how to rotate `CLOUDFLARE_API_TOKEN`.
- `tests/test_smoke.py` no longer hardcodes the version string (#9).

### Added
- Contributor + onboarding surfaces: `CONTRIBUTING.md`, `SECURITY.md`, a `Makefile`,
  `.python-version`, GitHub issue/PR templates, and Dependabot config.
- README Install section documenting the `pip install forgejudge` library + CLI path,
  the `uvx --from "forgejudge[mcp]" forgejudge mcp` zero-install MCP server, and the
  `harness` / `mcp` / `playground` optional extras.

## [0.1.0] - 2026-05-29

Initial release.

### Added
- **Solver** — hand-rolled single-agent `localize → repair → validate` loop: BM25
  localization, a role-based LiteLLM router with free-tier fallback + cost accounting,
  a syntax edit-gate, a critic pre-filter, and a cost/step budget with autosubmit.
- **Harness** — deterministic execution-as-judge `grade()` encoding the SWE-bench
  `RESOLVED_FULL` rule, verified equivalent to `swebench.harness.grading` in CI and
  deliberately stricter on a *skipped* `FAIL_TO_PASS`; cheat-resistant (canonical test
  files restored before grading), with a sandboxed runner.
- **Golden set** — 18 intrinsically-verifiable, mutation-hardened tasks (15 post-cutoff
  fixtures + 3 mined from the author's own repos), with a fixture-contract loader,
  dataset builder, and mutation hardener.
- **Observability** — OpenTelemetry GenAI spans exported to Langfuse Cloud (optionally
  Phoenix); every run is a clickable public trace.
- **Run store** — Neon (Postgres + pgvector) run store + leaderboard query.
- **CI gates** — a deterministic gold-integrity gate and a multi-seed regression gate
  (small-sample CI) wired into GitHub Actions, plus a scheduled leaderboard sweep.
- **Surfaces** — `forgejudge` CLI (`selftest` / `mcp` / `info`), an MCP server, and a
  guarded live playground; optional `harness` / `mcp` / `playground` extras.

[Unreleased]: https://github.com/ahmedEid1/forgejudge/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ahmedEid1/forgejudge/releases/tag/v0.1.0
