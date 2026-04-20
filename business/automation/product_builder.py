#!/usr/bin/env python3
"""
Product Builder — Transform opportunities into deployable micro-SaaS

Takes an Opportunity and generates:
1. Product specification
2. Landing page (HTML/CSS/JS)
3. Backend API (FastAPI)
4. Database schema
5. Payment integration (Stripe)
6. Deployment config (Vercel/Railway)

Stack:
- Frontend: React + TailwindCSS
- Backend: FastAPI + PostgreSQL
- Payments: Stripe
- Hosting: Vercel (frontend) + Railway (backend)
- CI/CD: GitHub Actions
"""
from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ProductSpec:
    """Product specification"""
    name: str
    tagline: str
    description: str
    features: List[str]
    target_audience: str
    pricing_model: str  # free, freemium, subscription, one-time
    pricing_tiers: List[Dict]
    tech_stack: Dict[str, str]
    
    def to_dict(self) -> Dict:
        return {
            'name': self.name,
            'tagline': self.tagline,
            'description': self.description,
            'features': self.features,
            'target_audience': self.target_audience,
            'pricing_model': self.pricing_model,
            'pricing_tiers': self.pricing_tiers,
            'tech_stack': self.tech_stack,
        }


class ProductBuilder:
    """
    Build a complete micro-SaaS from an opportunity.
    
    Usage:
        builder = ProductBuilder()
        
        # Generate spec from opportunity
        spec = builder.generate_spec(opportunity)
        
        # Build product
        project_dir = builder.build_product(spec)
        
        # Deploy
        builder.deploy(project_dir)
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path.home() / ".jarvismax" / "products"
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_spec(self, opportunity_data: Dict) -> ProductSpec:
        """
        Generate product specification from opportunity.
        
        Args:
            opportunity_data: Opportunity dict (from OpportunityScanner)
        
        Returns:
            ProductSpec
        """
        logger.info(f"📝 Generating product spec...")
        
        # Extract info
        title = opportunity_data.get('title', 'Untitled')
        description = opportunity_data.get('description', '')
        tags = opportunity_data.get('tags', [])
        pain_points = opportunity_data.get('pain_points', [])
        
        # Generate product name (clean title)
        name = self._sanitize_name(title)
        
        # Generate tagline
        tagline = self._generate_tagline(title, description, pain_points)
        
        # Generate features (from pain points)
        features = self._generate_features(pain_points, tags)
        
        # Determine pricing model
        pricing_model, pricing_tiers = self._generate_pricing(tags)
        
        # Target audience
        target_audience = self._identify_audience(tags, description)
        
        # Tech stack
        tech_stack = {
            'frontend': 'React + TailwindCSS + Vite',
            'backend': 'FastAPI + PostgreSQL',
            'auth': 'Supabase Auth',
            'payments': 'Stripe',
            'hosting_frontend': 'Vercel',
            'hosting_backend': 'Railway',
            'ci_cd': 'GitHub Actions',
        }
        
        spec = ProductSpec(
            name=name,
            tagline=tagline,
            description=description[:500],
            features=features,
            target_audience=target_audience,
            pricing_model=pricing_model,
            pricing_tiers=pricing_tiers,
            tech_stack=tech_stack,
        )
        
        logger.info(f"✅ Product spec generated: {spec.name}")
        logger.info(f"   Tagline: {spec.tagline}")
        logger.info(f"   Features: {len(spec.features)}")
        logger.info(f"   Pricing: {spec.pricing_model}")
        
        return spec
    
    def build_product(self, spec: ProductSpec) -> Path:
        """
        Build complete product structure.
        
        Returns:
            Path to project directory
        """
        logger.info(f"🏗️  Building product: {spec.name}...")
        
        project_dir = self.output_dir / self._sanitize_name(spec.name)
        project_dir.mkdir(parents=True, exist_ok=True)
        
        # Create structure
        self._create_project_structure(project_dir)
        
        # Generate files
        self._generate_landing_page(project_dir, spec)
        self._generate_backend(project_dir, spec)
        self._generate_database_schema(project_dir, spec)
        self._generate_stripe_integration(project_dir, spec)
        self._generate_deployment_config(project_dir, spec)
        self._generate_readme(project_dir, spec)
        
        # Save spec
        spec_path = project_dir / "product_spec.json"
        spec_path.write_text(json.dumps(spec.to_dict(), indent=2))
        
        logger.info(f"✅ Product built: {project_dir}")
        
        return project_dir
    
    def _create_project_structure(self, project_dir: Path):
        """Create project directory structure"""
        dirs = [
            'frontend/src/components',
            'frontend/src/pages',
            'frontend/public',
            'backend/app',
            'backend/alembic',
            'deploy',
            'docs',
        ]
        
        for dir_path in dirs:
            (project_dir / dir_path).mkdir(parents=True, exist_ok=True)
    
    def _generate_landing_page(self, project_dir: Path, spec: ProductSpec):
        """Generate landing page (React + TailwindCSS)"""
        logger.info("  📄 Generating landing page...")
        
        # Simple HTML landing page (can be enhanced with React later)
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{spec.name} - {spec.tagline}</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-50">
    <!-- Hero Section -->
    <div class="min-h-screen flex items-center justify-center px-4">
        <div class="max-w-4xl mx-auto text-center">
            <h1 class="text-5xl font-bold text-gray-900 mb-4">
                {spec.name}
            </h1>
            <p class="text-2xl text-gray-600 mb-8">
                {spec.tagline}
            </p>
            <p class="text-lg text-gray-500 mb-12 max-w-2xl mx-auto">
                {spec.description[:200]}...
            </p>
            
            <!-- CTA Buttons -->
            <div class="flex gap-4 justify-center">
                <a href="#pricing" class="bg-blue-600 text-white px-8 py-3 rounded-lg font-semibold hover:bg-blue-700 transition">
                    Get Started
                </a>
                <a href="#features" class="bg-gray-200 text-gray-700 px-8 py-3 rounded-lg font-semibold hover:bg-gray-300 transition">
                    Learn More
                </a>
            </div>
        </div>
    </div>
    
    <!-- Features Section -->
    <div id="features" class="py-20 bg-white">
        <div class="max-w-6xl mx-auto px-4">
            <h2 class="text-3xl font-bold text-center mb-12">Features</h2>
            <div class="grid md:grid-cols-3 gap-8">
                {''.join([f'''
                <div class="p-6 border rounded-lg">
                    <h3 class="text-xl font-semibold mb-2">✨ {feature}</h3>
                    <p class="text-gray-600">Description of {feature}</p>
                </div>
                ''' for feature in spec.features[:6]])}
            </div>
        </div>
    </div>
    
    <!-- Pricing Section -->
    <div id="pricing" class="py-20 bg-gray-50">
        <div class="max-w-6xl mx-auto px-4">
            <h2 class="text-3xl font-bold text-center mb-12">Pricing</h2>
            <div class="grid md:grid-cols-{len(spec.pricing_tiers)} gap-8">
                {''.join([f'''
                <div class="p-8 border rounded-lg bg-white">
                    <h3 class="text-2xl font-bold mb-2">{tier.get('name', 'Plan')}</h3>
                    <p class="text-4xl font-bold mb-4">${tier.get('price', 0)}<span class="text-lg text-gray-500">/mo</span></p>
                    <ul class="space-y-2 mb-6">
                        {''.join([f'<li>✓ {feat}</li>' for feat in tier.get('features', [])])}
                    </ul>
                    <button class="w-full bg-blue-600 text-white py-2 rounded-lg hover:bg-blue-700 transition">
                        Choose Plan
                    </button>
                </div>
                ''' for tier in spec.pricing_tiers])}
            </div>
        </div>
    </div>
    
    <!-- Footer -->
    <footer class="bg-gray-900 text-white py-8">
        <div class="max-w-6xl mx-auto px-4 text-center">
            <p>&copy; 2026 {spec.name}. Built with JarvisMax AGI.</p>
        </div>
    </footer>
</body>
</html>
"""
        
        landing_path = project_dir / "frontend" / "index.html"
        landing_path.write_text(html)
        
        logger.info(f"    ✅ Landing page: {landing_path}")
    
    def _generate_backend(self, project_dir: Path, spec: ProductSpec):
        """Generate FastAPI backend"""
        logger.info("  ⚙️  Generating backend...")
        
        # Main FastAPI app
        backend_code = f'''"""
{spec.name} Backend API

Auto-generated by JarvisMax Business Engine
"""
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import stripe
import os

app = FastAPI(title="{spec.name}")

# CORS — origines explicites via env CORS_ALLOWED_ORIGINS (CSV)
_cors_origins = [o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

# Models
class User(BaseModel):
    email: str
    name: str

class Subscription(BaseModel):
    user_id: int
    plan: str
    status: str

# Routes
@app.get("/")
def read_root():
    return {{"message": "Welcome to {spec.name} API"}}

@app.get("/health")
def health_check():
    return {{"status": "ok"}}

@app.post("/api/subscribe")
def create_subscription(subscription: Subscription):
    # TODO: Implement Stripe subscription logic
    return {{"status": "success", "subscription_id": "sub_xxx"}}

@app.get("/api/user/{{user_id}}")
def get_user(user_id: int):
    # TODO: Implement user retrieval
    return {{"id": user_id, "email": "user@example.com"}}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''
        
        backend_path = project_dir / "backend" / "app" / "main.py"
        backend_path.write_text(backend_code)
        
        # Requirements
        requirements = """fastapi==0.115.0
uvicorn[standard]==0.32.1
stripe==11.2.0
pydantic==2.10.3
python-dotenv==1.0.1
psycopg2-binary==2.9.10
sqlalchemy==2.0.36
alembic==1.14.0
"""
        
        req_path = project_dir / "backend" / "requirements.txt"
        req_path.write_text(requirements)
        
        logger.info(f"    ✅ Backend: {backend_path}")
    
    def _generate_database_schema(self, project_dir: Path, spec: ProductSpec):
        """Generate database schema (SQLAlchemy)"""
        logger.info("  🗄️  Generating database schema...")
        
        schema_code = f'''"""
Database models for {spec.name}
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    
    subscriptions = relationship("Subscription", back_populates="user")

class Subscription(Base):
    __tablename__ = "subscriptions"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    plan = Column(String)
    status = Column(String)  # active, canceled, expired
    stripe_subscription_id = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="subscriptions")
'''
        
        models_path = project_dir / "backend" / "app" / "models.py"
        models_path.write_text(schema_code)
        
        logger.info(f"    ✅ Schema: {models_path}")
    
    def _generate_stripe_integration(self, project_dir: Path, spec: ProductSpec):
        """Generate Stripe integration code"""
        logger.info("  💳 Generating Stripe integration...")
        
        stripe_code = '''"""
