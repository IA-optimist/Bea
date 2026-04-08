# Phase 3 — Business Engine Activation Plan

**Date:** 2026-04-08  
**Status:** INFRASTRUCTURE READY — ACTIVATION REQUIRED  
**Goal:** €65k/month autonomous revenue (6 pillars)

---

## Current State Assessment

### ✅ EXISTING INFRASTRUCTURE:

**Business Layer:**
- `core/business_pipeline.py` (721 LOC) — Lead/prospect CRM
- `core/business_actions.py` — Business action primitives
- `core/orchestration/business_missions.py` (402 LOC) — Mission templates

**Finance Layer:**
- `core/finance/revenue_tracker.py` (135 LOC) — MRR/ARR metrics
- `core/finance/invoice_manager.py` (142 LOC) — Invoice automation
- `core/finance/finance_memory.py` (213 LOC) — Financial memory

**SaaS Layer:**
- `business/saas/agent.py` (177 LOC) — SaaS reasoning agent
- `business/saas/schema.py` (245 LOC) — SaaS data models
- `business/automation/opportunity_scanner.py` (535 LOC) — Market scanner

**API Layer:**
- `api/routes/finance.py` (258 LOC) — Stripe integration
- `api/routes/business_actions.py` — Business actions API
- `api/routes/business_artifacts.py` — Artifacts management

**Total Business Code:** ~2,900 LOC (already written!)

---

## Phase 3 Roadmap

### **PILLAR 1: SaaS Generator (Priority 1)**

**Objective:** Autonomous SaaS opportunity → validated MVP → deployed product

#### **P3.1 — Opportunity Scanner Automation**
**Goal:** Daily cron job scanning Product Hunt, Reddit, HN for SaaS ideas

**Tasks:**
1. Create cron job: `daily_opportunity_scan.py`
   - Run `opportunity_scanner.py` at 06:00 UTC
   - Filter: `total_score > 70`, `monetization_score > 60`
   - Store top 10 in PostgreSQL `opportunities` table
   
2. Add API endpoint: `POST /api/v3/business/opportunities/scan`
   - Trigger manual scan
   - Return scored opportunities

3. Add webhook: Telegram notification for score > 85
   - Format: "🎯 HIGH-VALUE OPPORTUNITY: [title] (score: XX/100)"
   - Include: demand, competition, feasibility, monetization scores

**Deliverables:**
- [ ] `cron/daily_opportunity_scan.py` (cron job)
- [ ] `models/opportunity.py` (PostgreSQL schema)
- [ ] API route: `/api/v3/business/opportunities/*`
- [ ] Telegram notification integration

**Duration:** 3-4h  
**Cognition:** Use confidence scoring for opportunity validation

---

#### **P3.2 — Feasibility Analysis (Cognition-Powered)**
**Goal:** Autonomous technical feasibility assessment for top opportunities

**Tasks:**
1. Create `core/business/feasibility_analyzer.py`
   - Input: Opportunity (title, description, scores)
   - Output: Technical feasibility report
     - Tech stack recommendation
     - MVP scope (features list)
     - Time estimate (hours)
     - Complexity score (1-10)
     - Dependencies (APIs, services)
   
2. Integrate with `CognitionOrchestrator`
   - Mission type: `business.analyze_feasibility`
   - Use Tree-of-Thought for multi-path analysis
   - Confidence threshold: 0.8 (high confidence required)

3. Store analysis in PostgreSQL: `opportunity_analyses` table
   - Link to opportunity_id
   - Include confidence score, reasoning, recommendations

**Deliverables:**
- [ ] `core/business/feasibility_analyzer.py` (200-300 LOC)
- [ ] Integration with cognition wrapper
- [ ] PostgreSQL schema: `opportunity_analyses`
- [ ] API route: `POST /api/v3/business/opportunities/{id}/analyze`

**Duration:** 4-5h  
**Cognition:** Core use case for AGI reasoning

---

#### **P3.3 — MVP Generator (Code Automation)**
**Goal:** Auto-generate MVP codebase from feasibility report

**Tasks:**
1. Create `core/business/mvp_generator.py`
   - Input: Feasibility report (tech stack, features, scope)
   - Output: Full codebase (FastAPI + React/Next.js)
     - Backend: FastAPI boilerplate + CRUD + auth
     - Frontend: React landing page + dashboard
     - Database: PostgreSQL migrations
     - Docker: Dockerfile + docker-compose.yml
     - Deployment: GitHub Actions CI/CD

