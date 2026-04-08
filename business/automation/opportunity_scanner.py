#!/usr/bin/env python3
"""
Opportunity Scanner — Discover profitable SaaS ideas

Scrapes:
- Product Hunt (trending, top posts)
- Reddit (r/SaaS, r/Entrepreneur, r/startups)
- Hacker News (Show HN, Ask HN)
- Indie Hackers

Identifies:
- Recurring pain points
- High-demand problems
- Low-competition niches
- Monetizable solutions

Scoring system:
- Demand score (upvotes, comments, mentions)
- Competition score (existing solutions)
- Feasibility score (tech complexity, time to build)
- Monetization score (willingness to pay)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class Opportunity:
    """A business opportunity"""
    title: str
    description: str
    source: str  # product_hunt, reddit, hackernews
    url: str
    discovered_at: datetime
    
    # Metrics
    upvotes: int = 0
    comments: int = 0
    mentions: int = 1
    
    # Scores (0-100)
    demand_score: float = 0.0
    competition_score: float = 0.0
    feasibility_score: float = 0.0
    monetization_score: float = 0.0
    
    # Overall
    total_score: float = 0.0
    
    # Tags
    tags: List[str] = field(default_factory=list)
    pain_points: List[str] = field(default_factory=list)
    
    def calculate_total_score(self):
        """Calculate weighted total score"""
        weights = {
            'demand': 0.35,
            'competition': 0.20,
            'feasibility': 0.25,
            'monetization': 0.20,
        }
        
        self.total_score = (
            self.demand_score * weights['demand'] +
            self.competition_score * weights['competition'] +
            self.feasibility_score * weights['feasibility'] +
            self.monetization_score * weights['monetization']
        )
    
    def to_dict(self) -> Dict:
        """Serialize to dict"""
        return {
            'title': self.title,
            'description': self.description,
            'source': self.source,
            'url': self.url,
            'discovered_at': self.discovered_at.isoformat(),
            'metrics': {
                'upvotes': self.upvotes,
                'comments': self.comments,
                'mentions': self.mentions,
            },
            'scores': {
                'demand': round(self.demand_score, 2),
                'competition': round(self.competition_score, 2),
                'feasibility': round(self.feasibility_score, 2),
                'monetization': round(self.monetization_score, 2),
                'total': round(self.total_score, 2),
            },
            'tags': self.tags,
            'pain_points': self.pain_points,
        }


class OpportunityScanner:
    """
    Scan multiple sources for business opportunities.
    
    Usage:
        scanner = OpportunityScanner()
        opportunities = scanner.scan_all(days_back=30)
        
        # Get top opportunities
        top_10 = scanner.get_top_opportunities(opportunities, limit=10)
        
        # Save results
        scanner.save_opportunities(opportunities, "opportunities.json")
    """
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or Path.home() / ".jarvismax" / "opportunities"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # User agent for requests
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (compatible; JarvisMaxBot/1.0; +https://github.com/UniTy01/Jarvismax-master)'
        }
    
    def scan_all(self, days_back: int = 30) -> List[Opportunity]:
        """
        Scan all sources for opportunities.
        
        Args:
            days_back: How many days back to search
        
        Returns:
            List of opportunities
        """
        logger.info(f"🔍 Scanning opportunities (last {days_back} days)...")
        
        opportunities = []
        
        # Product Hunt
        logger.info("📱 Scanning Product Hunt...")
        try:
            ph_opps = self.scan_product_hunt(days_back)
            opportunities.extend(ph_opps)
            logger.info(f"  Found {len(ph_opps)} opportunities")
        except Exception as e:
            logger.error(f"  Failed: {e}")
        
        # Reddit
        logger.info("🔴 Scanning Reddit...")
        try:
            reddit_opps = self.scan_reddit(days_back)
            opportunities.extend(reddit_opps)
            logger.info(f"  Found {len(reddit_opps)} opportunities")
        except Exception as e:
            logger.error(f"  Failed: {e}")
        
        # Hacker News
        logger.info("🟠 Scanning Hacker News...")
        try:
            hn_opps = self.scan_hackernews(days_back)
            opportunities.extend(hn_opps)
            logger.info(f"  Found {len(hn_opps)} opportunities")
        except Exception as e:
            logger.error(f"  Failed: {e}")
        
        # Calculate scores
        logger.info("📊 Calculating scores...")
        for opp in opportunities:
            self._score_opportunity(opp)
        
        logger.info(f"✅ Total opportunities found: {len(opportunities)}")
        
        return opportunities
    
    def scan_product_hunt(self, days_back: int = 30) -> List[Opportunity]:
        """
        Scan Product Hunt for trending products and pain points.
        
        Note: Product Hunt API requires auth. Using public RSS feed instead.
        """
        opportunities = []
        
        try:
            # Product Hunt RSS feed
            url = "https://www.producthunt.com/feed"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'xml')
            
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            for item in soup.find_all('item')[:50]:  # Top 50 items
                try:
                    title = item.title.text if item.title else "Unknown"
                    description = item.description.text if item.description else ""
                    link = item.link.text if item.link else ""
                    pub_date_str = item.pubDate.text if item.pubDate else ""
                    
                    # Parse date
                    try:
                        pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                        pub_date = pub_date.replace(tzinfo=None)  # Remove timezone
                    except:
                        pub_date = datetime.now()
                    
                    if pub_date < cutoff_date:
                        continue
                    
                    # Extract pain points from description
                    pain_points = self._extract_pain_points(description)
                    
                    opp = Opportunity(
                        title=title,
                        description=description[:500],  # Truncate
                        source="product_hunt",
                        url=link,
                        discovered_at=pub_date,
                        pain_points=pain_points,
                        tags=self._extract_tags(title + " " + description),
                    )
                    
                    opportunities.append(opp)
                
                except Exception as e:
                    logger.debug(f"Failed to parse item: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Product Hunt scan failed: {e}")
        
        return opportunities
    
    def scan_reddit(self, days_back: int = 30) -> List[Opportunity]:
        """
        Scan Reddit for pain points and business ideas.
        
        Subreddits:
        - r/SaaS
        - r/Entrepreneur
        - r/startups
        - r/SideProject
        """
        opportunities = []
        
        subreddits = ['SaaS', 'Entrepreneur', 'startups', 'SideProject']
        
        for subreddit in subreddits:
            try:
                # Reddit JSON API (no auth needed for public posts)
                url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=25"
                response = requests.get(url, headers=self.headers, timeout=10)
                response.raise_for_status()
                
                data = response.json()
                
                cutoff_timestamp = (datetime.now() - timedelta(days=days_back)).timestamp()
                
                for post in data.get('data', {}).get('children', []):
                    post_data = post.get('data', {})
                    
                    created_utc = post_data.get('created_utc', 0)
                    if created_utc < cutoff_timestamp:
                        continue
                    
                    title = post_data.get('title', '')
                    selftext = post_data.get('selftext', '')
                    url = f"https://www.reddit.com{post_data.get('permalink', '')}"
                    upvotes = post_data.get('ups', 0)
                    comments = post_data.get('num_comments', 0)
                    
                    # Filter for pain points / problems
                    if not self._is_problem_post(title, selftext):
                        continue
                    
                    pain_points = self._extract_pain_points(title + " " + selftext)
                    
                    opp = Opportunity(
                        title=title,
                        description=selftext[:500],
                        source=f"reddit_r_{subreddit}",
                        url=url,
                        discovered_at=datetime.fromtimestamp(created_utc),
                        upvotes=upvotes,
                        comments=comments,
                        pain_points=pain_points,
                        tags=self._extract_tags(title + " " + selftext),
                    )
                    
                    opportunities.append(opp)
                
                time.sleep(1)  # Rate limiting
            
            except Exception as e:
                logger.error(f"Reddit r/{subreddit} scan failed: {e}")
        
        return opportunities
    
    def scan_hackernews(self, days_back: int = 30) -> List[Opportunity]:
        """
        Scan Hacker News for Show HN and Ask HN posts.
        """
        opportunities = []
        
        try:
            # HN Algolia API
            cutoff_timestamp = int((datetime.now() - timedelta(days=days_back)).timestamp())
            
            # Show HN
            url = f"https://hn.algolia.com/api/v1/search?tags=show_hn&numericFilters=created_at_i>{cutoff_timestamp}&hitsPerPage=50"
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            for hit in data.get('hits', []):
                title = hit.get('title', '')
                url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
                created_at = datetime.fromtimestamp(hit.get('created_at_i', 0))
                points = hit.get('points', 0)
                comments = hit.get('num_comments', 0)
                
                # Extract description from story_text or first comment
                description = hit.get('story_text', '') or hit.get('comment_text', '')
                
                pain_points = self._extract_pain_points(title + " " + description)
                
                opp = Opportunity(
                    title=title,
                    description=description[:500],
                    source="hackernews_show",
                    url=url,
                    discovered_at=created_at,
                    upvotes=points,
                    comments=comments,
                    pain_points=pain_points,
                    tags=self._extract_tags(title + " " + description),
                )
                
                opportunities.append(opp)
        
        except Exception as e:
            logger.error(f"Hacker News scan failed: {e}")
        
        return opportunities
    
    def _is_problem_post(self, title: str, text: str) -> bool:
        """Check if post describes a problem/pain point"""
        content = (title + " " + text).lower()
        
        problem_keywords = [
            'problem', 'issue', 'struggle', 'difficult', 'pain', 'frustrating',
            'annoying', 'hate', 'need', 'wish', 'looking for', 'help with',
            'solution', 'better way', 'improve', 'automate', 'tedious',
        ]
        
        return any(keyword in content for keyword in problem_keywords)
    
    def _extract_pain_points(self, text: str) -> List[str]:
        """Extract pain points from text using pattern matching"""
        pain_points = []
        
        # Patterns
        patterns = [
            r"(?:problem|issue|pain point)[\s:]+([^.!?\n]{10,100})",
            r"(?:struggle|difficult|hard)[\s]+(?:to|with)[\s]+([^.!?\n]{10,100})",
            r"(?:wish|need|want)[\s]+(?:to|a)[\s]+([^.!?\n]{10,100})",
            r"(?:hate|annoying|frustrating)[\s]+(?:when|that|how)[\s]+([^.!?\n]{10,100})",
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            pain_points.extend([m.strip() for m in matches if len(m.strip()) > 15])
        
        return pain_points[:5]  # Top 5
    
    def _extract_tags(self, text: str) -> List[str]:
        """Extract relevant tags from text"""
        text_lower = text.lower()
        
        tag_keywords = {
            'saas': ['saas', 'software as a service', 'subscription'],
            'automation': ['automate', 'automation', 'automatic'],
            'productivity': ['productivity', 'efficient', 'workflow'],
            'marketing': ['marketing', 'seo', 'ads', 'campaign'],
            'analytics': ['analytics', 'tracking', 'metrics', 'data'],
            'developer_tools': ['api', 'developer', 'sdk', 'library'],
            'ai': ['ai', 'machine learning', 'gpt', 'llm'],
            'no_code': ['no-code', 'nocode', 'drag and drop'],
            'e-commerce': ['ecommerce', 'e-commerce', 'shopify', 'store'],
            'payment': ['payment', 'stripe', 'billing', 'invoice'],
        }
        
        tags = []
        for tag, keywords in tag_keywords.items():
            if any(kw in text_lower for kw in keywords):
                tags.append(tag)
        
        return tags
    
    def _score_opportunity(self, opp: Opportunity):
        """Calculate all scores for an opportunity"""
        
        # Demand score (based on engagement)
        demand = min(100, (opp.upvotes * 2 + opp.comments * 5 + len(opp.pain_points) * 10))
        opp.demand_score = demand
        
        # Competition score (inverse — less competition = higher score)
        # TODO: Implement Google search / domain check for existing solutions
        # For now, use heuristic: popular tags = more competition
        competition_penalty = len(opp.tags) * 5
        opp.competition_score = max(0, 100 - competition_penalty)
        
        # Feasibility score (based on complexity indicators)
        # Simple heuristics for now
        complexity_keywords = ['ml', 'ai', 'blockchain', 'crypto', 'hardware']
        complexity_penalty = sum(20 for kw in complexity_keywords if kw in opp.description.lower())
        opp.feasibility_score = max(20, 100 - complexity_penalty)
        
        # Monetization score (willingness to pay indicators)
        monetization_keywords = ['paid', 'pricing', 'subscription', 'premium', 'upgrade', 'business']
        monetization_boost = sum(15 for kw in monetization_keywords if kw in opp.description.lower())
        opp.monetization_score = min(100, 50 + monetization_boost)
        
        # Calculate total
        opp.calculate_total_score()
    
    def get_top_opportunities(self, opportunities: List[Opportunity], limit: int = 10) -> List[Opportunity]:
        """Get top N opportunities by total score"""
        sorted_opps = sorted(opportunities, key=lambda x: x.total_score, reverse=True)
        return sorted_opps[:limit]
    
    def save_opportunities(self, opportunities: List[Opportunity], filename: str = "opportunities.json"):
        """Save opportunities to JSON file"""
        filepath = self.cache_dir / filename
        
        data = {
            'generated_at': datetime.now().isoformat(),
            'total_opportunities': len(opportunities),
            'opportunities': [opp.to_dict() for opp in opportunities]
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"💾 Saved {len(opportunities)} opportunities to {filepath}")
        
        return filepath
    
    def generate_report(self, opportunities: List[Opportunity], top_n: int = 10) -> str:
        """Generate a markdown report of top opportunities"""
        top_opps = self.get_top_opportunities(opportunities, top_n)
        
        report = f"""# 🚀 BUSINESS OPPORTUNITIES REPORT

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Total Opportunities Scanned:** {len(opportunities)}  
**Top Opportunities:** {top_n}

