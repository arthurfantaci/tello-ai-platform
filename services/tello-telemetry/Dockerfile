# Stage 1: Build dependencies with uv
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

WORKDIR /app

# Copy workspace root files for dependency resolution
COPY pyproject.toml uv.lock ./

# Copy only the packages needed by tello-telemetry
COPY packages/tello-core/ packages/tello-core/
COPY services/tello-telemetry/ services/tello-telemetry/

# Install production dependencies only
RUN uv sync --package tello-telemetry --frozen --no-dev

# Stage 2: Slim runtime image
FROM python:3.13-slim-bookworm

WORKDIR /app

# Install curl for Docker healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY packages/tello-core/src/ packages/tello-core/src/
COPY services/tello-telemetry/src/ services/tello-telemetry/src/

# Activate venv
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8200

ENTRYPOINT ["python", "-m", "tello_telemetry.server", "--transport", "streamable-http", "--port", "8200"]
