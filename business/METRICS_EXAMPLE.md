# Business Engine Metrics & Logging

## Overview

The Business Engine now includes comprehensive structured logging (using `structlog`) and Prometheus metrics for full observability of the autonomous SaaS generation pipeline.

## Structured Logging

All events are logged as structured JSON with consistent fields:

### Example Log Events

```json
{
  "event": "pipeline_start",
  "days_back": 30,
  "top_n": 5,
  "auto_build": true,
  "auto_deploy": false,
  "logger": "business.business_engine",
  "level": "info",
  "timestamp": "2026-04-09T09:17:42.123456Z"
}

{
  "event": "opportunity_scan_complete",
  "source": "producthunt",
  "count": 15,
  "duration": 3.456,
  "logger": "business.business_engine",
  "level": "info",
  "timestamp": "2026-04-09T09:17:45.123456Z"
}

{
  "event": "product_build_complete",
  "mvp_id": "mvp_1712653062",
  "product": "AI Task Manager",
  "tech_stack": "React/FastAPI",
  "path": "/root/.jarvismax/business/products/ai-task-manager",
  "duration": 45.678,
  "logger": "business.business_engine",
  "level": "info",
  "timestamp": "2026-04-09T09:18:30.123456Z"
}

{
  "event": "deployment_complete",
  "product": "AI Task Manager",
  "mvp_id": "mvp_1712653062",
  "tech_stack": "React/FastAPI",
  "deploy_url": "https://ai-task-manager.vercel.app",
  "duration": 12.345,
  "logger": "business.business_engine",
  "level": "info",
  "timestamp": "2026-04-09T09:18:42.123456Z"
}
```

## Prometheus Metrics

### Available Metrics

#### 1. Opportunity Scans
```
# HELP business_opportunity_scans_total Total number of opportunity scans
# TYPE business_opportunity_scans_total counter
business_opportunity_scans_total{source="producthunt"} 10.0
business_opportunity_scans_total{source="reddit"} 8.0
business_opportunity_scans_total{source="hackernews"} 12.0
```

#### 2. Opportunities Found
```
# HELP business_opportunities_found Number of opportunities found
# TYPE business_opportunities_found gauge
business_opportunities_found{source="producthunt"} 15.0
business_opportunities_found{source="reddit"} 23.0
business_opportunities_found{source="hackernews"} 18.0
```

#### 3. Scan Duration
```
# HELP business_scan_duration_seconds Time spent scanning opportunities
# TYPE business_scan_duration_seconds histogram
business_scan_duration_seconds_bucket{le="0.5",source="producthunt"} 0.0
business_scan_duration_seconds_bucket{le="1.0",source="producthunt"} 2.0
business_scan_duration_seconds_bucket{le="2.5",source="producthunt"} 5.0
business_scan_duration_seconds_bucket{le="5.0",source="producthunt"} 8.0
business_scan_duration_seconds_bucket{le="+Inf",source="producthunt"} 10.0
business_scan_duration_seconds_count{source="producthunt"} 10.0
business_scan_duration_seconds_sum{source="producthunt"} 34.567
```

#### 4. Product Builds
```
# HELP business_product_builds_total Total number of product builds
# TYPE business_product_builds_total counter
business_product_builds_total{status="success"} 12.0
business_product_builds_total{status="failed"} 2.0
```

#### 5. Deploy Duration
```
# HELP business_deploy_duration_seconds Time spent deploying products
# TYPE business_deploy_duration_seconds histogram
business_deploy_duration_seconds_bucket{le="5.0"} 3.0
business_deploy_duration_seconds_bucket{le="10.0"} 7.0
business_deploy_duration_seconds_bucket{le="30.0"} 11.0
business_deploy_duration_seconds_bucket{le="+Inf"} 12.0
business_deploy_duration_seconds_count 12.0
business_deploy_duration_seconds_sum 145.678
```

#### 6. Compliance Checks
```
# HELP business_compliance_checks_total Total number of compliance checks
# TYPE business_compliance_checks_total counter
business_compliance_checks_total{result="safe"} 15.0
business_compliance_checks_total{result="blocked"} 3.0
```

#### 7. Pipeline Runs
```
# HELP business_pipeline_runs_total Total number of pipeline runs
# TYPE business_pipeline_runs_total counter
business_pipeline_runs_total{status="success"} 8.0
business_pipeline_runs_total{status="failed"} 1.0
```