---

"""
        
        for i, opp in enumerate(top_opps, 1):
            report += f"""## {i}. {opp.title}

**Source:** {opp.source}  
**URL:** {opp.url}  
**Discovered:** {opp.discovered_at.strftime('%Y-%m-%d')}

**Metrics:**
- Upvotes: {opp.upvotes}
- Comments: {opp.comments}
- Mentions: {opp.mentions}

**Scores:**
- 🔥 Demand: {opp.demand_score:.1f}/100
- 🏆 Competition: {opp.competition_score:.1f}/100
- 🛠️  Feasibility: {opp.feasibility_score:.1f}/100
- 💰 Monetization: {opp.monetization_score:.1f}/100
- **⭐ TOTAL: {opp.total_score:.1f}/100**

**Tags:** {', '.join(opp.tags) if opp.tags else 'None'}

**Pain Points:**
{chr(10).join(['- ' + pp for pp in opp.pain_points]) if opp.pain_points else '- None extracted'}

**Description:**
{opp.description[:300]}...

---

"""
        
        return report


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Scan for business opportunities")
    parser.add_argument('--days', type=int, default=30, help='Days back to scan (default: 30)')
    parser.add_argument('--top', type=int, default=10, help='Top N opportunities (default: 10)')
    parser.add_argument('--output', default='opportunities.json', help='Output filename')
    args = parser.parse_args()
    
    scanner = OpportunityScanner()
    
    # Scan all sources
    opportunities = scanner.scan_all(days_back=args.days)
    
    # Save to JSON
    scanner.save_opportunities(opportunities, args.output)
    
    # Generate report
    report = scanner.generate_report(opportunities, args.top)
    
    report_path = scanner.cache_dir / "report.md"
    report_path.write_text(report)
    
    print(report)
    print(f"\n📄 Full report saved to: {report_path}")
    print(f"💾 Raw data saved to: {scanner.cache_dir / args.output}")


if __name__ == '__main__':
    main()
