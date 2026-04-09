# JarvisMax Deployment Guide

## Architecture

**Production Server:** VPS1 (77.42.40.146)  
**Repository:** Jarvismax-master  
**Container:** jarvis_core  
**Domain:** jarvis.jarvismaxapp.co.uk

## Automated Deployment (Phase 6)

### GitHub Actions CI/CD

Workflow: `.github/workflows/deploy.yml`

**Triggers:**
- Push to `main` branch
- Manual trigger via GitHub Actions UI

**Process:**
1. Checkout latest code
2. SSH to VPS1
3. Pull latest from `origin/main`
4. Backup current container state
5. Restart container (volume-mounted, no rebuild)
6. Health check validation
7. Rollback on failure

**Required Secrets:**
- `VPS_SSH_KEY` — SSH private key for root@77.42.40.146
- `JARVIS_API_TOKEN` — API token for smoke tests

### Manual Deployment

```bash
# SSH to VPS1
ssh root@77.42.40.146

# Navigate to repo
cd /root/.openclaw/workspace/Jarvismax-master

# Pull latest
git pull origin main

# Restart container
docker restart jarvis_core

# Check health
curl http://localhost:8000/health

# Check logs
docker logs jarvis_core --tail 50
```

## Health Checks

**Endpoint:** `/health`  
**Expected:** `{"status":"ok","service":"jarvismax"}`

**Swagger UI:** `/docs`  
**OpenAPI:** `/openapi.json`

## Rollback Procedure

### Automatic (CI/CD)
If health check fails, workflow automatically:
1. Stops current container
2. Restores last backup image
3. Starts rollback container

### Manual
```bash
# List backups
docker images jarvismax_backup

# Restore specific backup
docker stop jarvis_core
docker run -d --name jarvis_core_rollback \
  --volumes-from jarvis_core \
  jarvismax_backup:YYYYMMDD_HHMMSS

# Verify health
curl http://localhost:8000/health
```

## Monitoring

**Container Status:**
```bash
docker ps --filter name=jarvis_core
```

**Resource Usage:**
```bash
docker stats jarvis_core --no-stream
```

**Logs:**
```bash
# Real-time
docker logs -f jarvis_core

# Last 100 lines
docker logs jarvis_core --tail 100

# Since timestamp
docker logs jarvis_core --since 2026-04-09T00:00:00
```

## Phase 6 Features

✅ **Automated deployment** on push to main  
✅ **Health validation** before marking success  
✅ **Automatic rollback** on failure  
✅ **Container backups** before each deployment  
✅ **Smoke tests** for critical endpoints

## Security

- SSH keys stored in GitHub Secrets (encrypted)
- API tokens never committed to repo
- VPS firewall: SSH (22), HTTP (80), HTTPS (443) only
- Container runs as non-root user `jarvis`

## Troubleshooting

**Deployment fails:**
1. Check GitHub Actions logs
2. SSH to VPS1, check `docker logs jarvis_core`
3. Verify `/root/.openclaw/workspace/Jarvismax-master` is latest
4. Manual rollback if needed

**Health check fails:**
1. Check container status: `docker ps -a | grep jarvis_core`
2. Check logs: `docker logs jarvis_core --tail 100`
3. Verify .env variables loaded
4. Test import: `docker exec jarvis_core python3 -c "from api.main import app; print('OK')"`

**Container won't start:**
1. Check syntax: `docker exec jarvis_core python3 -m py_compile /app/api/main.py`
2. Check dependencies: `docker exec jarvis_core pip list | grep fastapi`
3. Rebuild if needed: `docker build -t jarvismax:latest .`

## Next Phase (Phase 7)

**Business Engine Integration:**
- Wire Tree-of-Thought into opportunity analysis
- Lifelong learning for business patterns
- Multi-project business portfolios
- First autonomous revenue test (€65k/month target)