2. Code templates library: `business/templates/mvp/*`
   - `fastapi_base/` — FastAPI starter
   - `react_landing/` — Marketing site
   - `dashboard/` — Admin panel
   - `auth/` — JWT auth system

3. Integration with `delegate_task`
   - Use subagent for file generation (avoid host sync issues)
   - Commit to new GitHub repo (auto-create via gh CLI)

**Deliverables:**
- [ ] `core/business/mvp_generator.py` (400-500 LOC)
- [ ] Code templates: `business/templates/mvp/*` (~2000 LOC)
- [ ] GitHub repo creation automation
- [ ] API route: `POST /api/v3/business/opportunities/{id}/generate-mvp`

**Duration:** 8-10h  
**Cognition:** Use for architecture decisions

---

#### **P3.4 — Deployment Automation**
**Goal:** Auto-deploy generated MVPs to production VPS

**Tasks:**
1. Create `core/business/deploy_manager.py`
   - Input: GitHub repo URL
   - Actions:
     - Clone repo on VPS
     - Build Docker image
     - Deploy with Caddy reverse proxy
     - Generate subdomain: `<project>.jarvismaxapp.co.uk`
     - SSL cert via Caddy auto-HTTPS

2. Health monitoring
   - Ping deployed app every 5min
   - Store uptime in PostgreSQL
   - Alert on downtime (Telegram)

3. Revenue tracking integration
   - Link deployed MVPs to `revenue_tracker`
   - Track signups, conversions, MRR

**Deliverables:**
- [ ] `core/business/deploy_manager.py` (300-400 LOC)
- [ ] Caddy dynamic config generator
- [ ] Health check cron job
- [ ] API route: `POST /api/v3/business/mvps/{id}/deploy`

**Duration:** 5-6h  
**Cognition:** Not required (mechanical task)

---

### **PILLAR 2: Bug Bounty Automation (Priority 2)**

**Objective:** Autonomous vulnerability scanning + HackerOne submissions

#### **P3.5 — HackerOne Integration**
**Goal:** Auto-submit vulnerability reports via HackerOne API

**Tasks:**
1. Create `tools/integrations/hackerone_tool.py`
   - Submit report (title, description, severity, proof)
   - List programs (eligibility check)
   - Track submissions (status, bounty awarded)

2. Vulnerability templates: `business/templates/vulnerabilities/*`
   - XSS, SQLi, CSRF, SSRF, etc.
   - Structured format (CVSS, impact, remediation)

3. Store submissions in PostgreSQL: `bug_bounty_submissions`
   - Link to discovered vulnerability
   - Track bounty status (pending/paid/rejected)

**Deliverables:**
- [ ] `tools/integrations/hackerone_tool.py` (200-300 LOC)
- [ ] Vulnerability templates
- [ ] PostgreSQL schema: `bug_bounty_submissions`
- [ ] API route: `POST /api/v3/bug-bounty/submit`

**Duration:** 4-5h  
**Cognition:** Use for report quality scoring

---

#### **P3.6 — Vulnerability Scanner (Scheduled)**
**Goal:** Daily automated scanning of public bug bounty programs

**Tasks:**
1. Create `business/automation/vuln_scanner.py`
   - Scan targets from HackerOne program list
   - Run common checks (OWASP Top 10)
   - Filter false positives (confidence > 0.7)

2. Cron job: `daily_vuln_scan.py`
   - Run at 02:00 UTC (off-peak)
   - Store findings in PostgreSQL
   - Trigger HackerOne submission for high-confidence findings

3. Legal compliance check
   - Only scan authorized programs
   - Respect scope/out-of-scope rules
   - Rate limiting (max 1 req/sec)

**Deliverables:**
- [ ] `business/automation/vuln_scanner.py` (500-600 LOC)
- [ ] Cron job: `cron/daily_vuln_scan.py`
- [ ] Legal compliance checker
- [ ] PostgreSQL schema: `vulnerability_findings`

**Duration:** 8-10h  
**Cognition:** Use for false positive filtering

---

### **PILLAR 3: Blue Team (NIS2 Compliance) (Priority 3)**

**Objective:** SOC-as-a-Service for EU companies (NIS2 compliance)

#### **P3.7 — Security Audit Scheduler**
**Goal:** Weekly automated security audits for client infrastructure

