#!/usr/bin/env python3
"""
Daily Opportunity Scan — Cron Job
Runs opportunity_scanner.py daily at 06:00 UTC
Filters high-value opportunities (score > 70) and stores in PostgreSQL
Sends Telegram alerts for exceptional opportunities (score > 85)
"""
from __future__ import annotations

import sys
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

# Add parent dir to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models.opportunity import Opportunity
from business.automation.opportunity_scanner import OpportunityScanner
import structlog

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = structlog.get_logger()

# Database connection — DATABASE_URL is required.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is required for daily_opportunity_scan. "
        "Set it in the cron environment."
    )
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


def send_telegram_alert(opportunity: dict):
    """Send Telegram notification for high-value opportunity"""
    try:
        import requests
        
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "7216973216")  # Max's Telegram ID
        
        if not bot_token:
            logger.warning("telegram_alert_skipped", reason="no_bot_token")
            return
        
        message = f"""🎯 **HIGH-VALUE OPPORTUNITY DETECTED**

**Title:** {opportunity['title']}
**Source:** {opportunity['source'].replace('_', ' ').title()}
**Total Score:** {opportunity['scores']['total']}/100

📊 **Scores:**
• Demand: {opportunity['scores']['demand']}/100
• Competition: {opportunity['scores']['competition']}/100
• Feasibility: {opportunity['scores']['feasibility']}/100
• Monetization: {opportunity['scores']['monetization']}/100

📈 **Metrics:**
• Upvotes: {opportunity['metrics']['upvotes']}
• Comments: {opportunity['metrics']['comments']}
• Mentions: {opportunity['metrics']['mentions']}

🔗 **Link:** {opportunity['url']}

💡 **Pain Points:**
{chr(10).join(f"• {p}" for p in opportunity['pain_points'][:3])}

🏷️ **Tags:** {', '.join(opportunity['tags'][:5])}

_Discovered: {datetime.fromisoformat(opportunity['discovered_at']).strftime('%Y-%m-%d %H:%M UTC')}_
"""
        
        response = requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            },
            timeout=10,
        )
        
        if response.status_code == 200:
            logger.info("telegram_alert_sent", opportunity_id=opportunity.get('id'))
        else:
            logger.warning("telegram_alert_failed", status=response.status_code, body=response.text[:200])
    
    except Exception as e:
        logger.error("telegram_alert_error", error=str(e))


def main():
    """Main cron job execution"""
    logger.info("opportunity_scan_started", timestamp=datetime.now(timezone.utc).isoformat())
    
    db = SessionLocal()
    try:
        # Initialize scanner
        scanner = OpportunityScanner()
        
        # Run scan (all sources)
        logger.info("scanning_sources", sources=["product_hunt", "reddit", "hackernews"])
        opportunities = scanner.scan_all()
        
        logger.info("scan_completed", total_found=len(opportunities))
        
        # Filter high-value opportunities (score > 70)
        high_value = [opp for opp in opportunities if opp.total_score > 70]
        logger.info("filtered_high_value", count=len(high_value), threshold=70)
        
        # Store top 10 in database
        stored_count = 0
        alert_count = 0
        
        for opp_data in sorted(high_value, key=lambda x: x.total_score, reverse=True)[:10]:
            # Check if already exists (by URL)
            existing = db.query(Opportunity).filter(Opportunity.url == opp_data.url).first()
            
            if existing:
                logger.info("opportunity_exists", url=opp_data.url, existing_id=existing.id)
                continue
            
            # Create new opportunity
            opportunity = Opportunity(
                title=opp_data.title,
                description=opp_data.description,
                source=opp_data.source,
                url=opp_data.url,
                discovered_at=opp_data.discovered_at,
                upvotes=opp_data.upvotes,
                comments=opp_data.comments,
                mentions=opp_data.mentions,
                demand_score=opp_data.demand_score,
                competition_score=opp_data.competition_score,
                feasibility_score=opp_data.feasibility_score,
                monetization_score=opp_data.monetization_score,
                total_score=opp_data.total_score,
                tags=opp_data.tags,
                pain_points=opp_data.pain_points,
                raw_data=opp_data.to_dict(),
            )
            
            db.add(opportunity)
            db.commit()
            db.refresh(opportunity)
            
            stored_count += 1
            logger.info("opportunity_stored", id=opportunity.id, title=opportunity.title[:50], score=opportunity.total_score)
            
            # Send Telegram alert for exceptional opportunities (score > 85)
            if opportunity.total_score > 85:
                send_telegram_alert(opportunity.to_dict())
                alert_count += 1
        
        logger.info("scan_job_completed", 
                   total_scanned=len(opportunities),
                   high_value=len(high_value),
                   stored=stored_count,
                   alerts_sent=alert_count)
        
        return stored_count
    
    except Exception as e:
        logger.error("scan_job_failed", error=str(e), exc_info=True)
        raise
    
    finally:
        db.close()


if __name__ == "__main__":
    try:
        count = main()
        sys.exit(0)
    except Exception as e:
        logger.error("cron_job_failed", error=str(e))
        sys.exit(1)
