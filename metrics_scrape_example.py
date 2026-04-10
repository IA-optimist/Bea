#!/usr/bin/env python3
"""
Generate example metrics output for documentation.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from prometheus_client import REGISTRY, generate_latest

# Import to register metrics
from business.business_engine import (
    OPPORTUNITY_SCANS,
    OPPORTUNITY_COUNT,
    SCAN_DURATION,
    PRODUCT_BUILDS,
    DEPLOY_DURATION,
    COMPLIANCE_CHECKS,
    PIPELINE_RUNS
)

# Simulate some metrics
OPPORTUNITY_SCANS.labels(source='producthunt').inc(10)
OPPORTUNITY_SCANS.labels(source='reddit').inc(8)
OPPORTUNITY_SCANS.labels(source='hackernews').inc(12)

OPPORTUNITY_COUNT.labels(source='producthunt').set(15)
OPPORTUNITY_COUNT.labels(source='reddit').set(23)
OPPORTUNITY_COUNT.labels(source='hackernews').set(18)

SCAN_DURATION.labels(source='producthunt').observe(3.456)
SCAN_DURATION.labels(source='producthunt').observe(4.123)
SCAN_DURATION.labels(source='reddit').observe(2.789)
SCAN_DURATION.labels(source='hackernews').observe(5.234)

PRODUCT_BUILDS.labels(status='success').inc(12)
PRODUCT_BUILDS.labels(status='failed').inc(2)

DEPLOY_DURATION.observe(12.345)
DEPLOY_DURATION.observe(15.678)
DEPLOY_DURATION.observe(8.901)

COMPLIANCE_CHECKS.labels(result='safe').inc(15)
COMPLIANCE_CHECKS.labels(result='blocked').inc(3)

PIPELINE_RUNS.labels(status='success').inc(8)
PIPELINE_RUNS.labels(status='failed').inc(1)

# Generate metrics
metrics_output = generate_latest(REGISTRY).decode('utf-8')

# Filter for business metrics only
print("=" * 80)
print("BUSINESS ENGINE METRICS - EXAMPLE OUTPUT")
print("=" * 80)
print()

for line in metrics_output.split('\n'):
    if 'business_' in line:
        print(line)

print()
print("=" * 80)
print("Total metrics exported:", len([l for l in metrics_output.split('\n') if l and not l.startswith('#')]))
print("Business metrics:", len([l for l in metrics_output.split('\n') if 'business_' in l and not l.startswith('#')]))
print("=" * 80)
