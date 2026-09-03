# Dockerfile for running on a Runpod pod
FROM runpod/base:1.0.2-cuda1290-ubuntu2204

# Set environment variables
# This ensures Python output is immediately visible in logs
ENV PYTHONUNBUFFERED=1

# Set the working directory
WORKDIR /app

# Install system dependencies if needed
RUN apt-get update --yes && \
    DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends \
        wget \
        curl \
        emacs \
        tmux \
        tree \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency inputs and the standalone package before the application.
COPY requirements.txt /app/
COPY agent-harness /app/agent-harness

# Install Python dependencies
RUN python3 -m pip install --no-cache-dir --upgrade pip && \
    python3 -m pip install --no-cache-dir -r requirements.txt

# Set Hugging Face cache directory
ENV HF_HOME=/app/models
ENV HF_HUB_ENABLE_HF_TRANSFER=0

# Copy application files
COPY . /app

# Verify the pinned agent-harness stack and its local filesystem tool loop at
# image-build time. This check is offline and never requires API credentials.
RUN python3 compatibility/agent_harness_spike.py

# MiniMax credentials are supplied to `docker run`, never baked into the image.
ENV MINIMAX_BASE_URL=https://api.minimax.io/anthropic

# Export an optional runtime .env file before executing the container command.
ENTRYPOINT ["/bin/sh", "-c", "set -a; if [ -f /app/.env ]; then . /app/.env; fi; set +a; exec \"$@\"", "--"]