Stripe payment integration
"""
import stripe
import os

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

def create_customer(email: str, name: str):
    """Create Stripe customer"""
    return stripe.Customer.create(email=email, name=name)

def create_subscription(customer_id: str, price_id: str):
    """Create subscription"""
    return stripe.Subscription.create(
        customer=customer_id,
        items=[{"price": price_id}]
    )

def cancel_subscription(subscription_id: str):
    """Cancel subscription"""
    return stripe.Subscription.delete(subscription_id)

def create_checkout_session(price_id: str, success_url: str, cancel_url: str):
    """Create checkout session"""
    return stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
    )
'''
        
        stripe_path = project_dir / "backend" / "app" / "stripe_integration.py"
        stripe_path.write_text(stripe_code)
        
        logger.info(f"    ✅ Stripe: {stripe_path}")
    
    def _generate_deployment_config(self, project_dir: Path, spec: ProductSpec):
        """Generate deployment configs"""
        logger.info("  🚀 Generating deployment config...")
        
        # Vercel config (frontend)
        vercel_config = {
            "version": 2,
            "builds": [{"src": "frontend/index.html", "use": "@vercel/static"}],
            "routes": [{"src": "/(.*)", "dest": "/frontend/$1"}]
        }
        
        vercel_path = project_dir / "vercel.json"
        vercel_path.write_text(json.dumps(vercel_config, indent=2))
        
        # Railway config (backend)
        railway_config = {
            "build": {
                "builder": "NIXPACKS",
                "buildCommand": "pip install -r backend/requirements.txt"
            },
            "deploy": {
                "startCommand": "cd backend && uvicorn app.main:app --host 0.0.0.0 --port $PORT",
                "restartPolicyType": "ON_FAILURE"
            }
        }
        
        railway_path = project_dir / "railway.json"
        railway_path.write_text(json.dumps(railway_config, indent=2))
        
        # .env.example
        env_example = f"""# {spec.name} Environment Variables

# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname

# Stripe
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx

# Frontend URL
FRONTEND_URL=https://yourapp.vercel.app

# Backend URL
BACKEND_URL=https://yourapp.railway.app
"""
        
        env_path = project_dir / ".env.example"
        env_path.write_text(env_example)
        
        logger.info(f"    ✅ Deployment configs: vercel.json, railway.json")
    
    def _generate_readme(self, project_dir: Path, spec: ProductSpec):
        """Generate README"""
        readme = f"""# {spec.name}

{spec.tagline}

**Auto-generated by JarvisMax Business Engine**

## Description

{spec.description}

## Features

{chr(10).join(['- ' + f for f in spec.features])}

## Tech Stack

{chr(10).join([f'- **{k}**: {v}' for k, v in spec.tech_stack.items()])}

## Pricing

**Model:** {spec.pricing_model}

{chr(10).join([f'### {tier.get("name", "Plan")} - ${tier.get("price", 0)}/mo' + chr(10) + chr(10).join(['- ' + f for f in tier.get("features", [])]) for tier in spec.pricing_tiers])}

## Setup

### Prerequisites
- Node.js 18+
- Python 3.11+
- PostgreSQL
- Stripe account

### Installation

1. Clone repository
2. Install dependencies:
   ```bash
   # Frontend
   cd frontend
   npm install
   
   # Backend
   cd backend
   pip install -r requirements.txt
   ```

3. Configure environment variables (see `.env.example`)

4. Run locally:
   ```bash
   # Backend
   cd backend
   uvicorn app.main:app --reload
   
   # Frontend
   cd frontend
   npm run dev
   ```

