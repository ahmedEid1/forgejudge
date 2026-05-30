---
name: Bug report
about: A reproducible problem in the solver, harness, store, playground, or MCP server
title: "[bug] "
labels: bug
assignees: ""
---

## What happened

A clear description of the bug and what you expected instead.

## Reproduction

Minimal steps. Ideally a command, a task id, or a snippet:

```bash
# e.g.
uv run python -m forgejudge.harness.runner_actions --patch-source gold
```

- Task / instance id (if relevant):
- Model (if a solve/sweep):

## Environment

- ForgeJudge version / commit: <!-- `forgejudge --version` or the git SHA -->
- Install method: <!-- source checkout (`uv sync`) / pip / uvx -->
- Extras installed: <!-- none / harness / mcp / playground -->
- Python & OS:

## Logs / output

<details>
<summary>output</summary>

```
paste relevant output, traceback, or trace link here
```

</details>

## Notes

Anything else — a Langfuse trace link, a failing test, a hypothesis.

> Security vulnerability? Do **not** file it here — see [SECURITY.md](../../SECURITY.md).
