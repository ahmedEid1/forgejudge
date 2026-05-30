# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