## Deployment

### Frontend (Vercel)
```bash
vercel deploy
```

### Backend (Railway)
```bash
railway up
```

## License

MIT

---

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**By:** JarvisMax AGI Business Engine
"""
        
        readme_path = project_dir / "README.md"
        readme_path.write_text(readme)
        
        logger.info(f"    ✅ README: {readme_path}")
    
    def _sanitize_name(self, title: str) -> str:
        """Convert title to valid product name"""
        # Remove special chars, convert to lowercase, replace spaces with hyphens
        name = re.sub(r'[^a-zA-Z0-9\s-]', '', title)
        name = re.sub(r'\s+', '-', name.strip())
        name = name.lower()[:50]
        return name or "untitled-saas"
    
    def _generate_tagline(self, title: str, description: str, pain_points: List[str]) -> str:
        """Generate catchy tagline"""
        # Simple heuristic for now (can be enhanced with LLM)
        if pain_points:
            return f"Solve {pain_points[0][:50]} effortlessly"
        elif len(description) > 20:
            return description[:80] + "..."
        else:
            return f"{title} - Simplified"
    
    def _generate_features(self, pain_points: List[str], tags: List[str]) -> List[str]:
        """Generate features from pain points"""
        features = []
        
        # From pain points
        for pp in pain_points[:3]:
            feature = pp.strip()
            if len(feature) > 10:
                features.append(feature[:80])
        
        # From tags
        tag_features = {
            'automation': 'Automated workflow',
            'analytics': 'Real-time analytics dashboard',
            'productivity': 'Boost team productivity',
            'ai': 'AI-powered insights',
            'developer_tools': 'Developer-friendly API',
            'payment': 'Integrated payment processing',
        }
        
        for tag in tags:
            if tag in tag_features:
                features.append(tag_features[tag])
        
        # Defaults if empty
        if not features:
            features = [
                'Easy to use interface',
                'Fast and reliable',
                'Secure and compliant',
                'Excellent support',
            ]
        
        return features[:6]
    
    def _generate_pricing(self, tags: List[str]) -> tuple[str, List[Dict]]:
        """Generate pricing model and tiers"""
        # Freemium for most B2C, subscription for B2B
        if 'developer_tools' in tags or 'saas' in tags:
            model = 'freemium'
        else:
            model = 'subscription'
        
        if model == 'freemium':
            tiers = [
                {
                    'name': 'Free',
                    'price': 0,
                    'features': ['Basic features', 'Limited usage', 'Community support']
                },
                {
                    'name': 'Pro',
                    'price': 19,
                    'features': ['All features', 'Unlimited usage', 'Priority support', 'Analytics']
                },
                {
                    'name': 'Business',
                    'price': 49,
                    'features': ['Everything in Pro', 'Team collaboration', 'Custom integrations', 'Dedicated support']
                }
            ]
        else:
            tiers = [
                {
                    'name': 'Starter',
                    'price': 29,
                    'features': ['Core features', 'Email support', '1 user']
                },
                {
                    'name': 'Professional',
                    'price': 79,
                    'features': ['All features', 'Priority support', '5 users', 'API access']
                }
            ]
        
        return model, tiers
    
    def _identify_audience(self, tags: List[str], description: str) -> str:
        """Identify target audience"""
        audiences = {
            'developer_tools': 'Developers and technical teams',
            'saas': 'SaaS companies and startups',
            'marketing': 'Marketing professionals and agencies',
            'e-commerce': 'Online retailers and e-commerce businesses',
            'productivity': 'Remote teams and freelancers',
            'ai': 'Tech-savvy professionals',
        }
        
        for tag in tags:
            if tag in audiences:
                return audiences[tag]
        
        return 'Small businesses and entrepreneurs'


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Build micro-SaaS from opportunity")
    parser.add_argument('opportunity_json', help='Path to opportunity JSON file')
    parser.add_argument('--output', help='Output directory', default=None)
    args = parser.parse_args()
    
    # Load opportunity
    with open(args.opportunity_json) as f:
        data = json.load(f)
    
    # Get first opportunity
    opportunities = data.get('opportunities', [])
    if not opportunities:
        print("❌ No opportunities found in JSON")
        return
    
    opportunity = opportunities[0]
    
    # Build
    builder = ProductBuilder(output_dir=Path(args.output) if args.output else None)
    spec = builder.generate_spec(opportunity)
    project_dir = builder.build_product(spec)
    
    print(f"\n✅ Product built successfully!")
    print(f"📁 Location: {project_dir}")
    print(f"\n📝 Next steps:")
    print(f"   1. cd {project_dir}")
    print(f"   2. Review generated files")
    print(f"   3. Configure .env (see .env.example)")
    print(f"   4. Deploy: vercel deploy && railway up")


if __name__ == '__main__':
    main()
