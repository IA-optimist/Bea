"""
Revenue launch package generator for Bea.

The package is intentionally deterministic so Bea can keep producing a
sellable bundle even when upstream LLM output is missing or thin.
"""
from __future__ import annotations

import json
import re
from html import escape


def _slugify(text: str) -> str:
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s[:60] or "project"


def _pick_product_name(_session, _offer_data: dict) -> str:
    return "InvoiceOps Guard"


def _pick_offer(_session, offer_data: dict) -> dict:
    offers = offer_data.get("offers") or []
    if offers:
        return offers[0]
    return {
        "title": "InvoiceOps Guard",
        "tagline": "Detect revenue leaks before they become churn.",
        "problem_statement": "SaaS teams lose money on billing mistakes, missed renewals, and weak onboarding.",
        "value_proposition": "A fast audit plus a clear remediation plan.",
        "target_persona": "Founder / Ops lead in a 5-50 person SaaS",
        "offer_type": "productized",
        "delivery_mode": "Audit + report + follow-up",
        "key_features": ["Audit", "Report", "Action plan"],
        "differentiators": ["Focused on revenue leaks", "Fast turnaround"],
        "objection_answers": {"Too expensive": "Cheaper than revenue loss."},
        "pricing_tiers": [
            {
                "name": "Audit",
                "price_month": 0,
                "price_year": 0,
                "description": "One-time revenue leak audit.",
                "ideal_for": "Pilot customer",
            }
        ],
        "monetization_model": "Fixed-fee audit then monthly retainer",
        "upsell_path": "Audit -> monthly monitoring retainer",
        "landing_headline": "Stop leaking SaaS revenue",
        "cta": "Book a revenue leak audit",
        "sales_script_opener": "Can I show you where revenue is leaking?",
    }


