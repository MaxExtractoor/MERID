# Minimal Dockerfile for MERID backend
FROM python:3.11-slim

# Create a non-root user for safety
RUN useradd --create-home --shell /bin/bash merid

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements-dev.txt ./
RUN python -m pip install --upgrade pip && pip install --no-cache-dir -r requirements-dev.txt

# Copy the application
COPY . /app
RUN chown -R merid:merid /app
USER merid

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
