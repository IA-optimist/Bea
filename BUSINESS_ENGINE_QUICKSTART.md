# BUSINESS ENGINE - QUICK START GUIDE

**Status**: ✅ OPERATIONAL  
**Mode**: TEST (Phase 1 - no Stripe required)  
**Date**: 2026-04-07

---

## 🎯 WHAT'S ACTIVATED

The Jarvismax Business Engine is now fully operational with:

- **8 Business Agents** (SaaS, Venture, Offer, Workflow, etc.)
- **5 Business Actions** (MVP spec, research, offer package, etc.)
- **3 Sample Projects** created with complete specifications
- **REST API** for business operations at `/api/v3/business-actions`

---

## 🚀 QUICK START

### 1. Test the System

```bash
cd /root/Jarvismax-master
bash scripts/test_business_engine.sh
```

Expected output: `✅ BUSINESS ENGINE: OPERATIONAL`

### 2. List Available Business Actions

```bash
TOKEN=$(grep "^JARVIS_API_TOKEN=" .env | cut -d'=' -f2)
curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v3/business-actions | jq '.data[].action_id'
```

Output:
- `venture.research_workspace` - Market research
- `offer.package` - Pricing & positioning
- `workflow.blueprint` - Automation design
- `saas.mvp_spec` - SaaS MVP specification
- `workflow.n8n_trigger` - Workflow automation (requires approval)

### 3. View Existing Projects

```bash
ls -la workspace/business/
```

Projects created:
1. **devtools-api-analytics** - Developer tools SaaS
2. **cli-productivity-tools** - CLI tools venture research
3. **apiwatch** - API monitoring SaaS (complete MVP spec)

---

## 📋 CREATE A NEW SAAS PROJECT

### Generate MVP Specification

```bash
TOKEN=$(grep "^JARVIS_API_TOKEN=" .env | cut -d'=' -f2)

curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "saas.mvp_spec",
    "agent_output": {
      "blueprints": [{
        "product_name": "YourSaaSName",
        "tagline": "One-line value proposition",
        "problem": "The problem you solve",
        "solution": "How you solve it",
        "target_user": "Your ideal customer",
        "mvp_scope": "Core features for MVP",
        "features": [
          {
            "id": "f1",
            "name": "Core Feature",
            "description": "What it does",
            "priority": "must",
            "effort": "m"
          }
        ],
        "tech_stack": {
          "frontend": "Next.js 14 + Tailwind",
          "backend": "FastAPI",
          "database": "PostgreSQL",
          "hosting": "Vercel + Railway"
        },
        "monetization": "Pricing strategy",
        "build_time_weeks": 8
      }]
    },
    "project_name": "your_project_name"
  }' \
  http://localhost:8000/api/v3/business-actions/execute
```

### View Generated Files

```bash
# Projects are created in workspace/business/
ls workspace/business/your-project-name-*/
```

Generated files:
- `README.md` - Project overview
- `mvp-spec.json` - Complete specification
- `features.md` - Feature breakdown
- `user-stories.md` - User stories
- `tech-stack.md` - Technical choices
- `roadmap.md` - Development timeline

---

## 🔧 BUSINESS ACTIONS REFERENCE

### 1. Venture Research (Market Analysis)

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "venture.research_workspace",
    "agent_output": {
      "sector": "your_target_market",
      "focus": "specific niche",
      "budget": 0,
      "timeline": "14days"
    },
    "project_name": "venture_research_project"
  }' \
  http://localhost:8000/api/v3/business-actions/execute
```

### 2. Offer Package (Pricing & Positioning)

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "offer.package",
    "agent_output": {
      "product": "Your product name",
      "target": "Target audience",
      "pricing_model": "subscription"
    },
    "project_name": "offer_design_project"
  }' \
  http://localhost:8000/api/v3/business-actions/execute
```

### 3. Workflow Blueprint (Automation Design)

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "workflow.blueprint",
    "agent_output": {
      "process": "Process to automate",
      "tools": ["n8n", "zapier"]
    },
    "project_name": "workflow_automation"
  }' \
  http://localhost:8000/api/v3/business-actions/execute