## Accessing Metrics

### HTTP Endpoint

The Prometheus metrics are exposed at the `/metrics` endpoint:

```bash
# Scrape all metrics
curl http://localhost:8000/metrics

# Filter for business metrics only
curl http://localhost:8000/metrics | grep business_
```

### Example Response

```
# HELP business_opportunity_scans_total Total number of opportunity scans
# TYPE business_opportunity_scans_total counter
business_opportunity_scans_total{source="producthunt"} 10.0
business_opportunity_scans_total{source="reddit"} 8.0
business_opportunity_scans_total{source="hackernews"} 12.0

# HELP business_opportunities_found Number of opportunities found
# TYPE business_opportunities_found gauge
business_opportunities_found{source="producthunt"} 15.0
business_opportunities_found{source="reddit"} 23.0
business_opportunities_found{source="hackernews"} 18.0

# HELP business_product_builds_total Total number of product builds
# TYPE business_product_builds_total counter
business_product_builds_total{status="success"} 12.0
business_product_builds_total{status="failed"} 2.0

# HELP business_pipeline_runs_total Total number of pipeline runs
# TYPE business_pipeline_runs_total counter
business_pipeline_runs_total{status="success"} 8.0
business_pipeline_runs_total{status="failed"} 1.0
```

## Prometheus Configuration

Add this to your `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'jarvismax-business'
    scrape_interval: 15s
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

## Grafana Dashboard

### Example Queries

**Total opportunities scanned per source:**
```promql
sum(business_opportunity_scans_total) by (source)
```

**Build success rate:**
```promql
sum(rate(business_product_builds_total{status="success"}[5m])) 
/ 
sum(rate(business_product_builds_total[5m]))
```

**Average scan duration:**
```promql
rate(business_scan_duration_seconds_sum[5m]) 
/ 
rate(business_scan_duration_seconds_count[5m])
```

**Average deploy time:**
```promql
rate(business_deploy_duration_seconds_sum[5m]) 
/ 
rate(business_deploy_duration_seconds_count[5m])
```

**Pipeline success rate:**
```promql
sum(rate(business_pipeline_runs_total{status="success"}[5m])) 
/ 
sum(rate(business_pipeline_runs_total[5m]))
```

## Log Aggregation

Structured logs can be ingested by any JSON-aware log aggregator:

- **ELK Stack**: Parse JSON logs directly
- **Loki**: Use `json` parser
- **Datadog**: Auto-parse JSON logs
- **CloudWatch**: Use JSON filter patterns

### Example Loki Query

```logql
{job="jarvismax"} 
| json 
| event="product_build_complete" 
| duration > 60
```

## Alerting Examples

### Prometheus Alerts

```yaml
groups:
  - name: business_engine
    rules:
      - alert: HighBuildFailureRate
        expr: |
          sum(rate(business_product_builds_total{status="failed"}[5m])) 
          / 
          sum(rate(business_product_builds_total[5m])) 
          > 0.2
        for: 10m
        annotations:
          summary: "High build failure rate detected"
          
      - alert: SlowDeployments
        expr: |
          rate(business_deploy_duration_seconds_sum[5m]) 
          / 
          rate(business_deploy_duration_seconds_count[5m]) 
          > 120
        for: 15m
        annotations:
          summary: "Deployments are taking longer than 2 minutes on average"
          
      - alert: LowOpportunityCount
        expr: |
          business_opportunities_found < 5
        for: 1h
        annotations:
          summary: "Low number of opportunities detected"
```

## Usage Example

```python
from business.business_engine import BusinessEngine

# Initialize engine
engine = BusinessEngine()

# Run pipeline - all logging and metrics are automatic
results = engine.run_pipeline(
    days_back=30,
    top_n=5,
    auto_build=True,
    auto_deploy=False
)

# Logs will be emitted as structured JSON
# Metrics will be available at /metrics endpoint
```

## Benefits

1. **Full Observability**: Every stage of the pipeline is logged with structured data
2. **Performance Tracking**: Histogram metrics track duration of all operations
3. **Error Detection**: Failed operations are logged and counted separately
4. **Trend Analysis**: Prometheus metrics enable historical analysis
5. **Alerting**: Set up alerts for failures, slow operations, or low output
6. **Debugging**: Structured logs make debugging easier with searchable fields
7. **Production Ready**: Compatible with industry-standard monitoring tools
