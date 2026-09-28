# Security Policy

> **This project is archived (2026-09-28) and unsupported.** There will be no fixes,
> advisories or releases. The threat model below still describes the code, and it
> matters to anyone running a fork: model-authored patches are hostile input.

ForgeJudge runs **untrusted, model-authored code**: the solver applies an LLM's patch
and the harness executes the resulting test suite to grade it. We take the safety of
that pipeline seriously and welcome responsible disclosure.

## Threat model (in brief)

- **Sandboxing.** Candidate patches and tests are meant to run only inside a disposable,
  isolated environment — a GitHub Actions ephemeral VM in CI, or a throwaway local tree.
  Never grade an unreviewed third-party patch on a machine with credentials or data you
  care about. Treat every model-authored patch as hostile input.
- **Cheat-resistance.** The grader restores the canonical test files before scoring and
  counts a *skipped* `FAIL_TO_PASS` as not-passed, so a patch can't neuter or skip its
  way to a green verdict. Bypasses of this are in scope.
- **The guarded playground** (`playground_api/`) was a public live runner (no longer
  maintained; self-host it from the repo): pre-vetted
  task allowlist only (no free-form prompt reaches the model), per-IP rate limit, a
  fail-closed daily token budget, and optional Cloudflare Turnstile. Auth/budget/rate
  bypasses, prompt-injection that reaches the model, and quota-drain vectors are in scope.
- **Secrets.** API keys and DB URLs come from the environment / `.env` (gitignored).
  Anything that exfiltrates a key or writes to a deployment's leaderboard DB is in scope.

## Reporting a vulnerability

Because the project is archived, reports are not acted on. If you run a fork, handle
reports there. For the historical record, reports went privately via either:

- GitHub **Security Advisories** — <https://github.com/ahmedEid1/forgejudge/security/advisories/new>
  (preferred; lets us collaborate on a fix before disclosure), or
- email **ahmedhobeishy.tools@gmail.com** with subject `ForgeJudge security`.

Reports included: affected version/commit, a description and impact, and minimal
reproduction steps or a proof-of-concept.

## What to expect (historical)

While the project was maintained, reports were acknowledged within 3 business days and
assessed within 10, with coordinated disclosure and credit in the release notes or
advisory. Since the archive (2026-09-28) no report is answered or fixed; report issues
to the fork you use. Good-faith research — no privacy violations, no data destruction,
no service degradation — is still welcome and will not be pursued.

## Scope

In scope: this repository (the solver, harness/grader, store, playground API, MCP server,
and CI workflows). Out of scope: third-party services we depend on (Groq, Gemini,
OpenRouter, Langfuse, Neon, Hugging Face, Cloudflare) — report those to the respective
vendor — and vulnerabilities solely in the deliberately-buggy golden *subject* code under
`forgejudge/golden/fixtures/` and `golden/owned/`, which is test input, not shipped code.