**Tasks:**
1. Create `business/automation/security_audit.py`
   - Run CIS benchmarks (Linux, Docker, K8s)
   - Check NIS2 compliance (GDPR, logging, incident response)
   - Generate PDF report (compliant with auditors)

2. Client onboarding API
   - Add client (company name, infra details)
   - Store SSH keys (encrypted in vault)
   - Schedule audit cron job

3. Incident response automation
   - Detect anomalies (failed logins, suspicious processes)
   - Auto-remediate (block IPs, kill processes)
   - Alert client (email + Telegram)

**Deliverables:**
- [ ] `business/automation/security_audit.py` (600-700 LOC)
- [ ] PDF report generator (NIS2 compliant)
- [ ] Client onboarding API
- [ ] Incident response automation

**Duration:** 10-12h  
**Cognition:** Use for anomaly detection

---

### **PILLAR 4-6: Deferred (Phase 5)**

**Pillar 4: Compta/Fiscalité**
- Invoice automation (already exists: `invoice_manager.py`)
- Tax compliance (France/EU)
- Financial reporting

**Pillar 5: Freelance Automation**
- Upwork/Fiverr scrapers
- Bid generator (cognition-powered)
- Delivery automation

**Pillar 6: Crypto Trading**
- Legal research required (France regulations)
- Risk management mandatory
- Deferred until pillars 1-3 profitable

---

## Success Metrics

### **Phase 3 Goals:**

**Technical:**
- [ ] Opportunity scanner: 1 scan/day, top 10 stored
- [ ] Feasibility analyzer: 3-5 analyses/week (high-score opportunities)
- [ ] MVP generator: 1 MVP generated/week
- [ ] Deployment: 2-3 MVPs deployed/month
- [ ] Bug bounty: 10-20 submissions/month
- [ ] Blue team: 2-3 clients onboarded

**Revenue (6-month target):**
- SaaS MVPs: €500-2000/month (2-3 MVPs × €250-500/MRR each)
- Bug bounty: €1000-3000/month (10-20 submissions × €100-150 avg)
- Blue team: €2000-5000/month (2-3 clients × €1000-2000/month each)

**Total Phase 3:** €3,500-10,000/month (milestone: €5k/month in 6 months)

**Phase 5 Target:** €65k/month (all 6 pillars mature)

---

## Implementation Priority

### **Week 1-2: SaaS Generator Core**
1. P3.1 — Opportunity scanner automation (3-4h)
2. P3.2 — Feasibility analyzer (4-5h)
3. P3.3 — MVP generator (8-10h)
4. P3.4 — Deployment automation (5-6h)

**Total:** 20-25h  
**Deliverables:** End-to-end SaaS generation pipeline operational

### **Week 3-4: Bug Bounty Automation**
1. P3.5 — HackerOne integration (4-5h)
2. P3.6 — Vulnerability scanner (8-10h)

**Total:** 12-15h  
**Deliverables:** Automated bug bounty submissions running

### **Week 5-6: Blue Team MVP**
1. P3.7 — Security audit scheduler (10-12h)

**Total:** 10-12h  
**Deliverables:** First SOC-as-a-Service client onboarded

---

## Risk Mitigation

**Technical Risks:**
- MVP generation quality → Use cognition for validation
- Deployment failures → Health checks + rollback automation
- False positives (bug bounty) → Confidence threshold 0.7+

**Legal Risks:**
- Bug bounty: Only authorized programs (HackerOne scope check)
- Blue team: Client consent required (written agreement)
- SaaS: GDPR compliance (privacy policy, data processing)

**Financial Risks:**
- Low conversion (MVPs) → A/B test landing pages
- Rejected bug bounty → Improve report quality (cognition scoring)
- Client churn (Blue team) → Monthly reports + proactive alerts

---

## Next Session (Immediate)

**Start with P3.1:** Opportunity scanner automation (highest ROI, lowest complexity)

**Tasks:**
1. Create PostgreSQL schema: `opportunities` table
2. Create cron job: `cron/daily_opportunity_scan.py`
3. Add API route: `POST /api/v3/business/opportunities/scan`
4. Test end-to-end: scan → store → API query

**Duration:** 3-4h  
**Output:** First automated SaaS opportunity scan operational

---

**Status:** READY TO START  
**Next:** P3.1 Implementation
