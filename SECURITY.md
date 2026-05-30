# Security Policy

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
- **The guarded playground** (`playground_api/`) is a public live runner: pre-vetted
  task allowlist only (no free-form prompt reaches the model), per-IP rate limit, a
  fail-closed daily token budget, and optional Cloudflare Turnstile. Auth/budget/rate
  bypasses, prompt-injection that reaches the model, and quota-drain vectors are in scope.
- **Secrets.** API keys and DB URLs come from the environment / `.env` (gitignored).
  Anything that exfiltrates a key or writes to the production leaderboard DB is in scope.

## Reporting a vulnerability

**Do not open a public issue for a security bug.** Instead, report privately via either:

- GitHub **Security Advisories** — <https://github.com/ahmedEid1/forgejudge/security/advisories/new>
  (preferred; lets us collaborate on a fix before disclosure), or
- email **ahmedhobeishy.tools@gmail.com** with subject `ForgeJudge security`.

Please include: affected version/commit, a description and impact, and minimal
reproduction steps or a proof-of-concept.

## What to expect

- **Acknowledgement** within 3 business days.
- An **assessment + planned fix timeline** within 10 business days.
- Coordinated disclosure: we'll agree on a date and credit you (if you wish) in the
  release notes / advisory.

Please give us reasonable time to ship a fix before any public disclosure. Acting in good
faith under this policy — no privacy violations, no data destruction, no service
degradation — is welcome, and we won't pursue action against good-faith research.

## Scope

In scope: this repository (the solver, harness/grader, store, playground API, MCP server,
and CI workflows). Out of scope: third-party services we depend on (Groq, Gemini,
OpenRouter, Langfuse, Neon, Hugging Face, Cloudflare) — report those to the respective
vendor — and vulnerabilities solely in the deliberately-buggy golden *subject* code under
`forgejudge/golden/fixtures/` and `golden/owned/`, which is test input, not shipped code.
