#!/usr/bin/env python3
"""
Data Intelligence Service — Market Research, Competitive Analysis & Business Intelligence

Revenue Model: B2B SaaS (€200-2000/month per client)

Features:
1. Competitor monitoring (pricing, features, marketing)
2. Market trend analysis (Reddit, HN, Twitter, Product Hunt)
3. Customer sentiment tracking (reviews, social media)
4. Pricing intelligence (dynamic pricing recommendations)
5. SEO/keyword tracking
6. Lead generation (web scraping, enrichment)
7. Automated reports (daily/weekly/monthly)
8. API access for real-time data

Target Clients:
- SaaS companies (track competitors)
- E-commerce (pricing optimization)
- Marketing agencies (client reports)
- Investors/VCs (market research)

Tech Stack:
- Scraping: Scrapy, Selenium, Playwright
- Data storage: PostgreSQL + TimescaleDB (time-series)
- NLP: sentiment analysis (transformers)
- Visualization: Plotly, Grafana
- API: FastAPI
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Competitor:
    """Competitor profile"""
    competitor_id: str
    name: str
    website: str
    
    # Pricing
    pricing_tiers: List[Dict] = field(default_factory=list)
    lowest_price: float = 0.0
    highest_price: float = 0.0
    
    # Features
    features: List[str] = field(default_factory=list)
    unique_features: List[str] = field(default_factory=list)
    
    # Marketing
    marketing_channels: List[str] = field(default_factory=list)
    social_followers: Dict[str, int] = field(default_factory=dict)
    
    # Metrics
    estimated_revenue: float = 0.0
    estimated_customers: int = 0
    growth_rate: float = 0.0  # %
    
    # Last updated
    last_scraped: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        return {
            'competitor_id': self.competitor_id,
            'name': self.name,
            'website': self.website,
            'pricing': {
                'tiers': self.pricing_tiers,
                'range': f"€{self.lowest_price}-{self.highest_price}/month",
            },
            'features': {
                'total': len(self.features),
                'unique': self.unique_features,
            },
            'marketing': {
                'channels': self.marketing_channels,
                'social': self.social_followers,
            },
            'metrics': {
                'revenue': self.estimated_revenue,
                'customers': self.estimated_customers,
                'growth': f"{self.growth_rate:+.1f}%",
            },
            'last_updated': self.last_scraped.isoformat() if self.last_scraped else None,
        }


@dataclass
class MarketTrend:
    """Market trend/signal"""
    trend_id: str
    timestamp: datetime
    source: str  # reddit, hn, twitter, product_hunt
    
    # Trend data
    keyword: str
    mentions: int
    sentiment: float  # -1.0 (negative) to +1.0 (positive)
    
    # Analysis
    trend_direction: str  # up, down, stable
    opportunity_score: float  # 0-100
    
    def to_dict(self) -> Dict:
        return {
            'trend_id': self.trend_id,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source,
            'keyword': self.keyword,
            'mentions': self.mentions,
            'sentiment': round(self.sentiment, 2),
            'trend_direction': self.trend_direction,
            'opportunity_score': round(self.opportunity_score, 2),
        }


class DataIntelligenceService:
    """
    Market intelligence and competitive analysis service.
    
    Usage:
        intel = DataIntelligenceService()
        
        # Add competitor
        competitor = intel.add_competitor("Competitor Inc", "https://competitor.com")
        
        # Track trend
        trend = intel.track_trend("AI automation", source="reddit", mentions=250)
        
        # Generate report
        report = intel.generate_competitive_report()
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".jarvismax" / "intel"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.competitors: Dict[str, Competitor] = {}
        self.trends: List[MarketTrend] = []
        
        self._load_state()
    
    def _load_state(self):
        """Load competitors and trends from disk"""
        competitors_file = self.data_dir / "competitors.json"
        trends_file = self.data_dir / "trends.json"
        
        if competitors_file.exists():
            with open(competitors_file) as f:
                data = json.load(f)
                for comp_data in data:
                    comp = Competitor(
                        competitor_id=comp_data['competitor_id'],
                        name=comp_data['name'],
                        website=comp_data['website'],
                        pricing_tiers=comp_data['pricing']['tiers'],
                        features=comp_data['features'].get('all', []),
                        unique_features=comp_data['features'].get('unique', []),
                        last_scraped=datetime.fromisoformat(comp_data['last_updated']) if comp_data.get('last_updated') else None,
                    )
                    self.competitors[comp.competitor_id] = comp
        
        if trends_file.exists():
            with open(trends_file) as f:
                data = json.load(f)
                for trend_data in data:
                    trend = MarketTrend(
                        trend_id=trend_data['trend_id'],
                        timestamp=datetime.fromisoformat(trend_data['timestamp']),
                        source=trend_data['source'],
                        keyword=trend_data['keyword'],
                        mentions=trend_data['mentions'],
                        sentiment=trend_data['sentiment'],
                        trend_direction=trend_data['trend_direction'],
                        opportunity_score=trend_data['opportunity_score'],
                    )
                    self.trends.append(trend)
    
    def _save_state(self):
        """Save competitors and trends to disk"""
        competitors_file = self.data_dir / "competitors.json"
        trends_file = self.data_dir / "trends.json"
        
        with open(competitors_file, 'w') as f:
            json.dump([c.to_dict() for c in self.competitors.values()], f, indent=2)
        
        with open(trends_file, 'w') as f:
            json.dump([t.to_dict() for t in self.trends[-500:]], f, indent=2)  # Keep last 500
    
    def add_competitor(
        self,
        name: str,
        website: str,
        pricing_tiers: Optional[List[Dict]] = None,
        features: Optional[List[str]] = None,
    ) -> Competitor:
        """Add competitor to monitoring"""
        competitor_id = hashlib.md5(name.encode()).hexdigest()[:12]
        
        competitor = Competitor(
            competitor_id=competitor_id,
            name=name,
            website=website,
            pricing_tiers=pricing_tiers or [],
            features=features or [],
            last_scraped=datetime.now(),
        )
        
        # Calculate pricing range
        if pricing_tiers:
            prices = [tier.get('price', 0) for tier in pricing_tiers]
            competitor.lowest_price = min(prices)
            competitor.highest_price = max(prices)
        
        self.competitors[competitor_id] = competitor
        self._save_state()
        
        logger.info(f"✅ Competitor added: {name}")
        
        return competitor
    
    def track_trend(
        self,
        keyword: str,
        source: str,
        mentions: int,
        sentiment: float = 0.0,
    ) -> MarketTrend:
        """Track market trend"""
        trend_id = hashlib.md5(f"{keyword}{datetime.now().isoformat()}".encode()).hexdigest()[:16]
        
        # Analyze trend direction
        # (In real implementation: compare with historical data)
        trend_direction = "up" if mentions > 100 else "stable"
        
        # Calculate opportunity score
        # High mentions + positive sentiment = high opportunity
        opportunity_score = min(100, (mentions / 10) + (sentiment * 50))
        
        trend = MarketTrend(
            trend_id=trend_id,
            timestamp=datetime.now(),
            source=source,
            keyword=keyword,
            mentions=mentions,
            sentiment=sentiment,
            trend_direction=trend_direction,
            opportunity_score=opportunity_score,
        )
        
        self.trends.append(trend)
        self._save_state()
        
        logger.info(f"📊 Trend tracked: {keyword} ({mentions} mentions, {sentiment:+.2f} sentiment)")
        
        return trend
    
    def generate_competitive_report(self) -> str:
        """Generate competitive analysis report"""
        report = f"""# 📊 COMPETITIVE INTELLIGENCE REPORT

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 🎯 Competitors ({len(self.competitors)})

"""
        
        for comp in sorted(self.competitors.values(), key=lambda c: c.estimated_revenue, reverse=True):
            report += f"""### {comp.name}

- **Website:** {comp.website}
- **Pricing:** €{comp.lowest_price}-{comp.highest_price}/month ({len(comp.pricing_tiers)} tiers)
- **Features:** {len(comp.features)} total
- **Unique Features:** {', '.join(comp.unique_features[:3])}
- **Estimated Revenue:** €{comp.estimated_revenue:,.0f}/month
- **Growth:** {comp.growth_rate:+.1f}%
- **Last Updated:** {comp.last_scraped.strftime('%Y-%m-%d') if comp.last_scraped else 'Never'}

---

"""
        
        # Market trends
        recent_trends = [t for t in self.trends if t.timestamp > datetime.now() - timedelta(days=7)]
        
        report += f"""
## 📈 Market Trends (Last 7 Days)

**Total Trends Tracked:** {len(recent_trends)}

"""
        
        # Top trends by opportunity score
        top_trends = sorted(recent_trends, key=lambda t: t.opportunity_score, reverse=True)[:10]
        
        for trend in top_trends:
            sentiment_emoji = "😊" if trend.sentiment > 0.3 else "😐" if trend.sentiment > -0.3 else "😞"
            direction_emoji = "📈" if trend.trend_direction == "up" else "📉" if trend.trend_direction == "down" else "➡️"
            
            report += f"""### {trend.keyword}

- **Source:** {trend.source}
- **Mentions:** {trend.mentions} {direction_emoji}
- **Sentiment:** {trend.sentiment:+.2f} {sentiment_emoji}
- **Opportunity Score:** {trend.opportunity_score:.0f}/100
- **Timestamp:** {trend.timestamp.strftime('%Y-%m-%d %H:%M')}

---

"""
        
        report += """
## 💡 Recommendations

"""
        
        # Generate recommendations based on trends and competitors
        if top_trends:
            best_trend = top_trends[0]
            report += f"""### 1. Capitalize on "{best_trend.keyword}"

This trend has {best_trend.mentions} mentions with {best_trend.sentiment:+.2f} sentiment. Consider:
- Building a feature targeting this pain point
- Creating content marketing around this keyword
- SEO optimization for this search term

"""
        
        if len(self.competitors) > 0:
            report += f"""### 2. Competitive Positioning

You are tracking {len(self.competitors)} competitors. Key insights:
- Pricing range: €{min(c.lowest_price for c in self.competitors.values())}-{max(c.highest_price for c in self.competitors.values())}/month
- Average features: {sum(len(c.features) for c in self.competitors.values()) / len(self.competitors):.0f}

**Recommendation:** Position yourself at €{(min(c.lowest_price for c in self.competitors.values()) + max(c.highest_price for c in self.competitors.values())) / 2:.0f}/month with {int(sum(len(c.features) for c in self.competitors.values()) / len(self.competitors)) + 5} features.

"""
        
        report += """
---

**Generated by JarvisMax Data Intelligence Service**  
**Version:** 1.0.0
"""
        
        return report
    
    def save_report(self, report: str) -> Path:
        """Save report to file"""
        report_path = self.data_dir / f"competitive_report_{datetime.now().strftime('%Y%m%d')}.md"
        report_path.write_text(report)
        
        logger.info(f"💾 Report saved: {report_path}")
        
        return report_path


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Data Intelligence Service")
    parser.add_argument('--add-competitor', help='Add competitor (name)')
    parser.add_argument('--website', help='Competitor website')
    parser.add_argument('--track-trend', help='Track trend (keyword)')
    parser.add_argument('--source', default='reddit', help='Trend source')
    parser.add_argument('--mentions', type=int, default=100, help='Number of mentions')
    parser.add_argument('--report', action='store_true', help='Generate report')
    args = parser.parse_args()
    
    intel = DataIntelligenceService()
    
    if args.add_competitor and args.website:
        competitor = intel.add_competitor(args.add_competitor, args.website)
        print(f"✅ Competitor added: {competitor.name}")
    
    if args.track_trend:
        trend = intel.track_trend(args.track_trend, args.source, args.mentions)
        print(f"📊 Trend tracked: {trend.keyword}")
    
    if args.report or not (args.add_competitor or args.track_trend):
        report = intel.generate_competitive_report()
        print(report)
        intel.save_report(report)


if __name__ == '__main__':
    main()
