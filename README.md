<div align="center">

# ForgeJudge

**An open, always-on leaderboard and CI gate for autonomous coding agents — every patch runs in a sandbox, every run has a public trace, every regression fails the build.**

</div>

> 🚧 **Status: under active construction.** This README is a stub; the landing page (badges, leaderboard link, playground GIF, one-command quickstart) lands in the launch-polish phase.

## What ForgeJudge is

ForgeJudge is the only open-source autonomous software-engineering agent that **proves its quality in public on every commit**:

- a hand-rolled, single-agent **solver** (localize → repair → validate) over a `$0` LLM router,
- a **deterministic eval harness** that scores every patch by real test transitions (the official SWE-bench grading rule: all `FAIL_TO_PASS` pass **and** all `PASS_TO_PASS` stay green),
- an always-on **public leaderboard** + clickable **per-run traces**,
- a **multi-seed CI regression gate** that fails any change which lowers the resolution rate,

all on a **`$0` / self-hostable stack** against a **contamination-resistant, intrinsically-verifiable golden set**.

**The engineered harness, observability, and gate are the deliverable — not a high resolution rate.** We prove value with a *model-swap comparison*: the score rises with a better model while the harness stays fixed.

## Why

Autonomous coding agents publish a headline number; benchmarks publish a leaderboard; observability tools are bring-your-own-agent. **No project fuses all three.** ForgeJudge does — turning "the demo worked" into a reproducible eval score, an inspectable trace, and a CI gate that blocks regressions.

## License

[MIT](./LICENSE) © 2026 Ahmed Hobeishy. Imports and attributes the MIT-licensed [`swebench`](https://github.com/SWE-bench/SWE-bench) grading harness.

<!-- ci trigger check -->