def _render_landing(bundle: dict) -> str:
    product = escape(bundle["product_name"])
    headline = escape(bundle["headline"])
    promise = escape(bundle["promise"])
    target = escape(bundle["target"])
    cta = escape(bundle["cta"])
    pricing = bundle["pricing"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{product}</title>
  <meta name="description" content="{promise}" />
  <style>
    :root {{ color-scheme: dark; --bg: #0b1020; --panel: #121a33; --text: #e5e7eb; --muted: #9ca3af; --accent: #7c3aed; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Inter, Arial, sans-serif; background: radial-gradient(circle at top, #1f2a4a, var(--bg)); color: var(--text); }}
    .wrap {{ max-width: 1080px; margin: 0 auto; padding: 64px 24px; }}
    .hero {{ display: grid; gap: 24px; grid-template-columns: 1.3fr 0.9fr; align-items: center; }}
    .card {{ background: rgba(18, 26, 51, 0.9); border: 1px solid rgba(124, 58, 237, 0.22); border-radius: 20px; padding: 24px; box-shadow: 0 20px 60px rgba(0,0,0,.25); }}
    h1 {{ font-size: clamp(2.4rem, 5vw, 4.8rem); line-height: 0.96; margin: 0 0 16px; }}
    h2 {{ margin: 0 0 12px; }}
    p {{ color: var(--muted); line-height: 1.6; }}
    .pill {{ display:inline-block; padding:8px 12px; border-radius:999px; background: rgba(124,58,237,.15); color:#c4b5fd; font-size:.92rem; }}
    .btn {{ display:inline-block; background: linear-gradient(135deg, var(--accent), #4f46e5); color:white; padding:14px 20px; border-radius:14px; text-decoration:none; font-weight:700; }}
    .grid {{ display:grid; gap:16px; grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 24px; }}
    .muted {{ color: var(--muted); }}
    @media (max-width: 900px) {{ .hero, .grid {{ grid-template-columns: 1fr; }} .wrap {{ padding: 32px 16px; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <span class="pill">B2B SaaS revenue leak audit</span>
        <h1>{headline}</h1>
        <p>{promise}</p>
        <p><strong>Target:</strong> {target}</p>
        <a class="btn" href="#pricing">{cta}</a>
      </div>
      <div class="card">
        <h2>What you get</h2>
        <p>Fast audit, clear findings, prioritized fixes, and a follow-up plan that can turn into a monthly retainer.</p>
        <p class="muted">Starting point: {pricing["primary_offer"]}</p>
      </div>
    </div>
    <div class="grid">
      <div class="card"><h2>Find leaks</h2><p>Spot billing, onboarding, activation, and renewal issues before they become losses.</p></div>
      <div class="card"><h2>Fix fast</h2><p>Get a practical action plan ranked by impact and effort.</p></div>
      <div class="card"><h2>Retain revenue</h2><p>Use the audit as the base of a recurring monitoring service.</p></div>
    </div>
    <div class="card" id="pricing" style="margin-top:24px;">
      <h2>Pricing</h2>
      <p><strong>{pricing["audit_name"]}:</strong> {pricing["audit_price"]}</p>
      <p><strong>{pricing["retainer_name"]}:</strong> {pricing["retainer_price"]}</p>
      <p><strong>Guarantee:</strong> {pricing["guarantee"]}</p>
    </div>
  </div>
</body>
</html>"""


def _render_offer_md(bundle: dict) -> str:
    pricing = bundle["pricing"]
    offer = bundle["offer"]
    return f"""# {bundle["product_name"]}

## Positioning
{bundle["headline"]}

## Problem
{offer["problem_statement"]}

## Promise
{bundle["promise"]}

## Offer
- Delivery: {offer["delivery_mode"]}
- Type: {offer["offer_type"]}
- CTA: {bundle["cta"]}

## Pricing
- {pricing["audit_name"]}: {pricing["audit_price"]}
- {pricing["retainer_name"]}: {pricing["retainer_price"]}

## Why this works
{bundle["why_now"]}
"""


def _render_outreach_md(bundle: dict) -> str:
    lines = [
        f"# Outreach for {bundle['product_name']}",
        "",
        "## Ideal targets",
    ]
    for item in bundle["first_targets"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## Initial message",
        f"Subject: {bundle['headline']}",
        "",
        "Hi, I help SaaS teams stop leaking revenue from onboarding, billing, and renewals.",
        f"I built a short audit called {bundle['product_name']} that shows the highest-impact fixes in 48h.",
        "If that would be useful, I can send the scope and a sample output.",
        "",
        "## Follow-up sequence",
        "1. Day 0: Send the short audit message above.",
        "2. Day 2: Share one concrete revenue leak example.",
        "3. Day 5: Ask for a 15-minute fit check call.",
        "",
        "## Call opener",
        bundle["sales_script_opener"],
    ]
    return "\n".join(lines)


def _render_qualification_md(bundle: dict) -> str:
    questions = "\n".join(f"- {q}" for q in bundle["qualification_questions"])
    red_flags = "\n".join(f"- {x}" for x in bundle["red_flags"])
    return f"""# Qualification for {bundle["product_name"]}

## Questions
{questions}

## Red flags
{red_flags}

## Decision rule
Proceed only if the team has recurring billing or renewal pain and wants a practical fix within 2 weeks.
"""


def _render_next_steps_md(bundle: dict) -> str:
    targets = "\n".join(f"- {x}" for x in bundle["first_targets"])
    return f"""# Next Steps

## First 10 target accounts / filters
{targets}

## Week 1
- Send 20 tailored messages.
- Book 5 fit checks.
- Convert 1 audit pilot.

## Week 2
- Deliver the audit.
- Ask for testimonial and referral.
- Offer monthly monitoring.
"""


def build_revenue_launch_package(session) -> dict:
    offer_data = dict(session.metadata.get("offer_report", {}) or {})
    chosen = _pick_offer(session, offer_data)
    product_name = _pick_product_name(session, offer_data)
    if product_name.lower() in {"offer", "mvp", "business"}:
        product_name = "InvoiceOps Guard"

    headline = chosen.get("landing_headline") or "Stop leaking SaaS revenue"
    promise = chosen.get("value_proposition") or "A fast audit plus a clear remediation plan."
    target = chosen.get("target_persona") or "Founders and ops leads at small B2B SaaS teams"
    cta = chosen.get("cta") or "Book a revenue leak audit"
    sales_script_opener = chosen.get("sales_script_opener") or "Can I show you where revenue is leaking?"

    pricing = {
        "primary_offer": "Fixed-fee audit",
        "audit_name": "Revenue Leak Audit",
        "audit_price": "490 EUR one-time",
        "retainer_name": "Monitoring Retainer",
        "retainer_price": "990 EUR / month",
        "guarantee": "If no concrete leak is found, the audit is free.",
    }

    first_targets = [
        "SaaS founders with 5-50 employees",
        "RevOps / CS leaders who own renewals",
        "Teams with manual billing or spreadsheet-based follow-up",
        "Companies using Stripe, Paddle, or a homegrown billing flow",
        "Teams with churn or downgrade pressure",
        "B2B SaaS selling monthly or annual subscriptions",
        "Companies with delayed onboarding activation",
        "Operators who review revenue weekly but lack automation",
        "Founders who want a quick outside audit",
        "Teams without a dedicated revenue operations function",
    ]

    qualification_questions = [
        "Where do you currently lose the most revenue: onboarding, billing, renewal, or follow-up?",
        "How do you detect billing errors or failed renewals today?",
        "What is the cost of one missed renewal or one billing mistake?",
        "Who owns fixing revenue leaks after they are detected?",
    ]

    red_flags = [
        "No recurring revenue model",
        "No one owns revenue operations",
        "They want a free strategy call but no urgency",
    ]

    bundle = {
        "product_name": product_name,
        "slug": _slugify(product_name),
        "headline": headline,
        "promise": promise,
        "target": target,
        "cta": cta,
        "sales_script_opener": sales_script_opener,
        "pricing": pricing,
        "offer": chosen,
        "why_now": "Revenue leaks are expensive, immediate, and easy to explain. The audit is small enough to buy quickly and strong enough to upsell into monitoring.",
        "first_targets": first_targets,
        "qualification_questions": qualification_questions,
        "red_flags": red_flags,
        "files": [
            "README.md",
            "offer.md",
            "landing/index.html",
            "outreach.md",
            "qualification.md",
            "next-steps.md",
            "bundle.json",
        ],
    }

    bundle["file_contents"] = {
        "README.md": f"""# {product_name}

Revenue launch bundle generated by Bea.

## Summary
{headline}

## Target
{target}

## CTA
{cta}

## Files
- offer.md
- landing/index.html
- outreach.md
- qualification.md
- next-steps.md
""",
        "offer.md": _render_offer_md(bundle),
        "landing/index.html": _render_landing(bundle),
        "outreach.md": _render_outreach_md(bundle),
        "qualification.md": _render_qualification_md(bundle),
        "next-steps.md": _render_next_steps_md(bundle),
        "bundle.json": json.dumps(bundle, ensure_ascii=False, indent=2),
    }
    return bundle
