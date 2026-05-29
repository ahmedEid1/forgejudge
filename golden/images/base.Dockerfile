# Shared, pinned environment for the pure-Python fixture / owned golden tasks.
# Each task pins to this image via `env_image`; per-task images can extend it
# (base -> env -> instance layers) when a task needs extra dependencies.
FROM python:3.12-slim

# Pin the grader's pytest so a task's verdict is reproducible across runs.
RUN pip install --no-cache-dir pytest==9.0.3

WORKDIR /task
