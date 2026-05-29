---
title: ForgeJudge Live Playground
emoji: ⚖️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# ForgeJudge — guarded live playground

A rate-limited, fail-closed live runner for the [ForgeJudge](https://github.com/ahmedEid1/forgejudge)
autonomous coding agent. Pre-vetted golden tasks only (no free-form prompt reaches the model),
per-IP rate limit, and a fail-closed daily token budget.

The always-on, $0 **replay** playground lives at
[forgejudge.pages.dev/playground](https://forgejudge.pages.dev/playground); this Space is its
guarded live counterpart.

`POST /api/solve {"task_id": "..."}` · `GET /api/tasks`. Set `GROQ_API_KEY` (and optionally
`LANGFUSE_*`, `TURNSTILE_SECRET`, `DAILY_TOKEN_BUDGET`, `RATE_LIMIT_PER_HOUR`) as Space secrets.
