FROM python:3.11-slim

# TODO(security): passer en USER non-root. Nécessite une migration coordonnée :
#   1. useradd -m jarvis && chown -R jarvis /app /home/jarvis/.jarvismax
#   2. Adapter le volume mount (docker-compose.yml: ~/.jarvismax:/root/.jarvismax
#      → ~/.jarvismax:/home/jarvis/.jarvismax)
#   3. Adapter les scripts qui assument /root (start_with_deps.sh, etc.)
# Laisser en root pour l'instant afin de ne pas casser les déploiements existants.

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip>=26.0
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /root/.jarvismax/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/api/v2/health || exit 1

# Run the application
CMD ["python", "main.py"]
