# JarvisMax — Deployment Guide

**Last Updated**: 2026-04-07  
**Production Instance**: VPS1

---

## Production Domain

### Primary URL
**Domain**: `jarvis.jarvismaxapp.co.uk`  
**Protocol**: HTTPS (TLS via Caddy)  
**Status**: ✅ ACTIVE

### Endpoints

| Endpoint | Description | Status |
|----------|-------------|--------|
| `/health` | Health check | ✅ `{"status":"ok","service":"jarvismax"}` |
| `/docs` | API documentation (Swagger UI) | ✅ Available |
| `/redoc` | API documentation (ReDoc) | ✅ Available |
| `/api/v1/*` | Core API routes | ✅ Available |
| `/api/v2/*` | Enhanced API routes | ✅ Available |
| `/api/v3/*` | Canonical missions API | ✅ Available |

### Health Check
```bash
curl https://jarvis.jarvismaxapp.co.uk/health
# Response: {"status":"ok","service":"jarvismax"}
```

---

## Infrastructure

### Reverse Proxy: Caddy
**Config file**: `Caddyfile` (project root)  
**Status**: ✅ Configured, do not modify without coordination

Caddy handles:
- HTTPS/TLS termination
- Domain routing to backend (API_HOST:API_PORT)
- Certificate management (automatic Let's Encrypt)

### Backend API Server
**Host**: `0.0.0.0` (all interfaces)  
**Port**: `8000`  
**Framework**: FastAPI  
**Entry point**: `api/main.py`

### Environment Configuration
**File**: `.env` (project root)  
**Key variables**:
```bash
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
DRY_RUN=true

# Database
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=jarvis
POSTGRES_USER=jarvis

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# Qdrant (Vector DB)
QDRANT_HOST=qdrant
QDRANT_PORT=6333

# LLM Provider
ANTHROPIC_MODEL=claude-haiku-4-5-20251001
MODEL_STRATEGY=anthropic
```

**Note**: No explicit `DOMAIN` or `BASE_URL` variable required.  
Caddy reverse proxy handles domain routing transparently.

---

## Deployment Topology

```
Internet
   ↓
jarvis.jarvismaxapp.co.uk (DNS)
   ↓
Caddy (HTTPS :443) ← Caddyfile
   ↓
FastAPI Backend (HTTP :8000) ← api/main.py
   ↓
┌────────────────────────────────────┐
│ Services (docker-compose.yml)      │
│ - postgres:5432                    │
│ - redis:6379                       │
│ - qdrant:6333                      │
│ - n8n:5678 (optional)             │
└────────────────────────────────────┘
```

---

## Monitoring & Logs

### Application Logs
**Directory**: `logs/`  
**Format**: JSON structured logs (structlog)  
**Level**: INFO (production), DEBUG (development)

### Health Monitoring
```bash
# Quick health check
curl -f https://jarvis.jarvismaxapp.co.uk/health || echo "DOWN"

# Full system status
curl https://jarvis.jarvismaxapp.co.uk/api/v1/system/status
```

### Observability Endpoints
- `/api/v1/observability/events` - Cognitive event journal
- `/api/v1/metrics` - System metrics
- `/api/v1/monitoring/missions` - Mission health

---

## Deployment Checklist

### Pre-Deployment
- [ ] Review `.env` for sensitive credentials
- [ ] Verify database migrations applied
- [ ] Run test suite: `pytest tests/ -v`
- [ ] Check protected paths unchanged (ARCHITECTURE.md)

### Deployment
- [ ] Pull latest code: `git pull origin main`
- [ ] Install dependencies: `pip install -r requirements.txt`
- [ ] Restart services: `docker-compose restart`
- [ ] Verify health: `curl https://jarvis.jarvismaxapp.co.uk/health`

### Post-Deployment
- [ ] Monitor logs: `tail -f logs/jarvismax.log`
- [ ] Check critical missions succeed
- [ ] Verify LLM provider connectivity
- [ ] Test API endpoints with smoke tests

---

## Rollback Procedure

If deployment fails:
```bash
# 1. Checkout previous stable version
git log --oneline -10  # find last stable commit
git checkout <commit-hash>

# 2. Restart services
docker-compose restart

# 3. Verify health
curl https://jarvis.jarvismaxapp.co.uk/health

# 4. Review logs for errors
tail -100 logs/jarvismax.log
```

---

## Security Notes

### Protected Paths
Never auto-modify these files (see ARCHITECTURE.md):
- `core/meta_orchestrator.py`
- `core/tool_executor.py`
- `core/policy_engine.py`
- `api/auth.py`
- `api/main.py`
- `config/settings.py`
- `.env`
- `docker-compose.yml`

### Secrets Management
- All API keys stored in `.env`
- Never commit `.env` to git (in `.gitignore`)
- Rotate credentials quarterly
- Use `JARVIS_API_TOKEN` for authenticated API calls

### DRY_RUN Mode
Production runs with `DRY_RUN=true` by default:
- Tool execution simulated (no actual changes)
- Safe for testing and validation
- Set `DRY_RUN=false` only when explicitly approved

---

## Contact & Support

**Production Instance**: VPS1  
**Managed By**: JarvisMax Team  
**Incident Response**: Check logs first, then review CANONICAL_COMPONENTS.md for architecture

**Documentation**:
- Architecture: `ARCHITECTURE.md`
- Changelog: `CHANGELOG.md`
- Components: `CANONICAL_COMPONENTS.md`
- This file: `DEPLOYMENT.md`

---

**End of Deployment Guide**
