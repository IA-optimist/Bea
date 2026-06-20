#!/usr/bin/env python3
"""
Compliance Checker — Legal validation for automated business ideas

Checks:
1. Terms of Service compliance (scraping, automation)
2. GDPR requirements (EU users)
3. Legal business category (filter illegal/gray areas)
4. Copyright / trademark issues
5. Payment processing compliance (PCI DSS basics)

Flags:
- RED: Illegal / high-risk (block)
- YELLOW: Legal but risky (requires manual review)
- GREEN: Safe to proceed

This is NOT legal advice. Always consult a lawyer for real legal questions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
from pathlib import Path
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Risk classification"""
    GREEN = "green"      # Safe to proceed
    YELLOW = "yellow"    # Requires review
    RED = "red"          # Block


@dataclass
class ComplianceIssue:
    """A compliance concern"""
    category: str
    severity: RiskLevel
    description: str
    recommendation: str


@dataclass
class ComplianceReport:
    """Compliance check results"""
    overall_risk: RiskLevel
    issues: List[ComplianceIssue]
    is_safe: bool  # True if GREEN or YELLOW

    def to_dict(self) -> Dict:
        return {
            'overall_risk': self.overall_risk.value,
            'is_safe': self.is_safe,
            'issues': [
                {
                    'category': i.category,
                    'severity': i.severity.value,
                    'description': i.description,
                    'recommendation': i.recommendation,
                }
                for i in self.issues
            ]
        }


