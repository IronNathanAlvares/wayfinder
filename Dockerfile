# The corpus is baked into the image rather than mounted.
#
# That is deliberate. A source that has not been checked in a year is excluded
# from retrieval, and `/v1/corpus/health` returns 503 once that happens. Baking
# the corpus in means the image itself has an expiry date and the alarm fires
# against the thing that is actually deployed. A mounted corpus would let
# somebody quietly swap in unreviewed content under a green build.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# Dependencies first, so a corpus edit does not invalidate the layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --extra api --extra llm --no-install-project

COPY src/ src/
RUN uv sync --locked --extra api --extra llm

ENV PATH="/app/.venv/bin:$PATH"

# Paused threads live here. Mount it as a volume: the handoff this system is
# built around lasts days, and a caseworker queue that empties on redeploy is
# the one failure the design cannot have.
VOLUME ["/data"]

EXPOSE 8000

# No --no-model-screen. ADR-0008 measured the deterministic crisis screen at
# 0.167 recall on held-out data, so a container that starts without
# ANTHROPIC_API_KEY set should refuse to start rather than serve a screen that
# does not work.
CMD ["wayfinder", "serve", "--host", "0.0.0.0", "--db", "/data/wayfinder.sqlite"]
