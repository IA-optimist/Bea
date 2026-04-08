#!/usr/bin/env python3
"""
AI Agent Marketplace — Buy/Sell Specialized AI Agents & Automation Workflows

Revenue Model: Commission-based (20% of sales)

Features:
1. Agent listing (specialized AI agents for specific tasks)
2. Workflow marketplace (n8n, Zapier, Make workflows)
3. Rating & reviews
4. API integration (plug-and-play)
5. Revenue sharing (80% creator, 20% platform)
6. Usage analytics
7. Subscription plans (monthly/yearly)
8. White-label options

Target Customers:
- Buyers: SMEs, entrepreneurs, agencies
- Sellers: AI engineers, no-code builders, agencies

Examples:
- "Email Response Agent" (€29/month) — Auto-respond to customer emails
- "SEO Content Generator" (€49/month) — Generate blog posts
- "Lead Qualification Bot" (€99/month) — Qualify sales leads
- "Social Media Manager" (€79/month) — Auto-post to social
- "Invoice Processing Agent" (€149/month) — Extract data from invoices

Tech Stack:
- Backend: FastAPI + PostgreSQL
- Payment: Stripe Connect (revenue sharing)
- Agent hosting: Modal, Replicate, or self-hosted
- API Gateway: Kong or custom
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentCategory(str, Enum):
    """Agent categories"""
    CUSTOMER_SERVICE = "customer_service"
    SALES = "sales"
    MARKETING = "marketing"
    FINANCE = "finance"
    HR = "hr"
    OPERATIONS = "operations"
    DEVELOPMENT = "development"
    DATA_ANALYSIS = "data_analysis"
    CONTENT_CREATION = "content_creation"
    OTHER = "other"


class PricingModel(str, Enum):
    """Pricing models"""
    FREE = "free"
    ONE_TIME = "one_time"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    PAY_PER_USE = "pay_per_use"


@dataclass
class AgentListing:
    """Agent marketplace listing"""
    agent_id: str
    name: str
    description: str
    category: AgentCategory
    
    # Creator
    creator_id: str
    creator_name: str
    
    # Pricing
    pricing_model: PricingModel
    price: float  # €
    
    # Metrics
    total_installs: int = 0
    total_revenue: float = 0.0
    rating: float = 0.0  # 0-5
    num_reviews: int = 0
    
    # Features
    features: List[str] = field(default_factory=list)
    use_cases: List[str] = field(default_factory=list)
    
    # Technical
    api_endpoint: Optional[str] = None
    requires_api_key: bool = False
    
    # Dates
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            'agent_id': self.agent_id,
            'name': self.name,
            'description': self.description,
            'category': self.category.value,
            'creator': {
                'id': self.creator_id,
                'name': self.creator_name,
            },
            'pricing': {
                'model': self.pricing_model.value,
                'price': self.price,
            },
            'metrics': {
                'installs': self.total_installs,
                'revenue': round(self.total_revenue, 2),
                'rating': round(self.rating, 1),
                'reviews': self.num_reviews,
            },
            'features': self.features,
            'use_cases': self.use_cases,
            'api_endpoint': self.api_endpoint,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
        }
    
    def calculate_creator_revenue(self) -> float:
        """Calculate creator's share (80%)"""
        return self.total_revenue * 0.80
    
    def calculate_platform_revenue(self) -> float:
        """Calculate platform's share (20%)"""
        return self.total_revenue * 0.20


@dataclass
class Creator:
    """Agent creator/seller"""
    creator_id: str
    name: str
    email: str
    
    # Stats
    total_agents: int = 0
    total_installs: int = 0
    total_revenue: float = 0.0
    
    # Payout
    stripe_account_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'creator_id': self.creator_id,
            'name': self.name,
            'email': self.email,
            'stats': {
                'agents': self.total_agents,
                'installs': self.total_installs,
                'revenue': round(self.total_revenue, 2),
                'creator_share': round(self.total_revenue * 0.80, 2),
            },
            'stripe_account_id': self.stripe_account_id,
        }


