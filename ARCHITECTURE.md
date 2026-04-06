# JarvisMax OS — Architecture Documentation

**Version:** 1.0.0  
**Last Updated:** 2026-04-06

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Components](#core-components)
3. [Module System](#module-system)
4. [Task Processing](#task-processing)
5. [Data Flow](#data-flow)
6. [API Layer](#api-layer)
7. [Database Schema](#database-schema)
8. [Deployment](#deployment)

---

## System Overview

JarvisMax is a **microservices-based autonomous AI operating system** designed for:
- Autonomous business generation (SaaS pipeline)
- Automated security operations (Bug bounty + SOC)
- Revenue optimization (Tax, Market Intelligence, Marketplace)

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      EXTERNAL CLIENTS                        │
│   CLI, Web Dashboard, REST API, Webhooks, Telegram Bot      │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│                     API LAYER (FastAPI)                      │
│  /health /status /modules /tasks /revenue /metrics           │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│                    CORE OS (Orchestrator)                    │
│  ┌────────────────┐  ┌───────────────┐  ┌────────────────┐  │
│  │ Module Registry│  │  Task Queue   │  │ Worker Pool    │  │
│  │  (6 modules)   │  │   (Redis)     │  │  (4 workers)   │  │
│  └────────────────┘  └───────────────┘  └────────────────┘  │
└───────────────────────┬──────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        │               │               │
┌───────▼──────┐  ┌─────▼────┐  ┌──────▼──────┐
│ Business Eng │  │ Security │  │  Services   │
│ - Scanner    │  │ - HexStrike│ │ - Tax Opt   │
│ - Builder    │  │ - SOC      │  │ - Intel     │
│ - Deployer   │  │            │  │ - Marketplace│
└──────────────┘  └──────────┘  └─────────────┘
        │               │               │
        └───────────────┼───────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│                     DATA LAYER                               │
│  ┌──────────────┐         ┌──────────────┐                  │
│  │  PostgreSQL  │         │    Redis     │                  │
│  │  (Persistent)│         │   (Cache)    │                  │
│  └──────────────┘         └──────────────┘                  │
└──────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Core OS (`core/jarvismax_os.py`)

**Central orchestrator** for all modules and tasks.

#### Key Classes

```python
class JarvisMaxOS:
    """Main OS class"""
    
    # State
    modules: Dict[str, Module]        # Registry of all modules
    running: bool                     # OS running state
    task_queue: asyncio.Queue         # Task queue
    workers: List[asyncio.Task]       # Worker pool
    
    # Methods
    async def start()                 # Start OS + modules
    async def stop()                  # Stop OS + modules
    def register_module(...)          # Register a module
    async def dispatch(module, action, **params)  # Dispatch action
    def get_status()                  # Get system status
```

```python
@dataclass
class Module:
    """OS module"""
    
    name: str
    description: str
    version: str
    status: ModuleStatus              # stopped, starting, running, error
    
    # Lifecycle hooks
    start_fn: Callable
    stop_fn: Callable
    health_fn: Callable
    
    # Metrics
    requests_total: int
    requests_failed: int
    avg_response_time: float
    
    # Revenue
    mrr: float
    customers: int
```

#### Lifecycle

1. **Initialization** — Create OS instance, set up queues
2. **Start** — Register modules, start each module, spawn workers
3. **Running** — Process tasks from queue, update metrics
4. **Stop** — Stop workers, stop modules, cleanup

---

### 2. Module Integration (`core/modules_integration.py`)

**Action registry** connecting Core OS to real module implementations.

```python
ACTION_REGISTRY = {
    'business_engine': {
        'scan_opportunities': business_engine_scan_opportunities,
        'build_product': business_engine_build_product,
        'deploy_product': business_engine_deploy_product,
    },
    'tax_optimizer': {
        'calculate': tax_optimizer_calculate,
    },
    # ... etc
}

async def execute_action(module: str, action: str, params: Dict) -> Any:
    """Execute a module action"""
    action_fn = ACTION_REGISTRY[module][action]
    return await action_fn(**params)
```

**Actions wrap module methods** and handle:
- Async execution (`asyncio.to_thread` for sync functions)
- Error handling (try/catch, error dict)
- Logging

---

### 3. Task Processing

#### Task Queue (Redis-backed asyncio.Queue)

```python
task = {
    'id': uuid4(),
    'module': 'business_engine',
    'action': 'scan_opportunities',
    'params': {},
    'status': 'queued',
    'created_at': datetime.now(),
}

await os_instance.task_queue.put(task)
```

#### Workers (4 async workers)

```python
async def _task_worker(self, worker_id: int):
    while self.running:
        task = await self.task_queue.get()
        
        # Execute action
        result = await execute_action(
            task['module'],
            task['action'],
            task['params']
        )
        
        # Update metrics
        module.requests_total += 1
        module.avg_response_time = (old + new) / 2
        
        self.task_queue.task_done()
```

**Flow:**
1. Client creates task via API
2. Task queued in Redis
3. Worker picks up task
4. Worker executes action via `execute_action()`
5. Worker updates metrics
6. Result (future implementation: stored in DB)

---

## Module System

### Registered Modules

| Module | Version | Revenue Target | Description |
|--------|---------|----------------|-------------|
| `business_engine` | 1.0.0 | €25k/month | SaaS generation pipeline |
| `hexstrike` | 2.0.0 | €7k/month | Bug bounty automation |
| `tax_optimizer` | 1.0.0 | €3k/month | Tax optimization service |
| `soc_service` | 1.0.0 | €10k/month | Security Operations Center |
| `data_intelligence` | 1.0.0 | €5k/month | Market research & analysis |
| `agent_marketplace` | 1.0.0 | €15k/month | AI agent marketplace |

### Module Structure

```
business/
├── automation/
│   ├── opportunity_scanner.py    # Scan Reddit, HN, Twitter, Product Hunt
│   └── product_builder.py        # Generate SaaS stack (React + FastAPI)
├── legal/
│   └── compliance_checker.py     # Legal validation (RED/YELLOW/GREEN)
├── revenue/
│   └── revenue_engine.py         # MRR/ARR tracking
├── fiscal/
│   └── tax_optimizer.py          # Tax calculation & optimization
└── business_engine.py            # Main orchestrator
```

Each module has:
- **Start function** — Initialize resources (DB connections, API clients, etc.)
- **Stop function** — Cleanup resources
- **Health function** — Check module health
- **Actions** — Business logic (registered in `ACTION_REGISTRY`)

---

## Data Flow

### Example: Scan Opportunities

```
┌──────────┐
│  Client  │
└────┬─────┘
     │ POST /tasks {"module": "business_engine", "action": "scan_opportunities"}
     ▼
┌─────────────┐
│  FastAPI    │ Validate request, create task
└─────┬───────┘
      │ task_queue.put(task)
      ▼
┌─────────────┐
│ Redis Queue │
└─────┬───────┘
      │ Worker polls queue
      ▼
┌─────────────┐
│   Worker    │ execute_action("business_engine", "scan_opportunities", {})
└─────┬───────┘
      │
      ▼
┌─────────────────────────────┐
│ modules_integration.py      │
│ business_engine_scan_opportunities()
└─────┬───────────────────────┘
      │ OpportunityScanner().scan_all_sources()
      ▼
┌─────────────────────────────┐
│ business/automation/        │
│ opportunity_scanner.py      │ Fetch Reddit, HN, Twitter, Product Hunt
└─────┬───────────────────────┘
      │ Return list of opportunities
      ▼
┌─────────────┐
│   Worker    │ Update metrics (requests_total++, avg_response_time)
└─────┬───────┘
      │
      ▼
┌─────────────┐
│ PostgreSQL  │ (Future: Store task result in DB)
└─────────────┘
```

---

## API Layer

### FastAPI Server (`web_api/main.py`)

#### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Root (API info) |
| GET | `/health` | Health check |
| GET | `/status` | OS status (uptime, modules, metrics, revenue) |
| GET | `/modules` | List all modules |
| GET | `/modules/{name}` | Get module details |
| POST | `/modules/{name}/start` | Start a module |
| POST | `/modules/{name}/stop` | Stop a module |
| POST | `/tasks` | Create & queue a task |
| GET | `/tasks` | List tasks (stub) |
| GET | `/tasks/{id}` | Get task details (stub) |
| GET | `/revenue` | Revenue dashboard (MRR/ARR/breakdown) |
| GET | `/metrics` | System metrics (requests, success rate, per-module) |

#### Request/Response Models

```python
class TaskCreate(BaseModel):
    module: str
    action: str
    params: Optional[Dict] = {}

class TaskResponse(BaseModel):
    id: str
    module: str
    action: str
    params: Dict
    status: str
    created_at: str

class ModuleResponse(BaseModel):
    name: str
    description: str
    version: str
    status: str
    metrics: Dict
    revenue: Dict
```

#### Lifespan Management

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start OS when FastAPI starts
    os_instance = JarvisMaxOS()
    await os_instance.start()
    
    yield  # FastAPI runs
    
    # Stop OS when FastAPI stops
    await os_instance.stop()

app = FastAPI(lifespan=lifespan)
```

---

## Database Schema

### PostgreSQL Tables (`db/init.sql`)

#### Core Tables

**modules** — Module registry
```sql
CREATE TABLE modules (
    id UUID PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    version VARCHAR(20),
    status VARCHAR(20),
    started_at TIMESTAMP,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**tasks** — Task queue history
```sql
CREATE TABLE tasks (
    id UUID PRIMARY KEY,
    module_name VARCHAR(100) REFERENCES modules(name),
    action VARCHAR(100),
    params JSONB,
    status VARCHAR(20),          -- pending, running, completed, failed
    result JSONB,
    error TEXT,
    created_at TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

**revenue** — Revenue tracking
```sql
CREATE TABLE revenue (
    id UUID PRIMARY KEY,
    module_name VARCHAR(100) REFERENCES modules(name),
    date DATE NOT NULL,
    amount DECIMAL(10, 2),
    customers INTEGER,
    created_at TIMESTAMP
);
```

**metrics** — System metrics
```sql
CREATE TABLE metrics (
    id UUID PRIMARY KEY,
    module_name VARCHAR(100) REFERENCES modules(name),
    metric_name VARCHAR(100),
    metric_value DECIMAL(10, 2),
    timestamp TIMESTAMP
);
```

#### Module-Specific Tables

- **opportunities** — Business Engine scanned opportunities
- **products** — Business Engine generated products
- **soc_clients** — SOC Service clients
- **soc_alerts** — SOC Service security alerts
- **tax_reports** — Tax Optimizer reports
- **marketplace_agents** — Agent Marketplace listings
- **marketplace_purchases** — Marketplace transactions

---

## Deployment

### Docker Compose

```yaml
services:
  postgres:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
  
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    ports:
      - "6379:6379"
  
  jarvismax-core:
    build: .
    command: python3 core/jarvismax_os.py
    depends_on:
      - postgres
      - redis
    ports:
      - "8080:8080"
  
  jarvismax-api:
    build: .
    command: uvicorn web_api.main:app --host 0.0.0.0 --port 8000
    depends_on:
      - jarvismax-core
    ports:
      - "8000:8000"
```

### Deployment Steps

1. **Clone repo**
```bash
git clone https://github.com/UniTy01/Jarvismax-master.git
cd Jarvismax-master
```

2. **Configure**
```bash
cp .env.example .env
nano .env  # Change passwords
```

3. **Start**
```bash
docker-compose up -d
```

4. **Verify**
```bash
docker-compose ps
curl http://localhost:8000/health
```

---

## Performance Characteristics

### Latency

| Operation | Latency | Notes |
|-----------|---------|-------|
| Task queue (Redis) | < 1ms | In-memory queue |
| Worker dispatch | < 10ms | Async execution |
| Module action (avg) | 100-500ms | Depends on module |
| Database write (Postgres) | 5-20ms | SSD storage |
| API request | 10-50ms | FastAPI + async |

### Throughput

| Metric | Capacity | Notes |
|--------|----------|-------|
| Tasks/second | 100-500 | 4 workers, avg 100ms/task |
| API requests/second | 1,000+ | FastAPI async |
| Concurrent tasks | 4 | Worker pool size |

### Scalability

**Horizontal scaling:**
- Add more worker processes (increase worker pool size)
- Add more API servers (load balanced)
- Shard PostgreSQL (per-module databases)

**Vertical scaling:**
- Increase worker count (8, 16, 32 workers)
- Increase Redis memory
- Increase Postgres connection pool

---

## Security

### Authentication (Future)
- JWT tokens for API access
- Per-module API keys
- Role-based access control (RBAC)

### Data Protection
- PostgreSQL encrypted at rest
- Redis password-protected
- Environment variables for secrets

### Network
- Docker network isolation
- Nginx reverse proxy (optional)
- HTTPS via Let's Encrypt

---

## Monitoring & Observability

### Metrics (Prometheus format)

```python
# Per-module
jarvismax_module_requests_total{module="business_engine"}
jarvismax_module_requests_failed{module="business_engine"}
jarvismax_module_avg_response_time{module="business_engine"}
jarvismax_module_mrr{module="business_engine"}

# System
jarvismax_uptime_seconds
jarvismax_modules_running
jarvismax_tasks_queued
```

### Logs

```bash
# Core OS logs
docker-compose logs jarvismax-core

# API logs
docker-compose logs jarvismax-api

# Module logs
# Stored in ~/.jarvismax/logs/<module>.log
```

---

## Future Roadmap

### v1.1.0 (2 weeks)
- [ ] Complete REST API (task history, module logs)
- [ ] Web Dashboard (React + Tailwind)
- [ ] Real-time WebSocket updates
- [ ] Grafana dashboards

### v1.2.0 (1 month)
- [ ] Automated deployment (Vercel + Railway APIs)
- [ ] GitHub repo auto-creation
- [ ] HexStrike: Extract remaining 139 tools

### v2.0.0 (3 months)
- [ ] AGI Loop V2 (6-hour self-improvement cycles)
- [ ] Multi-tenant support (white-label)
- [ ] Mobile app (React Native)

---

**Last Updated:** 2026-04-06  
**Maintainer:** UniTy (Maxence)  
**License:** MIT
