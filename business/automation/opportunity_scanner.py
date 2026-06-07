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
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import asyncio

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PlaywrightTimeoutError

logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger(__name__)
log = logger  # M3 emitter alias


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
    Scan multiple sources for business opportunities using Playwright.
    
    Usage:
        scanner = OpportunityScanner()
        opportunities = await scanner.scan_all(days_back=30)
        
        # Get top opportunities
        top_10 = scanner.get_top_opportunities(opportunities, limit=10)
        
        # Save results
        scanner.save_opportunities(opportunities, "opportunities.json")
    """
    
    def __init__(self, cache_dir: Optional[Path] = None, headless: bool = True):
        self.cache_dir = cache_dir or Path.home() / ".beamax" / "opportunities"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        
        # Screenshot directory for errors
        self.screenshot_dir = self.cache_dir / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
    
    async def _setup_browser(self, browser: Browser) -> Page:
        """
        Setup browser page with stealth mode configurations.
        
        Args:
            browser: Playwright browser instance
            
        Returns:
            Configured page
        """
        # Create context with stealth settings
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            locale='en-US',
            timezone_id='America/New_York',
            # Extra stealth
            extra_http_headers={
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
            }
        )
        
        page = await context.new_page()
        
        # Additional JavaScript stealth
        await page.add_init_script("""
            // Override the navigator.webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            // Override the plugins property
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            // Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)
        
        return page
    
    async def _capture_error_screenshot(self, page: Page, error_name: str):
        """Capture screenshot on error for debugging"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            screenshot_path = self.screenshot_dir / f"error_{error_name}_{timestamp}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"📸 Error screenshot saved: {screenshot_path}")
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
    
    async def scan_all(self, days_back: int = 30) -> List[Opportunity]:
        """
        Scan all sources for opportunities.
        
        Args:
            days_back: How many days back to search
        
        Returns:
            List of opportunities
        """
        logger.info(f"🔍 Scanning opportunities (last {days_back} days)...")
        
        opportunities = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            
            try:
                # Product Hunt
                logger.info("📱 Scanning Product Hunt...")
                try:
                    ph_opps = await self.scan_product_hunt(browser, days_back)
                    opportunities.extend(ph_opps)
                    logger.info(f"  Found {len(ph_opps)} opportunities")
                except Exception as e:
                    logger.error(f"  Failed: {e}")
                
                # Reddit
                logger.info("🔴 Scanning Reddit...")
                try:
                    reddit_opps = await self.scan_reddit(browser, days_back)
                    opportunities.extend(reddit_opps)
                    logger.info(f"  Found {len(reddit_opps)} opportunities")
                except Exception as e:
                    logger.error(f"  Failed: {e}")
                
                # Hacker News
                logger.info("🟠 Scanning Hacker News...")
                try:
                    hn_opps = await self.scan_hackernews(browser, days_back)
                    opportunities.extend(hn_opps)
                    logger.info(f"  Found {len(hn_opps)} opportunities")
                except Exception as e:
                    logger.error(f"  Failed: {e}")
                
            finally:
                await browser.close()
        
        # Calculate scores
        logger.info("📊 Calculating scores...")
        for opp in opportunities:
            self._score_opportunity(opp)
        
        logger.info(f"✅ Total opportunities found: {len(opportunities)}")
        
        return opportunities
    
    async def scan_product_hunt(self, browser: Browser, days_back: int = 30) -> List[Opportunity]:
        """
        Scan Product Hunt for trending products and pain points.
        
        Uses Playwright to handle JS-heavy content.
        """
        opportunities = []
        page = await self._setup_browser(browser)
        
        try:
            # Navigate to Product Hunt
            url = "https://www.producthunt.com/"
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # Wait for posts to load
            try:
                await page.wait_for_selector('[data-test="post-item"]', timeout=10000)
            except PlaywrightTimeoutError:
                logger.warning("Product Hunt posts not found with expected selector, trying alternative...")
                await page.wait_for_selector('article, [class*="post"]', timeout=10000)
            
            # Get page content
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            datetime.now() - timedelta(days=days_back)
            
            # Parse posts - Product Hunt structure (adapt selectors as needed)
            posts = soup.find_all(['article', 'div'], class_=lambda x: x and ('post' in str(x).lower() or 'item' in str(x).lower()))
            
            for post in posts[:50]:  # Top 50
                try:
                    # Extract title
                    title_elem = post.find(['h2', 'h3', 'a'], class_=lambda x: x and 'title' in str(x).lower())
                    if not title_elem:
                        title_elem = post.find(['h2', 'h3'])
                    
                    title = title_elem.get_text(strip=True) if title_elem else "Unknown"
                    
                    # Extract description
                    desc_elem = post.find(['p', 'div'], class_=lambda x: x and ('description' in str(x).lower() or 'tagline' in str(x).lower()))
                    description = desc_elem.get_text(strip=True) if desc_elem else ""
                    
                    # Extract link
                    link_elem = post.find('a', href=True)
                    link = link_elem['href'] if link_elem else ""
                    if link and not link.startswith('http'):
                        link = f"https://www.producthunt.com{link}"
                    
                    # Extract metrics
                    upvotes = 0
                    upvote_elem = post.find(['span', 'div'], class_=lambda x: x and 'vote' in str(x).lower())
                    if upvote_elem:
                        upvote_text = upvote_elem.get_text(strip=True)
                        upvotes = int(re.search(r'\d+', upvote_text).group()) if re.search(r'\d+', upvote_text) else 0
                    
                    # Extract pain points
                    pain_points = self._extract_pain_points(description)
                    
                    opp = Opportunity(
                        title=title,
                        description=description[:500],
                        source="product_hunt",
                        url=link or url,
                        discovered_at=datetime.now(),  # PH doesn't easily expose dates without auth
                        upvotes=upvotes,
                        pain_points=pain_points,
                        tags=self._extract_tags(title + " " + description),
                    )
                    
                    opportunities.append(opp)
                
                except Exception as e:
                    logger.debug(f"Failed to parse Product Hunt item: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Product Hunt scan failed: {e}")
            await self._capture_error_screenshot(page, "product_hunt")
        
        finally:
            await page.close()
        
        return opportunities
    
    async def scan_reddit(self, browser: Browser, days_back: int = 30) -> List[Opportunity]:
        """
        Scan Reddit for pain points and business ideas.
        
        Subreddits:
        - r/SaaS
        - r/Entrepreneur
        - r/startups
        - r/SideProject
        
        Uses Playwright for JS-rendered content.
        """
        opportunities = []
        
        subreddits = ['SaaS', 'Entrepreneur', 'startups', 'SideProject']
        
        for subreddit in subreddits:
            page = await self._setup_browser(browser)
            
            try:
                # Navigate to subreddit
                url = f"https://old.reddit.com/r/{subreddit}/hot"
                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                
                # Wait for content to load
                await page.wait_for_selector('.thing', timeout=10000)
                
                # Get page content
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                (datetime.now() - timedelta(days=days_back)).timestamp()
                
                # Parse posts
                posts = soup.find_all('div', class_='thing')
                
                for post in posts[:25]:
                    try:
                        # Extract data
                        title_elem = post.find('a', class_='title')
                        title = title_elem.get_text(strip=True) if title_elem else ""
                        
                        # Get post URL
                        post_url = title_elem['href'] if title_elem and title_elem.has_attr('href') else ""
                        if post_url and not post_url.startswith('http'):
                            post_url = f"https://old.reddit.com{post_url}"
                        
                        # Extract upvotes
                        upvotes = 0
                        score_elem = post.find('div', class_='score unvoted')
                        if not score_elem:
                            score_elem = post.find('div', attrs={'class': lambda x: x and 'score' in x})
                        if score_elem:
                            score_text = score_elem.get_text(strip=True)
                            if score_text and score_text != '•':
                                try:
                                    upvotes = int(score_text)
                                except ValueError as _exc:
                                    log.warning("swallowed_exception", action="opportunity_scanner_swallow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])
                        
                        # Extract comments
                        comments = 0
                        comments_elem = post.find('a', class_='comments')
                        if comments_elem:
                            comments_text = comments_elem.get_text(strip=True)
                            match = re.search(r'(\d+)', comments_text)
                            if match:
                                comments = int(match.group(1))
                        
                        # Get selftext if available
                        expando = post.find('div', class_='expando')
                        selftext = expando.get_text(strip=True) if expando else ""
                        
                        # Filter for problem posts
                        if not self._is_problem_post(title, selftext):
                            continue
                        
                        pain_points = self._extract_pain_points(title + " " + selftext)
                        
                        opp = Opportunity(
                            title=title,
                            description=selftext[:500],
                            source=f"reddit_r_{subreddit}",
                            url=post_url,
                            discovered_at=datetime.now(),
                            upvotes=upvotes,
                            comments=comments,
                            pain_points=pain_points,
                            tags=self._extract_tags(title + " " + selftext),
                        )
                        
                        opportunities.append(opp)
                    
                    except Exception as e:
                        logger.debug(f"Failed to parse Reddit post: {e}")
                        continue
                
                await asyncio.sleep(2)  # Rate limiting
            
            except Exception as e:
                logger.error(f"Reddit r/{subreddit} scan failed: {e}")
                await self._capture_error_screenshot(page, f"reddit_{subreddit}")
            
            finally:
                await page.close()
        
        return opportunities
    
    async def scan_hackernews(self, browser: Browser, days_back: int = 30) -> List[Opportunity]:
        """
        Scan Hacker News for Show HN and Ask HN posts.
        
        Uses Playwright for consistent scraping.
        """
        opportunities = []
        page = await self._setup_browser(browser)
        
        try:
            # Navigate to HN
            url = "https://news.ycombinator.com/show"
            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            
            # Wait for content
            await page.wait_for_selector('.athing', timeout=10000)
            
            # Get page content
            content = await page.content()
            soup = BeautifulSoup(content, 'html.parser')
            
            datetime.now() - timedelta(days=days_back)
            
            # Parse items
            items = soup.find_all('tr', class_='athing')
            
            for item in items[:50]:
                try:
                    # Get item ID
                    item_id = item.get('id', '')
                    
                    # Extract title
                    titleline = item.find('span', class_='titleline')
                    if not titleline:
                        continue
                    
                    title_link = titleline.find('a')
                    title = title_link.get_text(strip=True) if title_link else ""
                    item_url = f"https://news.ycombinator.com/item?id={item_id}"
                    
                    # Get the next row for metadata
                    subtext = item.find_next_sibling('tr')
                    if not subtext:
                        continue
                    
                    subtext_td = subtext.find('td', class_='subtext')
                    if not subtext_td:
                        continue
                    
                    # Extract points
                    points = 0
                    score_span = subtext_td.find('span', class_='score')
                    if score_span:
                        score_text = score_span.get_text(strip=True)
                        match = re.search(r'(\d+)', score_text)
                        if match:
                            points = int(match.group(1))
                    
                    # Extract comments
                    comments = 0
                    comments_link = subtext_td.find_all('a')[-1] if subtext_td.find_all('a') else None
                    if comments_link:
                        comments_text = comments_link.get_text(strip=True)
                        match = re.search(r'(\d+)', comments_text)
                        if match:
                            comments = int(match.group(1))
                    
                    # Extract time (for filtering)
                    subtext_td.find('span', class_='age')
                    # Basic time filtering (HN shows relative times)
                    
                    pain_points = self._extract_pain_points(title)
                    
                    opp = Opportunity(
                        title=title,
                        description="",  # Would need to visit item page for full description
                        source="hackernews_show",
                        url=item_url,
                        discovered_at=datetime.now(),
                        upvotes=points,
                        comments=comments,
                        pain_points=pain_points,
                        tags=self._extract_tags(title),
                    )
                    
                    opportunities.append(opp)
                
                except Exception as e:
                    logger.debug(f"Failed to parse HN item: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Hacker News scan failed: {e}")
            await self._capture_error_screenshot(page, "hackernews")
        
        finally:
            await page.close()
        
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
    parser.add_argument('--no-headless', action='store_true', help='Run browser in visible mode')
    args = parser.parse_args()
    
    scanner = OpportunityScanner(headless=not args.no_headless)
    
    # Run async scan
    opportunities = asyncio.run(scanner.scan_all(days_back=args.days))
    
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
