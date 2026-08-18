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

# Copy requirements file
COPY requirements.txt /app/

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --pre -r requirements.txt 

# Set Hugging Face cache directory
ENV HF_HOME=/app/models
ENV HF_HUB_ENABLE_HF_TRANSFER=0

# Copy application files
COPY . /app