```

---

## 📊 CONFIGURATION

### Current Settings (.env)

```bash
BUSINESS_ENGINE_ENABLED=true
BUSINESS_MODE=TEST
REVENUE_TARGET_MONTHLY=5000
```

### Mode Explanation

- **TEST Mode** (current): Generate specs, no payment processing
- **PRODUCTION Mode** (Phase 2): Requires `STRIPE_API_KEY`

To activate production mode later:
```bash
# Add to .env:
STRIPE_API_KEY=sk_live_your_stripe_key
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
BUSINESS_MODE=PRODUCTION
```

---

## 🎓 EXAMPLE: COMPLETE SAAS PIPELINE

**Goal**: Create a micro-SaaS from research to MVP spec

```bash
TOKEN=$(grep "^JARVIS_API_TOKEN=" .env | cut -d'=' -f2)

# Step 1: Research the market
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "venture.research_workspace",
    "agent_output": {"sector": "developer_tools"},
    "project_name": "devtools_research"
  }' http://localhost:8000/api/v3/business-actions/execute

# Step 2: Design the offer
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "offer.package",
    "agent_output": {
      "product": "API Monitor",
      "target": "solo developers"
    },
    "project_name": "api_monitor_offer"
  }' http://localhost:8000/api/v3/business-actions/execute

# Step 3: Generate MVP spec
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "action_id": "saas.mvp_spec",
    "agent_output": {
      "blueprints": [{
        "product_name": "API Monitor",
        "tagline": "Monitor your APIs effortlessly",
        "problem": "API monitoring is expensive",
        "solution": "Affordable API analytics",
        "target_user": "Indie developers",
        "mvp_scope": "Basic monitoring + alerts"
      }]
    },
    "project_name": "api_monitor"
  }' http://localhost:8000/api/v3/business-actions/execute
```

---

## 📈 REVENUE ROADMAP

### Phase 1: DONE ✅
- Business Engine activated
- Sample projects created
- API tested and validated

### Phase 2: Week 1-2 (Build MVP)
- Implement APIWatch core features
- Deploy frontend (Vercel) + backend (Railway)
- Create landing page

### Phase 3: Week 3-4 (Launch)
- Integrate Stripe
- Beta launch (20 users)
- ProductHunt submission

### Phase 4: Month 1-2 (Scale)
- Target: 5 paying customers = 45 EUR MRR
- Launch 2nd micro-SaaS
- Automate marketing via n8n

### Phase 5: Month 3+ (Growth)
- 6 micro-SaaS projects
- 30 total customers
- Target: 270 EUR MRR

---

## 🛠️ TROUBLESHOOTING

### Test the API
```bash
curl http://localhost:8000/health
# Expected: {"status": "ok"}
```

### Check Docker Status
```bash
docker ps --filter "name=jarvis"
# All containers should show (healthy)
```

### View Logs
```bash
docker logs jarvis_core --tail 100 | grep -i business
```

### Restart if Needed
```bash
docker-compose restart jarvis_core
```

---

## 📚 RESOURCES

### Documentation
- Full report: `workspace/business_reports/BUSINESS_ENGINE_ACTIVATED.md`
- Summary: `workspace/business_reports/ACTIVATION_SUMMARY.txt`

### Sample Projects
- APIWatch: `workspace/business/apiwatch-20260407-1929/`
- DevTools: `workspace/business/devtools-api-analytics-20260407-1926/`

### API Reference
- Swagger docs: `http://localhost:8000/docs`
- Business actions: `http://localhost:8000/api/v3/business-actions`

---

## 🎯 NEXT STEPS

1. **Review APIWatch MVP**: `cat workspace/business/apiwatch-*/README.md`
2. **Start building**: Implement core features (API keys, logging, dashboard)
3. **Deploy**: Setup Vercel + Railway
4. **Activate payments**: Add Stripe keys to `.env` (Phase 3)
5. **Launch**: ProductHunt + dev communities

---

## 💡 TIPS

- **Zero marketing budget**: Focus on SEO, ProductHunt, dev communities
- **Bootstrap mode**: Build first, monetize later
- **Solo-buildable**: All specs designed for single developer
- **Fast iteration**: 6-8 week MVP timeline
- **Freemium model**: 9 EUR/month Pro tier

---

**Questions or Issues?**

Run the test suite:
```bash
bash scripts/test_business_engine.sh
```

Check container health:
```bash
docker ps --filter "name=jarvis" --format "table {{.Names}}\t{{.Status}}"
```

---

Generated: 2026-04-07 19:30 UTC  
Status: ✅ OPERATIONAL  
Mode: TEST (Phase 1)
