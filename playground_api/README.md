---
title: ForgeJudge Live Playground (archived)
emoji: ⚖️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# ForgeJudge — guarded live playground

> **Archived (2026-09-28).** The hosted instance is no longer maintained. To run it
> yourself: `docker build -f playground_api/Dockerfile .` (the Dockerfile clones the
> upstream repo; point it at your fork) and set the secrets below.

A rate-limited, fail-closed live runner for the [ForgeJudge](https://github.com/ahmedEid1/forgejudge)
autonomous coding agent. Pre-vetted golden tasks only (no free-form prompt reaches the model),
per-IP rate limit, and a fail-closed daily token budget.

The $0 **replay** playground lives at
[forgejudge.ahmedhobeishy.tech/playground](https://forgejudge.ahmedhobeishy.tech/playground)
(a frozen snapshot); this Space was its guarded live counterpart.

`POST /api/solve {"task_id": "..."}` · `GET /api/tasks`. Set `GROQ_API_KEY` (and optionally
`LANGFUSE_*`, `TURNSTILE_SECRET`, `DAILY_TOKEN_BUDGET`, `RATE_LIMIT_PER_HOUR`) as Space secrets.
