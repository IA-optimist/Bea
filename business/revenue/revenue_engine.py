#!/usr/bin/env python3
"""
Revenue Engine — Track and optimize micro-SaaS revenue

Features:
1. Stripe revenue tracking
2. MRR/ARR calculation
3. Churn analysis
4. Revenue forecasting
5. Alert system (milestones, anomalies)
6. Portfolio dashboard

Target metrics:
- MRR (Monthly Recurring Revenue)
- ARR (Annual Recurring Revenue)
- LTV (Lifetime Value)
- CAC (Customer Acquisition Cost)
- Churn rate
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class RevenueMetrics:
    """Revenue metrics for a product"""
    product_name: str
    period: str  # e.g., "2026-04"
    
    # Core metrics
    mrr: float = 0.0  # Monthly Recurring Revenue
    arr: float = 0.0  # Annual Recurring Revenue
    
    # Customers
    active_subscriptions: int = 0
    new_subscriptions: int = 0
    churned_subscriptions: int = 0
    churn_rate: float = 0.0
    
    # Revenue breakdown
    revenue_breakdown: Dict[str, float] = field(default_factory=dict)
    
    # Growth
    mrr_growth: float = 0.0  # % month-over-month
    
    def calculate_arr(self):
        """Calculate ARR from MRR"""
        self.arr = self.mrr * 12
    
    def calculate_churn_rate(self):
        """Calculate churn rate"""
        if self.active_subscriptions > 0:
            self.churn_rate = (self.churned_subscriptions / self.active_subscriptions) * 100
    
    def to_dict(self) -> Dict:
        return {
            'product_name': self.product_name,
            'period': self.period,
            'mrr': round(self.mrr, 2),
            'arr': round(self.arr, 2),
            'active_subscriptions': self.active_subscriptions,
            'new_subscriptions': self.new_subscriptions,
            'churned_subscriptions': self.churned_subscriptions,
            'churn_rate': round(self.churn_rate, 2),
            'revenue_breakdown': {k: round(v, 2) for k, v in self.revenue_breakdown.items()},
            'mrr_growth': round(self.mrr_growth, 2),
        }


@dataclass
class PortfolioMetrics:
    """Metrics for entire product portfolio"""
    period: str
    total_mrr: float = 0.0
    total_arr: float = 0.0
    total_products: int = 0
    total_customers: int = 0
    average_churn_rate: float = 0.0
    
    products: List[RevenueMetrics] = field(default_factory=list)
    
    def calculate_totals(self):
        """Calculate portfolio totals"""
        self.total_mrr = sum(p.mrr for p in self.products)
        self.total_arr = sum(p.arr for p in self.products)
        self.total_products = len(self.products)
        self.total_customers = sum(p.active_subscriptions for p in self.products)
        
        if self.products:
            self.average_churn_rate = sum(p.churn_rate for p in self.products) / len(self.products)
    
    def to_dict(self) -> Dict:
        return {
            'period': self.period,
            'total_mrr': round(self.total_mrr, 2),
            'total_arr': round(self.total_arr, 2),
            'total_products': self.total_products,
            'total_customers': self.total_customers,
            'average_churn_rate': round(self.average_churn_rate, 2),
            'products': [p.to_dict() for p in self.products],
        }


class RevenueEngine:
    """
    Track and analyze revenue across product portfolio.
    
    Usage:
        engine = RevenueEngine()
        
        # Add product revenue data
        metrics = engine.calculate_metrics("my-saas", stripe_api_key)
        
        # Get portfolio overview
        portfolio = engine.get_portfolio_metrics()
        
        # Check alerts
        alerts = engine.check_alerts(portfolio)
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".beamax" / "revenue"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.history_file = self.data_dir / "revenue_history.json"
        self.history = self._load_history()
    
    def _load_history(self) -> List[Dict]:
        """Load historical revenue data"""
        if self.history_file.exists():
            try:
                with open(self.history_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load history: {e}")
        return []
    
    def _save_history(self):
        """Save revenue history"""
        with open(self.history_file, 'w') as f:
            json.dump(self.history, f, indent=2)
    
    def calculate_metrics(self, product_name: str, stripe_api_key: Optional[str] = None) -> RevenueMetrics:
        """
        Calculate revenue metrics for a product.
        
        Args:
            product_name: Product identifier
            stripe_api_key: Stripe API key (or from env)
        
        Returns:
            RevenueMetrics
        """
        logger.info(f"💰 Calculating revenue for: {product_name}")
        
        period = datetime.now().strftime("%Y-%m")
        
        metrics = RevenueMetrics(
            product_name=product_name,
            period=period,
        )
        
        # Try to get real Stripe data
        if stripe_api_key or os.getenv("STRIPE_SECRET_KEY"):
            try:
                stripe_data = self._fetch_stripe_data(product_name, stripe_api_key)
                metrics.mrr = stripe_data.get('mrr', 0.0)
                metrics.active_subscriptions = stripe_data.get('active_subs', 0)
                metrics.new_subscriptions = stripe_data.get('new_subs', 0)
                metrics.churned_subscriptions = stripe_data.get('churned_subs', 0)
                metrics.revenue_breakdown = stripe_data.get('breakdown', {})
            except Exception as e:
                logger.warning(f"Failed to fetch Stripe data: {e}")
                # Use mock data for now
                metrics.mrr = 0.0
        
        # Calculate derived metrics
        metrics.calculate_arr()
        metrics.calculate_churn_rate()
        
        # Calculate growth (compare to last month)
        previous = self._get_previous_month_mrr(product_name)
        if previous > 0:
            metrics.mrr_growth = ((metrics.mrr - previous) / previous) * 100
        
        logger.info(f"   MRR: ${metrics.mrr:.2f} | ARR: ${metrics.arr:.2f}")
        logger.info(f"   Customers: {metrics.active_subscriptions} | Churn: {metrics.churn_rate:.1f}%")
        
        # Save to history
        self.history.append({
            'timestamp': datetime.now().isoformat(),
            'product': product_name,
            'metrics': metrics.to_dict(),
        })
        self._save_history()
        
        return metrics
    
    def _fetch_stripe_data(self, product_name: str, api_key: Optional[str] = None) -> Dict:
        """
        Fetch real Stripe subscription data.
        
        Note: Requires stripe library installed and valid API key.
        """
        try:
            import stripe
            
            stripe.api_key = api_key or os.getenv("STRIPE_SECRET_KEY")
            
            if not stripe.api_key:
                raise ValueError("Stripe API key not provided")
            
            # Fetch active subscriptions
            subs = stripe.Subscription.list(status='active', limit=100)
            
            active_count = len(subs.data)
            
            # Calculate MRR
            mrr = 0.0
            breakdown = {}
            
            for sub in subs.data:
                for item in sub['items']['data']:
                    price = item['price']
                    amount = price['unit_amount'] / 100  # Convert cents to dollars
                    
                    # Convert to monthly
                    if price['recurring']['interval'] == 'month':
                        monthly_amount = amount
                    elif price['recurring']['interval'] == 'year':
                        monthly_amount = amount / 12
                    else:
                        monthly_amount = amount  # Default
                    
                    mrr += monthly_amount
                    
                    # Breakdown by plan
                    plan_name = price.get('nickname', 'Unknown')
                    breakdown[plan_name] = breakdown.get(plan_name, 0) + monthly_amount
            
            # Get new subscriptions (last 30 days)
            thirty_days_ago = int((datetime.now() - timedelta(days=30)).timestamp())
            new_subs = stripe.Subscription.list(created={'gte': thirty_days_ago}, limit=100)
            new_count = len(new_subs.data)
            
            # Get canceled subscriptions (last 30 days)
            canceled_subs = stripe.Subscription.list(
                status='canceled',
                canceled_at={'gte': thirty_days_ago},
                limit=100
            )
            churned_count = len(canceled_subs.data)
            
            return {
                'mrr': mrr,
                'active_subs': active_count,
                'new_subs': new_count,
                'churned_subs': churned_count,
                'breakdown': breakdown,
            }
        
        except ImportError:
            logger.warning("Stripe library not installed (pip install stripe)")
            return {}
        except Exception as e:
            logger.error(f"Stripe API error: {e}")
            return {}
    
    def _get_previous_month_mrr(self, product_name: str) -> float:
        """Get MRR from previous month"""
        if not self.history:
            return 0.0
        
        # Find most recent entry for this product
        product_entries = [
            h for h in self.history
            if h.get('product') == product_name
        ]
        
        if len(product_entries) >= 2:
            # Get second-to-last entry
            return product_entries[-2].get('metrics', {}).get('mrr', 0.0)
        
        return 0.0
    
    def get_portfolio_metrics(self) -> PortfolioMetrics:
        """Get metrics for entire product portfolio"""
        logger.info("📊 Calculating portfolio metrics...")
        
        period = datetime.now().strftime("%Y-%m")
        
        # Get all products with revenue this month
        products_set = set()
        for entry in self.history:
            if entry.get('metrics', {}).get('period') == period:
                products_set.add(entry.get('product'))
        
        # Calculate metrics for each product
        product_metrics = []
        for product in products_set:
            # Get latest metrics for this product this month
            latest = None
            for entry in reversed(self.history):
                if (entry.get('product') == product and
                    entry.get('metrics', {}).get('period') == period):
                    latest = entry.get('metrics')
                    break
            
            if latest:
                metrics = RevenueMetrics(
                    product_name=latest['product_name'],
                    period=latest['period'],
                    mrr=latest['mrr'],
                    arr=latest['arr'],
                    active_subscriptions=latest['active_subscriptions'],
                    new_subscriptions=latest['new_subscriptions'],
                    churned_subscriptions=latest['churned_subscriptions'],
                    churn_rate=latest['churn_rate'],
                    revenue_breakdown=latest['revenue_breakdown'],
                    mrr_growth=latest['mrr_growth'],
                )
                product_metrics.append(metrics)
        
        # Create portfolio
        portfolio = PortfolioMetrics(
            period=period,
            products=product_metrics,
        )
        portfolio.calculate_totals()
        
        logger.info(f"   Total MRR: ${portfolio.total_mrr:.2f}")
        logger.info(f"   Total ARR: ${portfolio.total_arr:.2f}")
        logger.info(f"   Products: {portfolio.total_products}")
        logger.info(f"   Customers: {portfolio.total_customers}")
        
        return portfolio
    
    def check_alerts(self, portfolio: PortfolioMetrics) -> List[Dict]:
        """Check for revenue alerts / milestones"""
        alerts = []
        
        # Milestone: €1k MRR
        if 900 <= portfolio.total_mrr < 1000:
            alerts.append({
                'type': 'milestone_approaching',
                'title': '🎯 €1k MRR Milestone Approaching',
                'message': f'Current MRR: €{portfolio.total_mrr:.2f} (€{1000 - portfolio.total_mrr:.2f} to go!)',
            })
        elif portfolio.total_mrr >= 1000 and portfolio.total_mrr < 1100:
            alerts.append({
                'type': 'milestone_reached',
                'title': '🎉 €1k MRR Milestone Reached!',
                'message': f'Congratulations! Current MRR: €{portfolio.total_mrr:.2f}',
            })
        
        # Milestone: €10k MRR
        if 9500 <= portfolio.total_mrr < 10000:
            alerts.append({
                'type': 'milestone_approaching',
                'title': '🎯 €10k MRR Milestone Approaching',
                'message': f'Current MRR: €{portfolio.total_mrr:.2f} (€{10000 - portfolio.total_mrr:.2f} to go!)',
            })
        elif portfolio.total_mrr >= 10000 and portfolio.total_mrr < 10500:
            alerts.append({
                'type': 'milestone_reached',
                'title': '🎉 €10k MRR Milestone Reached!',
                'message': f'Amazing! Current MRR: €{portfolio.total_mrr:.2f}',
            })
        
        # High churn warning
        if portfolio.average_churn_rate > 10:
            alerts.append({
                'type': 'warning',
                'title': '⚠️ High Churn Rate',
                'message': f'Average churn: {portfolio.average_churn_rate:.1f}% (target: <5%)',
            })
        
        # Negative growth warning
        for product in portfolio.products:
            if product.mrr_growth < -10:
                alerts.append({
                    'type': 'warning',
                    'title': f'⚠️ {product.product_name} Revenue Declining',
                    'message': f'MRR growth: {product.mrr_growth:.1f}% (investigate immediately)',
                })
        
        return alerts
    
    def generate_dashboard(self, portfolio: PortfolioMetrics, alerts: List[Dict]) -> str:
        """Generate markdown dashboard"""
        dashboard = f"""# 💰 REVENUE DASHBOARD — {portfolio.period}

## 🎯 Portfolio Overview

**Total MRR:** €{portfolio.total_mrr:.2f}/month  
**Total ARR:** €{portfolio.total_arr:.2f}/year  
**Products:** {portfolio.total_products}  
**Total Customers:** {portfolio.total_customers}  
**Avg Churn Rate:** {portfolio.average_churn_rate:.1f}%

---

## 📊 Products

"""
        
        for product in sorted(portfolio.products, key=lambda p: p.mrr, reverse=True):
            growth_emoji = '📈' if product.mrr_growth > 0 else '📉' if product.mrr_growth < 0 else '➡️'
            
            dashboard += f"""### {product.product_name}

- **MRR:** €{product.mrr:.2f} {growth_emoji} {product.mrr_growth:+.1f}%
- **ARR:** €{product.arr:.2f}
- **Customers:** {product.active_subscriptions} active
- **New:** {product.new_subscriptions} | **Churned:** {product.churned_subscriptions}
- **Churn Rate:** {product.churn_rate:.1f}%

"""
            
            if product.revenue_breakdown:
                dashboard += "**Revenue Breakdown:**\n"
                for plan, amount in sorted(product.revenue_breakdown.items(), key=lambda x: x[1], reverse=True):
                    dashboard += f"- {plan}: €{amount:.2f}\n"
                dashboard += "\n"
        
        # Alerts
        if alerts:
            dashboard += f"""---

## 🚨 Alerts ({len(alerts)})

"""
            for alert in alerts:
                dashboard += f"""### {alert['title']}
{alert['message']}

"""
        
        # Progress to goal
        goal_mrr = 25000
        progress = (portfolio.total_mrr / goal_mrr) * 100
        
        dashboard += f"""---

## 🎯 Progress to Goal (€25k MRR)

**Current:** €{portfolio.total_mrr:.2f} ({progress:.1f}%)  
**Target:** €{goal_mrr:.2f}  
**Remaining:** €{goal_mrr - portfolio.total_mrr:.2f}

Progress: [{'█' * int(progress // 5)}{'░' * (20 - int(progress // 5))}] {progress:.1f}%

---

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Data Source:** Stripe API + Historical Tracking
"""
        
        return dashboard
    
    def save_dashboard(self, dashboard: str) -> Path:
        """Save dashboard to file"""
        dashboard_path = self.data_dir / "revenue_dashboard.md"
        dashboard_path.write_text(dashboard)
        
        logger.info(f"💾 Dashboard saved: {dashboard_path}")
        
        return dashboard_path


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Revenue tracking and analysis")
    parser.add_argument('--product', help='Product name to track')
    parser.add_argument('--portfolio', action='store_true', help='Show portfolio metrics')
    args = parser.parse_args()
    
    engine = RevenueEngine()
    
    if args.product:
        # Track single product
        metrics = engine.calculate_metrics(args.product)
        print(f"\n💰 {metrics.product_name}")
        print(f"MRR: €{metrics.mrr:.2f} | ARR: €{metrics.arr:.2f}")
        print(f"Customers: {metrics.active_subscriptions}")
        print(f"Churn: {metrics.churn_rate:.1f}%")
        print(f"Growth: {metrics.mrr_growth:+.1f}%\n")
    
    if args.portfolio or not args.product:
        # Show portfolio
        portfolio = engine.get_portfolio_metrics()
        alerts = engine.check_alerts(portfolio)
        dashboard = engine.generate_dashboard(portfolio, alerts)
        
        print(dashboard)
        
        # Save
        engine.save_dashboard(dashboard)


if __name__ == '__main__':
    main()