class AgentMarketplace:
    """
    AI Agent Marketplace platform.
    
    Usage:
        marketplace = AgentMarketplace()
        
        # Add creator
        creator = marketplace.add_creator("John Doe", "john@example.com")
        
        # List agent
        agent = marketplace.list_agent(
            name="Email Response Agent",
            creator_id=creator.creator_id,
            price=29.0
        )
        
        # Simulate purchase
        marketplace.purchase_agent(agent.agent_id, buyer_id="customer_123")
        
        # Get stats
        stats = marketplace.get_marketplace_stats()
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".jarvismax" / "marketplace"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.agents: Dict[str, AgentListing] = {}
        self.creators: Dict[str, Creator] = {}
        
        self._load_state()
    
    def _load_state(self):
        """Load marketplace data from disk"""
        agents_file = self.data_dir / "agents.json"
        creators_file = self.data_dir / "creators.json"
        
        if agents_file.exists():
            with open(agents_file) as f:
                data = json.load(f)
                for agent_data in data:
                    agent = AgentListing(
                        agent_id=agent_data['agent_id'],
                        name=agent_data['name'],
                        description=agent_data['description'],
                        category=AgentCategory(agent_data['category']),
                        creator_id=agent_data['creator']['id'],
                        creator_name=agent_data['creator']['name'],
                        pricing_model=PricingModel(agent_data['pricing']['model']),
                        price=agent_data['pricing']['price'],
                        total_installs=agent_data['metrics']['installs'],
                        total_revenue=agent_data['metrics']['revenue'],
                        rating=agent_data['metrics']['rating'],
                        num_reviews=agent_data['metrics']['reviews'],
                        features=agent_data.get('features', []),
                        use_cases=agent_data.get('use_cases', []),
                        api_endpoint=agent_data.get('api_endpoint'),
                        created_at=datetime.fromisoformat(agent_data['created_at']),
                        updated_at=datetime.fromisoformat(agent_data['updated_at']),
                    )
                    self.agents[agent.agent_id] = agent
        
        if creators_file.exists():
            with open(creators_file) as f:
                data = json.load(f)
                for creator_data in data:
                    creator = Creator(
                        creator_id=creator_data['creator_id'],
                        name=creator_data['name'],
                        email=creator_data['email'],
                        total_agents=creator_data['stats']['agents'],
                        total_installs=creator_data['stats']['installs'],
                        total_revenue=creator_data['stats']['revenue'],
                        stripe_account_id=creator_data.get('stripe_account_id'),
                    )
                    self.creators[creator.creator_id] = creator
    
    def _save_state(self):
        """Save marketplace data to disk"""
        agents_file = self.data_dir / "agents.json"
        creators_file = self.data_dir / "creators.json"
        
        with open(agents_file, 'w') as f:
            json.dump([a.to_dict() for a in self.agents.values()], f, indent=2)
        
        with open(creators_file, 'w') as f:
            json.dump([c.to_dict() for c in self.creators.values()], f, indent=2)
    
    def add_creator(self, name: str, email: str) -> Creator:
        """Register new creator"""
        creator_id = hashlib.md5(email.encode()).hexdigest()[:12]
        
        creator = Creator(
            creator_id=creator_id,
            name=name,
            email=email,
        )
        
        self.creators[creator_id] = creator
        self._save_state()
        
        logger.info(f"✅ Creator added: {name}")
        
        return creator
    
    def list_agent(
        self,
        name: str,
        description: str,
        creator_id: str,
        category: AgentCategory,
        pricing_model: PricingModel,
        price: float,
        features: Optional[List[str]] = None,
        use_cases: Optional[List[str]] = None,
    ) -> AgentListing:
        """List new agent on marketplace"""
        agent_id = hashlib.md5(f"{name}{creator_id}{datetime.now().isoformat()}".encode()).hexdigest()[:16]
        
        if creator_id not in self.creators:
            raise ValueError(f"Creator {creator_id} not found")
        
        creator = self.creators[creator_id]
        
        agent = AgentListing(
            agent_id=agent_id,
            name=name,
            description=description,
            category=category,
            creator_id=creator_id,
            creator_name=creator.name,
            pricing_model=pricing_model,
            price=price,
            features=features or [],
            use_cases=use_cases or [],
        )
        
        self.agents[agent_id] = agent
        
        # Update creator stats
        creator.total_agents += 1
        
        self._save_state()
        
        logger.info(f"✅ Agent listed: {name} (€{price}/{pricing_model.value})")
        
        return agent
    
    def purchase_agent(self, agent_id: str, buyer_id: str) -> Dict:
        """Simulate agent purchase"""
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")
        
        agent = self.agents[agent_id]
        creator = self.creators[agent.creator_id]
        
        # Process payment
        payment_amount = agent.price
        
        # Update agent stats
        agent.total_installs += 1
        
        if agent.pricing_model in [PricingModel.ONE_TIME, PricingModel.MONTHLY, PricingModel.YEARLY]:
            agent.total_revenue += payment_amount
            
            # Update creator stats
            creator.total_installs += 1
            creator.total_revenue += payment_amount
        
        self._save_state()
        
        logger.info(f"💰 Purchase: {agent.name} by {buyer_id} — €{payment_amount}")
        
        return {
            'agent_id': agent_id,
            'buyer_id': buyer_id,
            'amount': payment_amount,
            'creator_share': agent.calculate_creator_revenue() / agent.total_installs if agent.total_installs > 0 else 0,
            'platform_share': agent.calculate_platform_revenue() / agent.total_installs if agent.total_installs > 0 else 0,
        }
    
    def get_marketplace_stats(self) -> Dict:
        """Get overall marketplace statistics"""
        total_agents = len(self.agents)
        total_creators = len(self.creators)
        total_installs = sum(a.total_installs for a in self.agents.values())
        total_revenue = sum(a.total_revenue for a in self.agents.values())
        platform_revenue = sum(a.calculate_platform_revenue() for a in self.agents.values())
        
        # Top agents
        top_agents = sorted(self.agents.values(), key=lambda a: a.total_revenue, reverse=True)[:5]
        
        # Top creators
        top_creators = sorted(self.creators.values(), key=lambda c: c.total_revenue, reverse=True)[:5]
        
        return {
            'totals': {
                'agents': total_agents,
                'creators': total_creators,
                'installs': total_installs,
                'revenue': round(total_revenue, 2),
                'platform_revenue': round(platform_revenue, 2),
            },
            'top_agents': [
                {'name': a.name, 'installs': a.total_installs, 'revenue': round(a.total_revenue, 2)}
                for a in top_agents
            ],
            'top_creators': [
                {'name': c.name, 'agents': c.total_agents, 'revenue': round(c.total_revenue, 2)}
                for c in top_creators
            ],
        }
    
    def generate_dashboard(self) -> str:
        """Generate marketplace dashboard"""
        stats = self.get_marketplace_stats()
        
        dashboard = f"""# 🤖 AI AGENT MARKETPLACE DASHBOARD

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

