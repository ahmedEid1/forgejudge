# Hugging Face Space (Docker SDK) for the guarded live playground.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# The agent needs the full repo (package + golden set + fixtures), not just the wheel.
RUN git clone --depth 1 https://github.com/ahmedEid1/forgejudge .
RUN pip install --no-cache-dir uv \
    && uv pip install --system -e . \
    && uv pip install --system fastapi "uvicorn[standard]" httpx

ENV PORT=7860
EXPOSE 7860
CMD ["uvicorn", "playground_api.app:app", "--host", "0.0.0.0", "--port", "7860"]
