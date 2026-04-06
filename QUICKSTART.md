# 🚀 QUICKSTART — Get JarvisMax Running in 5 Minutes

---

## Prerequisites

- **Docker** (20.10+)
- **Docker Compose** (2.0+)
- **4GB RAM minimum**

**Don't have Docker?**
```bash
# macOS (Homebrew)
brew install docker docker-compose

# Linux (Ubuntu/Debian)
sudo apt-get install docker.io docker-compose

# Check installation
docker --version
docker-compose --version
```

---

## Step 1: Clone Repository

```bash
git clone https://github.com/UniTy01/Jarvismax-master.git
cd Jarvismax-master
```

---

## Step 2: Configure Environment

```bash
# Copy example config
cp .env.example .env

# Edit secrets (IMPORTANT!)
nano .env
```

**Minimum required changes:**
1. Change `POSTGRES_PASSWORD` (line 7)
2. Change `REDIS_PASSWORD` (line 16)
3. Change `JWT_SECRET_KEY` (line 57)

*Optional: Add API keys for Stripe, OpenAI, Vercel, etc.*

---

## Step 3: Start JarvisMax 🚀

```bash
docker-compose up -d
```

**What this does:**
- Creates PostgreSQL database
- Creates Redis cache
- Starts Core OS (6 modules)
- Starts REST API server

**Wait 30 seconds for services to initialize...**

---

## Step 4: Check Status ✅

```bash
# Check running containers
docker-compose ps

# View Core OS logs
docker-compose logs jarvismax-core

# View API logs
docker-compose logs jarvismax-api
```

**Expected output:**
```
✅ JARVISMAX OS — RUNNING (6 modules)
✅ business_engine      running
✅ hexstrike            running
✅ tax_optimizer        running
✅ soc_service          running
✅ data_intelligence    running
✅ agent_marketplace    running
```

---

## Step 5: Access Services 🌐

**Core OS Status:**
```bash
# Using CLI (inside container)
docker-compose exec jarvismax-core python3 -c "
from core.jarvismax_os import JarvisMaxOS
import asyncio
os = JarvisMaxOS()
asyncio.run(os.start())
os.print_status()
"
```

**REST API:**
- **API Docs:** http://localhost:8000/docs
- **Health:** http://localhost:8000/health
- **Status:** http://localhost:8000/status

**Database:**
```bash
# Connect to PostgreSQL
docker-compose exec postgres psql -U jarvismax -d jarvismax

# Run query
SELECT name, status, version FROM modules;
```

**Redis:**
```bash
# Connect to Redis
docker-compose exec redis redis-cli -a redis_secret_2026_CHANGE_ME

# Check keys
KEYS *
```

---

## Step 6: Use CLI Commands 🖥️

```bash
# Make CLI executable
chmod +x jarvismax

# Show revenue dashboard
./jarvismax revenue

# Show status
./jarvismax status

# List modules
./jarvismax modules

# Execute module action
./jarvismax exec business_engine scan_opportunities
```

---

## 🎉 SUCCESS! JarvisMax is Running!

**What's Next?**

### Option A: Launch First MVP (Business Engine)
```bash
# Scan opportunities
./jarvismax exec business_engine scan_opportunities

# Build best opportunity
./jarvismax exec business_engine build_product --opp-id=<id>

# Deploy to Vercel
./jarvismax exec business_engine deploy --product-id=<id>
```

### Option B: Add First SOC Client
```bash
# Create client
./jarvismax exec soc_service add_client \
  --name="Acme Corp" \
  --plan="business" \
  --email="admin@acme.com"

# Start monitoring
./jarvismax exec soc_service start_monitoring --client-id=<id>
```

### Option C: Generate Tax Report
```bash
# Optimize taxes
./jarvismax exec tax_optimizer calculate \
  --revenue=100000 \
  --expenses=30000 \
  --structure=micro
```

---

## 🛑 Stop JarvisMax

```bash
# Stop all services
docker-compose down

# Stop + remove volumes (DELETES DATA!)
docker-compose down -v
```

---

## 🐛 Troubleshooting

### Port Already in Use
```bash
# Change ports in docker-compose.yml
# Default: 5432, 6379, 8000, 8080
# Change to: 15432, 16379, 18000, 18080
```

### Database Not Starting
```bash
# Check logs
docker-compose logs postgres

# Reset database
docker-compose down -v
docker-compose up -d postgres
```

### Redis Connection Error
```bash
# Check Redis password matches .env
docker-compose logs redis
```

### Module Start Failed
```bash
# Check module logs
docker-compose logs jarvismax-core

# Restart module
docker-compose restart jarvismax-core
```

---

## 📚 Next Steps

1. **Read full README.md** for architecture details
2. **Check `/docs`** for module documentation
3. **Explore REST API** at http://localhost:8000/docs
4. **Join Discord** (coming soon) for support

---

## ⚡ Pro Tips

**Faster Development:**
```bash
# Live reload (auto-restart on code changes)
docker-compose up  # Without -d flag

# View all logs in real-time
docker-compose logs -f
```

**Production Deployment:**
1. Change `JARVISMAX_ENV=production` in .env
2. Add real API keys (Stripe, OpenAI, etc.)
3. Use strong passwords
4. Enable HTTPS (Nginx + Let's Encrypt)
5. Setup backups (PostgreSQL + Redis)

**Monitoring:**
```bash
# CPU/Memory usage
docker stats

# Module metrics
curl http://localhost:8000/metrics
```

---

**Need Help?**  
- **GitHub Issues:** https://github.com/UniTy01/Jarvismax-master/issues
- **Discord:** Coming soon
- **Email:** support@jarvismax.ai

---

🚀 **ENJOY JARVISMAX!** 🚀
