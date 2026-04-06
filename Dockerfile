FROM python:3.11-slim

LABEL maintainer="UniTy <unity@jarvismax.ai>"
LABEL description="JarvisMax — Autonomous AI Operating System"
LABEL version="1.0.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    git \
    curl \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for caching)
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p /root/.jarvismax

# Expose ports
EXPOSE 8000 8080

# Default command (can be overridden in docker-compose)
CMD ["python3", "core/jarvismax_os.py"]