class ComplianceChecker:
    """
    Check if a business idea is legally compliant.
    
    Usage:
        checker = ComplianceChecker()
        report = checker.check_idea(product_spec)
        
        if report.is_safe:
            print("✅ Safe to proceed")
        else:
            print("❌ BLOCKED:", report.overall_risk)
    """

    # Illegal keywords (RED flag)
    ILLEGAL_KEYWORDS = [
        'hack', 'crack', 'pirate', 'warez', 'keygen', 'ddos', 'botnet',
        'phishing', 'scam', 'fraud', 'fake', 'counterfeit', 'bypass',
        'gambling', 'casino', 'porn', 'adult content', 'drugs', 'weapons',
        'copyright infringement', 'trademark violation', 'steal', 'exploit database',
    ]

    # Risky keywords (YELLOW flag)
    RISKY_KEYWORDS = [
        'scraping', 'automation', 'bot', 'mass email', 'sms marketing',
        'web scraping', 'data extraction', 'proxy', 'vpn', 'anonymous',
        'crypto', 'nft', 'ico', 'token', 'investment', 'trading bot',
    ]

    # Requires GDPR compliance (EU users)
    GDPR_KEYWORDS = [
        'user data', 'personal information', 'email', 'tracking', 'analytics',
        'cookies', 'profile', 'account', 'authentication', 'database',
    ]

    def check_idea(self, product_spec: Dict) -> ComplianceReport:
        """
        Check if product idea is compliant.
        
        Args:
            product_spec: Product specification dict (from ProductBuilder)
        
        Returns:
            ComplianceReport
        """
        logger.info("⚖️  Running compliance checks...")

        issues = []

        # Extract text to analyze
        text = self._extract_text(product_spec)

        # 1. Illegal content check
        illegal_issues = self._check_illegal_content(text)
        issues.extend(illegal_issues)

        # 2. Risky activities check
        risky_issues = self._check_risky_activities(text)
        issues.extend(risky_issues)

        # 3. GDPR check
        gdpr_issues = self._check_gdpr(text, product_spec)
        issues.extend(gdpr_issues)

        # 4. Payment compliance
        payment_issues = self._check_payment_compliance(product_spec)
        issues.extend(payment_issues)

        # 5. ToS compliance
        tos_issues = self._check_tos_compliance(text, product_spec)
        issues.extend(tos_issues)

        # Determine overall risk
        if any(i.severity == RiskLevel.RED for i in issues):
            overall_risk = RiskLevel.RED
            is_safe = False
        elif any(i.severity == RiskLevel.YELLOW for i in issues):
            overall_risk = RiskLevel.YELLOW
            is_safe = True  # Can proceed with caution
        else:
            overall_risk = RiskLevel.GREEN
            is_safe = True

        report = ComplianceReport(
            overall_risk=overall_risk,
            issues=issues,
            is_safe=is_safe,
        )

        logger.info(f"{'✅' if is_safe else '❌'} Compliance check: {overall_risk.value.upper()}")
        logger.info(f"   Issues found: {len(issues)}")

        return report

    def _extract_text(self, spec: Dict) -> str:
        """Extract all text from spec for analysis"""
        parts = [
            spec.get('name', ''),
            spec.get('tagline', ''),
            spec.get('description', ''),
        ]

        # Features
        parts.extend(spec.get('features', []))

        # Pain points
        parts.extend(spec.get('pain_points', []))

        return ' '.join(parts).lower()

    def _check_illegal_content(self, text: str) -> List[ComplianceIssue]:
        """Check for illegal activities"""
        issues = []

        for keyword in self.ILLEGAL_KEYWORDS:
            if keyword in text:
                issues.append(ComplianceIssue(
                    category="Illegal Content",
                    severity=RiskLevel.RED,
                    description=f"Detected keyword: '{keyword}' (potentially illegal activity)",
                    recommendation="DO NOT PROCEED. This activity may be illegal in most jurisdictions."
                ))

        return issues

    def _check_risky_activities(self, text: str) -> List[ComplianceIssue]:
        """Check for risky but legal activities"""
        issues = []

        matches = []
        for keyword in self.RISKY_KEYWORDS:
            if keyword in text:
                matches.append(keyword)

        if matches:
            issues.append(ComplianceIssue(
                category="Risky Activity",
                severity=RiskLevel.YELLOW,
                description=f"Detected risky keywords: {', '.join(matches[:3])}",
                recommendation="REVIEW REQUIRED. Ensure compliance with platform ToS and applicable laws. Consult legal counsel."
            ))

        return issues

    def _check_gdpr(self, text: str, spec: Dict) -> List[ComplianceIssue]:
        """Check GDPR requirements"""
        issues = []

        # Check if product handles personal data
        handles_data = any(kw in text for kw in self.GDPR_KEYWORDS)

        if handles_data:
            issues.append(ComplianceIssue(
                category="GDPR Compliance",
                severity=RiskLevel.YELLOW,
                description="Product appears to handle personal data (EU GDPR applies)",
                recommendation="Implement: Privacy Policy, Cookie Consent, Data Deletion, Right to Access, Data Processing Agreements."
            ))

            # Check if privacy policy mentioned
            has_privacy = 'privacy' in text or 'gdpr' in text
            if not has_privacy:
                issues.append(ComplianceIssue(
                    category="Privacy Policy",
                    severity=RiskLevel.YELLOW,
                    description="No privacy policy mentioned",
                    recommendation="Add comprehensive privacy policy compliant with GDPR/CCPA before launch."
                ))

        return issues

    def _check_payment_compliance(self, spec: Dict) -> List[ComplianceIssue]:
        """Check payment processing compliance"""
        issues = []

        pricing_model = spec.get('pricing_model', '')
        tech_stack = spec.get('tech_stack', {})

        # If paid product, check payment processor
        if pricing_model in ['subscription', 'freemium', 'one-time']:
            payment_provider = tech_stack.get('payments', '').lower()

            if not payment_provider:
                issues.append(ComplianceIssue(
                    category="Payment Processing",
                    severity=RiskLevel.YELLOW,
                    description="Paid product without payment processor specified",
                    recommendation="Use PCI DSS compliant payment processor (Stripe, PayPal, Square)."
                ))
            elif payment_provider == 'stripe':
                # Stripe is good
                issues.append(ComplianceIssue(
                    category="Payment Processing",
                    severity=RiskLevel.GREEN,
                    description="Using Stripe (PCI DSS compliant)",
                    recommendation="Ensure proper Stripe integration and webhook security."
                ))

        return issues

    def _check_tos_compliance(self, text: str, spec: Dict) -> List[ComplianceIssue]:
        """Check Terms of Service compliance"""
        issues = []

        # Scraping check
        if 'scrap' in text:
            issues.append(ComplianceIssue(
                category="Web Scraping",
                severity=RiskLevel.YELLOW,
                description="Product involves web scraping",
                recommendation="Check target websites' robots.txt and ToS. Use APIs when available. Respect rate limits."
            ))

        # Automation/bot check
        if any(kw in text for kw in ['automation', 'bot', 'automated']):
            issues.append(ComplianceIssue(
                category="Automation",
                severity=RiskLevel.YELLOW,
                description="Product uses automation",
                recommendation="Ensure automation complies with platform ToS. Add proper User-Agent headers. Respect rate limits."
            ))

        # Email marketing check
        if any(kw in text for kw in ['email marketing', 'mass email', 'newsletter']):
            issues.append(ComplianceIssue(
                category="Email Marketing",
                severity=RiskLevel.YELLOW,
                description="Product involves email marketing",
                recommendation="Comply with CAN-SPAM Act / GDPR. Implement unsubscribe, double opt-in, clear sender identification."
            ))

        return issues

    def generate_legal_checklist(self, report: ComplianceReport, product_name: str) -> str:
        """Generate legal checklist for launch"""
        checklist = f"""# 📋 LEGAL CHECKLIST — {product_name}

**Overall Risk Level:** {report.overall_risk.value.upper()}  
**Safe to Proceed:** {'✅ YES' if report.is_safe else '❌ NO'}

---

## Issues Found ({len(report.issues)})

"""

        for i, issue in enumerate(report.issues, 1):
            emoji = {'green': '✅', 'yellow': '⚠️', 'red': '❌'}[issue.severity.value]

            checklist += f"""### {i}. {emoji} {issue.category} ({issue.severity.value.upper()})

**Issue:** {issue.description}  
**Action Required:** {issue.recommendation}

---

"""

        # Standard checklist
        checklist += """## Standard Pre-Launch Checklist

- [ ] Terms of Service page
- [ ] Privacy Policy page (GDPR compliant)
- [ ] Cookie Consent banner
- [ ] Contact information (email, address)
- [ ] Data deletion process
- [ ] Refund policy (if applicable)
- [ ] PCI DSS compliance (if handling payments)
- [ ] SSL certificate (HTTPS)
- [ ] Security audit (basic)
- [ ] Legal entity registration (if business)
- [ ] Business insurance (consider)
- [ ] Tax compliance setup

---

## Resources

- **GDPR:** https://gdpr.eu/
- **CAN-SPAM:** https://www.ftc.gov/business-guidance/resources/can-spam-act-compliance-guide-business
- **Stripe:** https://stripe.com/docs/security
- **ToS Generator:** https://www.termsfeed.com/

---

**Disclaimer:** This is NOT legal advice. Consult a qualified attorney for legal questions.

**Generated:** {report.issues[0].category if report.issues else 'N/A'}
"""

        return checklist

    def save_report(self, report: ComplianceReport, product_name: str, output_dir: Optional[Path] = None) -> Path:
        """Save compliance report"""
        if not output_dir:
            output_dir = Path.home() / ".beamax" / "compliance"

        output_dir.mkdir(parents=True, exist_ok=True)

        # JSON
        json_path = output_dir / f"{product_name}_compliance.json"
        json_path.write_text(json.dumps(report.to_dict(), indent=2))

        # Markdown checklist
        checklist = self.generate_legal_checklist(report, product_name)
        md_path = output_dir / f"{product_name}_legal_checklist.md"
        md_path.write_text(checklist)

        logger.info("💾 Compliance report saved:")
        logger.info(f"   JSON: {json_path}")
        logger.info(f"   Checklist: {md_path}")

        return md_path


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Check product compliance")
    parser.add_argument('spec_json', help='Path to product_spec.json')
    args = parser.parse_args()

    # Load spec
    with open(args.spec_json) as f:
        spec = json.load(f)

    # Check
    checker = ComplianceChecker()
    report = checker.check_idea(spec)

    # Print issues
    print("\n⚖️  COMPLIANCE REPORT\n")
    print(f"Overall Risk: {report.overall_risk.value.upper()}")
    print(f"Safe to Proceed: {'✅ YES' if report.is_safe else '❌ NO'}\n")

    if report.issues:
        print(f"Issues ({len(report.issues)}):\n")
        for i, issue in enumerate(report.issues, 1):
            emoji = {'green': '✅', 'yellow': '⚠️', 'red': '❌'}[issue.severity.value]
            print(f"{i}. {emoji} [{issue.category}] {issue.description}")
            print(f"   → {issue.recommendation}\n")
    else:
        print("✅ No compliance issues found!\n")

    # Save
    product_name = spec.get('name', 'product')
    path = checker.save_report(report, product_name)
    print(f"📄 Full checklist: {path}")


if __name__ == '__main__':
    main()
