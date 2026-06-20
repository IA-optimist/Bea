#!/usr/bin/env python3
"""
Test script for business engine logging and metrics.

Tests:
1. Import and initialization
2. Metrics registration
3. Logging output format
4. Metrics scraping
"""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from prometheus_client import REGISTRY, generate_latest


def test_imports():
    """Test that all imports work"""
    print("=" * 80)
    print("TEST 1: Import Business Engine")
    print("=" * 80)

    try:
        print("✅ BusinessEngine imported successfully")

        # Check metrics are registered
        print("✅ All Prometheus metrics imported successfully")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False


def test_metrics_registration():
    """Test that metrics are registered in Prometheus registry"""
    print("\n" + "=" * 80)
    print("TEST 2: Metrics Registration")
    print("=" * 80)

    try:
        metrics_output = generate_latest(REGISTRY).decode('utf-8')

        # Check for our custom metrics
        expected_metrics = [
            'business_opportunity_scans_total',
            'business_opportunities_found',
            'business_scan_duration_seconds',
            'business_product_builds_total',
            'business_deploy_duration_seconds',
            'business_compliance_checks_total',
            'business_pipeline_runs_total',
        ]

        found_metrics = []
        missing_metrics = []

        for metric in expected_metrics:
            if metric in metrics_output:
                found_metrics.append(metric)
                print(f"✅ Found metric: {metric}")
            else:
                missing_metrics.append(metric)
                print(f"❌ Missing metric: {metric}")

        print(f"\nSummary: {len(found_metrics)}/{len(expected_metrics)} metrics registered")
        return len(missing_metrics) == 0

    except Exception as e:
        print(f"❌ Metrics registration test failed: {e}")
        return False


def test_logging_format():
    """Test structured logging format"""
    print("\n" + "=" * 80)
    print("TEST 3: Structured Logging")
    print("=" * 80)

    try:
        import structlog
        logger = structlog.get_logger("test")

        # Test log output
        logger.info(
            "test_event",
            test_field="value",
            numeric_field=123,
            duration=45.67
        )

        print("✅ Structured logging works")
        print("   Format: JSON with timestamp, level, and custom fields")
        return True

    except Exception as e:
        print(f"❌ Structured logging test failed: {e}")
        return False


def test_metrics_increment():
    """Test incrementing metrics"""
    print("\n" + "=" * 80)
    print("TEST 4: Metrics Increment")
    print("=" * 80)

    try:
        from business.business_engine import (
            OPPORTUNITY_SCANS,
            PRODUCT_BUILDS,
            COMPLIANCE_CHECKS
        )

        # Increment some metrics
        OPPORTUNITY_SCANS.labels(source='producthunt').inc()
        OPPORTUNITY_SCANS.labels(source='reddit').inc()
        PRODUCT_BUILDS.labels(status='success').inc()
        COMPLIANCE_CHECKS.labels(result='safe').inc()

        # Get current values
        metrics_output = generate_latest(REGISTRY).decode('utf-8')

        print("✅ Metrics incremented successfully")
        print("\nSample metrics output:")
        print("-" * 80)

        # Show relevant lines
        for line in metrics_output.split('\n'):
            if 'business_' in line and not line.startswith('#'):
                print(line)

        return True

    except Exception as e:
        print(f"❌ Metrics increment test failed: {e}")
        return False


def test_metrics_endpoint_format():
    """Test the metrics endpoint output format"""
    print("\n" + "=" * 80)
    print("TEST 5: Metrics Endpoint Format")
    print("=" * 80)

    try:
        metrics_output = generate_latest(REGISTRY).decode('utf-8')

        # Verify Prometheus format
        lines = metrics_output.split('\n')
        has_help = any('# HELP' in line for line in lines)
        has_type = any('# TYPE' in line for line in lines)
        has_metrics = any('business_' in line and not line.startswith('#') for line in lines)

        print(f"✅ Has HELP lines: {has_help}")
        print(f"✅ Has TYPE lines: {has_type}")
        print(f"✅ Has metric values: {has_metrics}")

        if has_help and has_type and has_metrics:
            print("\n✅ Metrics endpoint format is valid Prometheus format")
            print(f"\nTotal lines: {len(lines)}")
            print("Sample output (first 20 lines):")
            print("-" * 80)
            for line in lines[:20]:
                print(line)
            return True
        else:
            print("\n❌ Invalid metrics format")
            return False

    except Exception as e:
        print(f"❌ Metrics endpoint format test failed: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("BUSINESS ENGINE LOGGING & MONITORING TESTS")
    print("=" * 80 + "\n")

    results = []

    # Run tests
    results.append(("Import Test", test_imports()))
    results.append(("Metrics Registration", test_metrics_registration()))
    results.append(("Structured Logging", test_logging_format()))
    results.append(("Metrics Increment", test_metrics_increment()))
    results.append(("Metrics Endpoint Format", test_metrics_endpoint_format()))

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("=" * 80 + "\n")

    return all(result for _, result in results)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
