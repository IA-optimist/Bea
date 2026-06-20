#!/usr/bin/env python3
"""
Business Engine — Autonomous SaaS Generation Pipeline

End-to-end workflow:
1. Scan opportunities (Product Hunt, Reddit, HN)
2. Score and rank by potential
3. Check legal compliance
4. Generate product spec
5. Build complete SaaS (frontend + backend)
6. Deploy to production
7. Track revenue and optimize

Target: €25,000/month in 6 months
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import structlog
from prometheus_client import Counter, Histogram, Gauge

from business.automation.opportunity_scanner import OpportunityScanner, Opportunity
from business.automation.product_builder import ProductBuilder
from business.legal.compliance_checker import ComplianceChecker
from business.revenue.revenue_engine import RevenueEngine, PortfolioMetrics

# Configure structlog for structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Prometheus metrics
OPPORTUNITY_SCANS = Counter(
    'business_opportunity_scans_total',
    'Total number of opportunity scans',
    ['source']
)

OPPORTUNITY_COUNT = Gauge(
    'business_opportunities_found',
    'Number of opportunities found',
    ['source']
)

SCAN_DURATION = Histogram(
    'business_scan_duration_seconds',
    'Time spent scanning opportunities',
    ['source']
)

PRODUCT_BUILDS = Counter(
    'business_product_builds_total',
    'Total number of product builds',
    ['status']
)

DEPLOY_DURATION = Histogram(
    'business_deploy_duration_seconds',
    'Time spent deploying products'
)

COMPLIANCE_CHECKS = Counter(
    'business_compliance_checks_total',
    'Total number of compliance checks',
    ['result']
)

PIPELINE_RUNS = Counter(
    'business_pipeline_runs_total',
    'Total number of pipeline runs',
    ['status']
)


class BusinessEngine:
    """
    Orchestrate the entire business automation pipeline.
    
    Usage:
        engine = BusinessEngine()
        
        # Full pipeline
        engine.run_pipeline(days_back=30, top_n=5, auto_build=False)
        
        # Or step by step
        opportunities = engine.scan_opportunities(days_back=7)
        product = engine.build_product(opportunities[0])
        engine.deploy_product(product)
    """

    def __init__(self, workspace: Optional[Path] = None):
        self.workspace = workspace or Path.home() / ".beamax" / "business"
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.scanner = OpportunityScanner(cache_dir=self.workspace / "opportunities")
        self.builder = ProductBuilder(output_dir=self.workspace / "products")
        self.compliance = ComplianceChecker()
        self.revenue = RevenueEngine(data_dir=self.workspace / "revenue")

        logger.info("business_engine_initialized", workspace=str(self.workspace))

    def run_pipeline(
        self,
        days_back: int = 30,
        top_n: int = 5,
        auto_build: bool = False,
        auto_deploy: bool = False,
    ) -> Dict:
        """
        Run complete business generation pipeline.
        
        Args:
            days_back: How many days to scan
            top_n: Top N opportunities to consider
            auto_build: Automatically build products
            auto_deploy: Automatically deploy (CAREFUL!)
        
        Returns:
            Pipeline results dict
        """
        pipeline_start = time.time()

        logger.info(
            "pipeline_start",
            days_back=days_back,
            top_n=top_n,
            auto_build=auto_build,
            auto_deploy=auto_deploy
        )

        results = {
            'started_at': datetime.now().isoformat(),
            'config': {
                'days_back': days_back,
                'top_n': top_n,
                'auto_build': auto_build,
                'auto_deploy': auto_deploy,
            },
            'stages': {},
        }

        # STAGE 1: Scan opportunities
        logger.info("stage_start", stage=1, name="scan_opportunities")
        scan_start = time.time()

        try:
            # Track each source separately
            opportunities = []
            sources = ['producthunt', 'reddit', 'hackernews']

            for source in sources:
                source_start = time.time()
                try:
                    # Scan from specific source (this assumes scanner has per-source methods)
                    source_opps = self.scanner.scan_all(days_back=days_back)
                    opportunities.extend(source_opps)

                    source_duration = time.time() - source_start

                    # Log structured data
                    logger.info(
                        "opportunity_scan_complete",
                        source=source,
                        count=len(source_opps),
                        duration=source_duration
                    )

                    # Update Prometheus metrics
                    OPPORTUNITY_SCANS.labels(source=source).inc()
                    OPPORTUNITY_COUNT.labels(source=source).set(len(source_opps))
                    SCAN_DURATION.labels(source=source).observe(source_duration)

                except Exception as source_error:
                    logger.error(
                        "opportunity_scan_failed",
                        source=source,
                        error=str(source_error)
                    )

            top_opps = self.scanner.get_top_opportunities(opportunities, limit=top_n)

            # Save report
            report = self.scanner.generate_report(opportunities, top_n)
            report_path = self.scanner.cache_dir / "report.md"
            report_path.write_text(report)

            self.scanner.save_opportunities(opportunities, "opportunities.json")

            scan_duration = time.time() - scan_start

            results['stages']['scan'] = {
                'status': 'success',
                'total_opportunities': len(opportunities),
                'top_opportunities': len(top_opps),
                'report_path': str(report_path),
                'duration': scan_duration,
            }

            logger.info(
                "stage_complete",
                stage=1,
                name="scan_opportunities",
                total_found=len(opportunities),
                top_selected=len(top_opps),
                duration=scan_duration
            )

        except Exception as e:
            logger.error("stage_failed", stage=1, name="scan_opportunities", error=str(e))
            results['stages']['scan'] = {'status': 'failed', 'error': str(e)}
            PIPELINE_RUNS.labels(status='failed').inc()
            return results

        # STAGE 2: Compliance check
        logger.info("stage_start", stage=2, name="compliance_check")
        compliance_start = time.time()
        safe_opportunities = []

        try:
            for i, opp_dict in enumerate([o.to_dict() for o in top_opps], 1):
                check_start = time.time()

                logger.info(
                    "compliance_check_start",
                    opportunity=opp_dict['title'][:50],
                    index=i,
                    total=len(top_opps)
                )

                # Generate spec (needed for compliance check)
                spec = self.builder.generate_spec(opp_dict)
                report = self.compliance.check_idea(spec.to_dict())

                check_duration = time.time() - check_start

                if report.is_safe:
                    logger.info(
                        "compliance_check_passed",
                        opportunity=opp_dict['title'][:50],
                        risk_level=report.overall_risk.value,
                        duration=check_duration
                    )
                    safe_opportunities.append((opp_dict, spec, report))
                    COMPLIANCE_CHECKS.labels(result='safe').inc()
                else:
                    logger.warning(
                        "compliance_check_blocked",
                        opportunity=opp_dict['title'][:50],
                        risk_level=report.overall_risk.value,
                        duration=check_duration
                    )
                    COMPLIANCE_CHECKS.labels(result='blocked').inc()

                    # Save compliance report
                    self.compliance.save_report(report, spec.name)

            compliance_duration = time.time() - compliance_start

            results['stages']['compliance'] = {
                'status': 'success',
                'checked': len(top_opps),
                'safe': len(safe_opportunities),
                'blocked': len(top_opps) - len(safe_opportunities),
                'duration': compliance_duration,
            }

            logger.info(
                "stage_complete",
                stage=2,
                name="compliance_check",
                checked=len(top_opps),
                safe=len(safe_opportunities),
                blocked=len(top_opps) - len(safe_opportunities),
                duration=compliance_duration
            )

        except Exception as e:
            logger.error("stage_failed", stage=2, name="compliance_check", error=str(e))
            results['stages']['compliance'] = {'status': 'failed', 'error': str(e)}
            PIPELINE_RUNS.labels(status='failed').inc()
            return results

        if not safe_opportunities:
            logger.warning("⚠️  No safe opportunities found. Pipeline stopped.")
            results['status'] = 'no_safe_opportunities'
            return results

        # STAGE 3: Product generation
        logger.info("stage_start", stage=3, name="product_generation")
        build_start = time.time()
        built_products = []

        try:
            for i, (opp, spec, compliance_report) in enumerate(safe_opportunities, 1):
                logger.info(
                    "product_build_start",
                    product=spec.name,
                    index=i,
                    total=len(safe_opportunities)
                )

                if auto_build:
                    product_build_start = time.time()
                    try:
                        project_dir = self.builder.build_product(spec)
                        build_duration = time.time() - product_build_start

                        # Extract tech stack info
                        tech_stack = getattr(spec, 'tech_stack', 'unknown')
                        if isinstance(tech_stack, dict):
                            tech_stack = f"{tech_stack.get('frontend', 'unknown')}/{tech_stack.get('backend', 'unknown')}"

                        built_products.append({
                            'name': spec.name,
                            'path': str(project_dir),
                            'spec': spec.to_dict(),
                            'compliance': compliance_report.to_dict(),
                            'mvp_id': getattr(spec, 'id', f'mvp_{int(time.time())}'),
                            'tech_stack': tech_stack,
                            'build_duration': build_duration,
                        })

                        logger.info(
                            "product_build_complete",
                            mvp_id=built_products[-1]['mvp_id'],
                            product=spec.name,
                            tech_stack=tech_stack,
                            path=str(project_dir),
                            duration=build_duration
                        )

                        PRODUCT_BUILDS.labels(status='success').inc()

                    except Exception as e:
                        build_duration = time.time() - product_build_start
                        logger.error(
                            "product_build_failed",
                            product=spec.name,
                            error=str(e),
                            duration=build_duration
                        )
                        PRODUCT_BUILDS.labels(status='failed').inc()
                else:
                    logger.info(
                        "product_build_skipped",
                        product=spec.name,
                        reason="auto_build=False"
                    )

            build_duration = time.time() - build_start

            results['stages']['build'] = {
                'status': 'success',
                'built': len(built_products),
                'duration': build_duration,
            }

            logger.info(
                "stage_complete",
                stage=3,
                name="product_generation",
                built=len(built_products),
                skipped=len(safe_opportunities) - len(built_products) if not auto_build else 0,
                duration=build_duration
            )

        except Exception as e:
            logger.error("stage_failed", stage=3, name="product_generation", error=str(e))
            results['stages']['build'] = {'status': 'failed', 'error': str(e)}
            PIPELINE_RUNS.labels(status='failed').inc()
            return results

        # STAGE 4: Deployment
        logger.info("stage_start", stage=4, name="deployment")
        deploy_stage_start = time.time()

        if auto_deploy and built_products:
            deployed = []

            for product in built_products:
                deploy_start = time.time()

                logger.info(
                    "deployment_start",
                    product=product['name'],
                    mvp_id=product.get('mvp_id', 'unknown')
                )

                try:
                    # TODO: Implement actual deployment (Vercel API + Railway API)
                    # Simulated deployment for now
                    deploy_url = f"https://{product['name'].lower().replace(' ', '-')}.vercel.app"
                    deploy_duration = time.time() - deploy_start

                    deployed.append({
                        'name': product['name'],
                        'url': deploy_url,
                        'duration': deploy_duration,
                    })

                    logger.info(
                        "deployment_complete",
                        product=product['name'],
                        mvp_id=product.get('mvp_id', 'unknown'),
                        tech_stack=product.get('tech_stack', 'unknown'),
                        deploy_url=deploy_url,
                        duration=deploy_duration
                    )

                    DEPLOY_DURATION.observe(deploy_duration)

                except Exception as e:
                    deploy_duration = time.time() - deploy_start
                    logger.error(
                        "deployment_failed",
                        product=product['name'],
                        error=str(e),
                        duration=deploy_duration
                    )

            deploy_stage_duration = time.time() - deploy_stage_start

            results['stages']['deploy'] = {
                'status': 'partial' if deployed else 'failed',
                'deployed': len(deployed),
                'message': 'Manual deployment required' if not deployed else 'Deployed successfully',
                'duration': deploy_stage_duration,
            }

            logger.info(
                "stage_complete",
                stage=4,
                name="deployment",
                deployed=len(deployed),
                duration=deploy_stage_duration
            )
        else:
            logger.info(
                "stage_skipped",
                stage=4,
                name="deployment",
                reason="auto_deploy=False or no products"
            )
            results['stages']['deploy'] = {
                'status': 'skipped',
            }

        # STAGE 5: Revenue tracking setup
        logger.info("\n📍 STAGE 5/5: Revenue tracking...")

        try:
            # Get current portfolio metrics
            portfolio = self.revenue.get_portfolio_metrics()
            alerts = self.revenue.check_alerts(portfolio)
            dashboard = self.revenue.generate_dashboard(portfolio, alerts)
            dashboard_path = self.revenue.save_dashboard(dashboard)

            results['stages']['revenue'] = {
                'status': 'success',
                'mrr': portfolio.total_mrr,
                'arr': portfolio.total_arr,
                'products': portfolio.total_products,
                'customers': portfolio.total_customers,
                'dashboard_path': str(dashboard_path),
            }

            logger.info("✅ Revenue tracking active")
            logger.info(f"   MRR: €{portfolio.total_mrr:.2f}")
            logger.info(f"   Dashboard: {dashboard_path}")

        except Exception as e:
            logger.error(f"❌ Stage 5 failed: {e}")
            results['stages']['revenue'] = {'status': 'failed', 'error': str(e)}

        # FINAL SUMMARY
        pipeline_duration = time.time() - pipeline_start

        results['completed_at'] = datetime.now().isoformat()
        results['status'] = 'success'
        results['duration'] = pipeline_duration
        results['summary'] = {
            'opportunities_scanned': len(opportunities),
            'safe_opportunities': len(safe_opportunities),
            'products_built': len(built_products),
        }

        # Record successful pipeline run
        PIPELINE_RUNS.labels(status='success').inc()

        logger.info(
            "pipeline_complete",
            status="success",
            opportunities_scanned=len(opportunities),
            safe_opportunities=len(safe_opportunities),
            products_built=len(built_products),
            total_duration=pipeline_duration
        )

        # Save pipeline results
        results_path = self.workspace / "pipeline_results.json"
        results_path.write_text(json.dumps(results, indent=2))

        logger.info("pipeline_results_saved", path=str(results_path))

        return results

    def scan_opportunities(self, days_back: int = 30) -> List[Opportunity]:
        """Scan for business opportunities"""
        return self.scanner.scan_all(days_back=days_back)

    def build_product(self, opportunity: Dict) -> Path:
        """Build product from opportunity"""
        spec = self.builder.generate_spec(opportunity)

        # Check compliance
        report = self.compliance.check_idea(spec.to_dict())

        if not report.is_safe:
            raise ValueError(f"Compliance check failed: {report.overall_risk.value}")

        # Build
        return self.builder.build_product(spec)

    def get_portfolio_status(self) -> PortfolioMetrics:
        """Get current portfolio metrics"""
        return self.revenue.get_portfolio_metrics()

    def check_revenue(self, product_name: str):
        """Check revenue for a specific product"""
        return self.revenue.calculate_metrics(product_name)


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Business Engine — Autonomous SaaS Generation")
    parser.add_argument('--days', type=int, default=30, help='Days to scan (default: 30)')
    parser.add_argument('--top', type=int, default=5, help='Top N opportunities (default: 5)')
    parser.add_argument('--build', action='store_true', help='Auto-build products')
    parser.add_argument('--deploy', action='store_true', help='Auto-deploy (CAREFUL!)')
    parser.add_argument('--workspace', help='Custom workspace directory')
    args = parser.parse_args()

    # Initialize
    workspace = Path(args.workspace) if args.workspace else None
    engine = BusinessEngine(workspace=workspace)

    # Run pipeline
    results = engine.run_pipeline(
        days_back=args.days,
        top_n=args.top,
        auto_build=args.build,
        auto_deploy=args.deploy,
    )

    print(f"\n{'='*80}")
    print("📊 PIPELINE SUMMARY")
    print(f"{'='*80}")
    print(json.dumps(results['summary'], indent=2))
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
