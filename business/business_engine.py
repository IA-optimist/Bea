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
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from business.automation.opportunity_scanner import OpportunityScanner, Opportunity
from business.automation.product_builder import ProductBuilder, ProductSpec
from business.legal.compliance_checker import ComplianceChecker, ComplianceReport
from business.revenue.revenue_engine import RevenueEngine, PortfolioMetrics

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


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
        self.workspace = workspace or Path.home() / ".jarvismax" / "business"
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        self.scanner = OpportunityScanner(cache_dir=self.workspace / "opportunities")
        self.builder = ProductBuilder(output_dir=self.workspace / "products")
        self.compliance = ComplianceChecker()
        self.revenue = RevenueEngine(data_dir=self.workspace / "revenue")
        
        logger.info(f"🚀 Business Engine initialized")
        logger.info(f"   Workspace: {self.workspace}")
    
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
        logger.info("=" * 80)
        logger.info("🚀 BUSINESS ENGINE — FULL PIPELINE START")
        logger.info("=" * 80)
        
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
        logger.info("\n📍 STAGE 1/5: Scanning opportunities...")
        try:
            opportunities = self.scanner.scan_all(days_back=days_back)
            top_opps = self.scanner.get_top_opportunities(opportunities, limit=top_n)
            
            # Save report
            report = self.scanner.generate_report(opportunities, top_n)
            report_path = self.scanner.cache_dir / "report.md"
            report_path.write_text(report)
            
            self.scanner.save_opportunities(opportunities, "opportunities.json")
            
            results['stages']['scan'] = {
                'status': 'success',
                'total_opportunities': len(opportunities),
                'top_opportunities': len(top_opps),
                'report_path': str(report_path),
            }
            
            logger.info(f"✅ Found {len(opportunities)} opportunities")
            logger.info(f"   Top {top_n} selected for analysis")
        
        except Exception as e:
            logger.error(f"❌ Stage 1 failed: {e}")
            results['stages']['scan'] = {'status': 'failed', 'error': str(e)}
            return results
        
        # STAGE 2: Compliance check
        logger.info("\n📍 STAGE 2/5: Compliance checking...")
        safe_opportunities = []
        
        try:
            for i, opp_dict in enumerate([o.to_dict() for o in top_opps], 1):
                logger.info(f"   Checking {i}/{len(top_opps)}: {opp_dict['title'][:50]}...")
                
                # Generate spec (needed for compliance check)
                spec = self.builder.generate_spec(opp_dict)
                report = self.compliance.check_idea(spec.to_dict())
                
                if report.is_safe:
                    logger.info(f"      ✅ SAFE ({report.overall_risk.value})")
                    safe_opportunities.append((opp_dict, spec, report))
                else:
                    logger.warning(f"      ❌ BLOCKED ({report.overall_risk.value})")
                    
                    # Save compliance report
                    self.compliance.save_report(report, spec.name)
            
            results['stages']['compliance'] = {
                'status': 'success',
                'checked': len(top_opps),
                'safe': len(safe_opportunities),
                'blocked': len(top_opps) - len(safe_opportunities),
            }
            
            logger.info(f"✅ Compliance check complete")
            logger.info(f"   Safe: {len(safe_opportunities)}/{len(top_opps)}")
        
        except Exception as e:
            logger.error(f"❌ Stage 2 failed: {e}")
            results['stages']['compliance'] = {'status': 'failed', 'error': str(e)}
            return results
        
        if not safe_opportunities:
            logger.warning("⚠️  No safe opportunities found. Pipeline stopped.")
            results['status'] = 'no_safe_opportunities'
            return results
        
        # STAGE 3: Product generation
        logger.info("\n📍 STAGE 3/5: Product generation...")
        built_products = []
        
        try:
            for i, (opp, spec, compliance_report) in enumerate(safe_opportunities, 1):
                logger.info(f"   Building {i}/{len(safe_opportunities)}: {spec.name}...")
                
                if auto_build:
                    try:
                        project_dir = self.builder.build_product(spec)
                        built_products.append({
                            'name': spec.name,
                            'path': str(project_dir),
                            'spec': spec.to_dict(),
                            'compliance': compliance_report.to_dict(),
                        })
                        logger.info(f"      ✅ Built: {project_dir}")
                    except Exception as e:
                        logger.error(f"      ❌ Build failed: {e}")
                else:
                    logger.info(f"      ⏭️  Skipped (auto_build=False)")
            
            results['stages']['build'] = {
                'status': 'success',
                'built': len(built_products),
            }
            
            if built_products:
                logger.info(f"✅ Products built: {len(built_products)}")
            else:
                logger.info(f"⏭️  Product building skipped")
        
        except Exception as e:
            logger.error(f"❌ Stage 3 failed: {e}")
            results['stages']['build'] = {'status': 'failed', 'error': str(e)}
            return results
        
        # STAGE 4: Deployment
        logger.info("\n📍 STAGE 4/5: Deployment...")
        
        if auto_deploy and built_products:
            deployed = []
            
            for product in built_products:
                logger.info(f"   Deploying: {product['name']}...")
                
                try:
                    # TODO: Implement actual deployment (Vercel API + Railway API)
                    logger.warning(f"      ⚠️  Deployment not implemented yet")
                    logger.info(f"      📝 Manual: cd {product['path']} && vercel deploy")
                except Exception as e:
                    logger.error(f"      ❌ Deploy failed: {e}")
            
            results['stages']['deploy'] = {
                'status': 'partial',
                'deployed': len(deployed),
                'message': 'Manual deployment required',
            }
        else:
            logger.info(f"   ⏭️  Deployment skipped (auto_deploy=False or no products)")
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
            
            logger.info(f"✅ Revenue tracking active")
            logger.info(f"   MRR: €{portfolio.total_mrr:.2f}")
            logger.info(f"   Dashboard: {dashboard_path}")
        
        except Exception as e:
            logger.error(f"❌ Stage 5 failed: {e}")
            results['stages']['revenue'] = {'status': 'failed', 'error': str(e)}
        
        # FINAL SUMMARY
        results['completed_at'] = datetime.now().isoformat()
        results['status'] = 'success'
        results['summary'] = {
            'opportunities_scanned': len(opportunities),
            'safe_opportunities': len(safe_opportunities),
            'products_built': len(built_products),
        }
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ PIPELINE COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Opportunities Scanned: {len(opportunities)}")
        logger.info(f"Safe to Build: {len(safe_opportunities)}")
        logger.info(f"Products Built: {len(built_products)}")
        logger.info("=" * 80)
        
        # Save pipeline results
        results_path = self.workspace / "pipeline_results.json"
        results_path.write_text(json.dumps(results, indent=2))
        logger.info(f"\n💾 Results saved: {results_path}")
        
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
