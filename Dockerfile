# ⚠️ DEPRECATED — Ne pas utiliser en CI/prod. ⚠️
#
# Le Dockerfile CANONIQUE est `docker/Dockerfile` (multi-stage, non-root,
# user `jarvis`). Il est référencé par :
#   - .github/workflows/ci.yml      (build CI)
#   - .github/workflows/deploy.yml  (build prod, "canonical non-root")
#   - docker-compose.yml            (service api)
#   - docker-compose.prod.yml
#   - docker-compose.test.yml
#
# Ce fichier-ci est conservé temporairement pour les vieux workflows manuels
# (`docker build .` sans `-f`) mais NE DOIT PAS être étendu. À supprimer
# dans une PR dédiée après confirmation qu'aucun script local ne dépend de lui.
#
# Le TODO historique sur la migration non-root a été résolu dans `docker/Dockerfile`.

FROM python:3.12-slim

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
RUN python -m pip install --upgrade "pip>=25,<26"
RUN python -m pip install --no-cache-dir -r requirements.txt

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
