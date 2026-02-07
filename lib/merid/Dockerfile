# Multi-stage Dockerfile for MERID backend (hardened)

# Builder: install build dependencies and Python packages into a target dir
FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /install
COPY requirements-dev.txt ./
RUN python -m pip install --upgrade pip
RUN python -m pip install --no-cache-dir --target /install -r requirements-dev.txt

# Final: minimal runtime image with non-root user
FROM python:3.11-slim

# Create a non-root user for safety
RUN useradd --create-home --shell /bin/bash merid

WORKDIR /app

# Copy only the installed packages and the application
COPY --from=builder /install /app/.venv
COPY . /app
RUN chown -R merid:merid /app

# Use a non-root user
USER merid

ENV PYTHONPATH=/app/.venv
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Lightweight healthcheck
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