## 💰 Revenue

**Total Revenue:** €{stats['totals']['revenue']:,.2f}  
**Platform Revenue (20%):** €{stats['totals']['platform_revenue']:,.2f}  
**Creator Revenue (80%):** €{(stats['totals']['revenue'] - stats['totals']['platform_revenue']):,.2f}

**Monthly Recurring Revenue (est.):** €{stats['totals']['revenue'] * 0.70:,.2f}/month  
**Annual Recurring Revenue (est.):** €{stats['totals']['revenue'] * 0.70 * 12:,.2f}/year

---

## 📊 Statistics

- **Total Agents:** {stats['totals']['agents']}
- **Total Creators:** {stats['totals']['creators']}
- **Total Installs:** {stats['totals']['installs']}
- **Avg Revenue per Agent:** €{(stats['totals']['revenue'] / max(stats['totals']['agents'], 1)):,.2f}
- **Avg Installs per Agent:** {(stats['totals']['installs'] / max(stats['totals']['agents'], 1)):.1f}

---

## 🏆 Top Agents (by Revenue)

"""
        
        for i, agent in enumerate(stats['top_agents'], 1):
            dashboard += f"{i}. **{agent['name']}** — €{agent['revenue']:,.2f} ({agent['installs']} installs)\n"
        
        dashboard += f"""
---

## 👥 Top Creators (by Revenue)

"""
        
        for i, creator in enumerate(stats['top_creators'], 1):
            dashboard += f"{i}. **{creator['name']}** — €{creator['revenue']:,.2f} ({creator['agents']} agents)\n"
        
        dashboard += f"""
---

## 📈 Agent Categories

"""
        
        # Count by category
        category_counts = {}
        for agent in self.agents.values():
            cat = agent.category.value
            if cat not in category_counts:
                category_counts[cat] = 0
            category_counts[cat] += 1
        
        for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
            dashboard += f"- **{cat.replace('_', ' ').title()}:** {count} agents\n"
        
        dashboard += """
---

**Generated by JarvisMax Agent Marketplace**  
**Version:** 1.0.0
"""
        
        return dashboard
    
    def save_dashboard(self, dashboard: str) -> Path:
        """Save dashboard to file"""
        dashboard_path = self.data_dir / "marketplace_dashboard.md"
        dashboard_path.write_text(dashboard)
        
        logger.info(f"💾 Dashboard saved: {dashboard_path}")
        
        return dashboard_path


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="AI Agent Marketplace")
    parser.add_argument('--add-creator', help='Add creator (name)')
    parser.add_argument('--email', help='Creator email')
    parser.add_argument('--list-agent', help='List agent (name)')
    parser.add_argument('--creator-id', help='Creator ID')
    parser.add_argument('--price', type=float, default=29.0, help='Agent price')
    parser.add_argument('--dashboard', action='store_true', help='Generate dashboard')
    args = parser.parse_args()
    
    marketplace = AgentMarketplace()
    
    if args.add_creator and args.email:
        creator = marketplace.add_creator(args.add_creator, args.email)
        print(f"✅ Creator added: {creator.name}")
        print(f"   Creator ID: {creator.creator_id}")
    
    if args.list_agent and args.creator_id:
        agent = marketplace.list_agent(
            name=args.list_agent,
            description=f"AI agent for {args.list_agent}",
            creator_id=args.creator_id,
            category=AgentCategory.CUSTOMER_SERVICE,
            pricing_model=PricingModel.MONTHLY,
            price=args.price,
            features=["Automated responses", "24/7 availability", "Multi-language support"],
            use_cases=["Customer support", "Sales inquiries", "General FAQs"],
        )
        print(f"✅ Agent listed: {agent.name} (€{agent.price}/month)")
    
    if args.dashboard or not (args.add_creator or args.list_agent):
        dashboard = marketplace.generate_dashboard()
        print(dashboard)
        marketplace.save_dashboard(dashboard)


if __name__ == '__main__':
    main()
