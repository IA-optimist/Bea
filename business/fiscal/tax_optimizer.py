#!/usr/bin/env python3
"""
Tax Optimizer — Legal Tax Optimization for Micro-Entrepreneurs & SaaS Companies

DISCLAIMER: This is NOT legal or tax advice. Always consult a certified accountant.

Features:
1. Revenue structure optimization (company types: micro-entrepreneur, SARL, SAS, holding)
2. VAT strategies (intra-community, reverse charge, franchise base)
3. Expense tracking & categorization (deductible/non-deductible)
4. Tax calendar & deadlines (French: TVA, IS, CFE, CVAE, etc.)
5. International structures (Estonia e-Residency, Ireland, Luxembourg, etc.)
6. R&D tax credits (CIR - Crédit Impôt Recherche)
7. Patent box regimes
8. Dividend optimization

Target Markets:
- France (primary)
- EU (secondary)
- International (future)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class CompanyType(str, Enum):
    """French company types"""
    MICRO_ENTREPRENEUR = "micro_entrepreneur"  # Auto-entrepreneur
    EIRL = "eirl"  # Entrepreneur Individuel à Responsabilité Limitée
    EURL = "eurl"  # Entreprise Unipersonnelle à Responsabilité Limitée
    SARL = "sarl"  # Société à Responsabilité Limitée
    SAS = "sas"    # Société par Actions Simplifiée
    SASU = "sasu"  # SAS Unipersonnelle
    SA = "sa"      # Société Anonyme
    HOLDING = "holding"  # Holding company


class TaxRegime(str, Enum):
    """Tax regimes"""
    MICRO_BNC = "micro_bnc"  # Micro-BNC (professions libérales)
    MICRO_BIC = "micro_bic"  # Micro-BIC (commercial)
    REEL_SIMPLIFIE = "reel_simplifie"  # Réel simplifié
    REEL_NORMAL = "reel_normal"  # Réel normal
    IS = "is"  # Impôt sur les sociétés (corporate tax)
    IR = "ir"  # Impôt sur le revenu (income tax)


@dataclass
class TaxScenario:
    """Tax calculation scenario"""
    company_type: CompanyType
    tax_regime: TaxRegime
    annual_revenue: float
    expenses: float
    
    # Calculated
    taxable_income: float = 0.0
    corporate_tax: float = 0.0
    social_charges: float = 0.0
    income_tax: float = 0.0
    total_tax: float = 0.0
    net_income: float = 0.0
    effective_rate: float = 0.0
    
    # Breakdown
    breakdown: Dict[str, float] = field(default_factory=dict)
    
    def calculate(self):
        """Calculate all taxes"""
        # Simplified calculations (real formulas are complex!)
        
        profit = self.annual_revenue - self.expenses
        
        if self.company_type == CompanyType.MICRO_ENTREPRENEUR:
            # Micro-entrepreneur: abattement forfaitaire
            if self.tax_regime == TaxRegime.MICRO_BNC:
                abattement = 0.34  # 34% pour BNC
            else:
                abattement = 0.71  # 71% pour BIC vente, 50% pour services
            
            self.taxable_income = profit * (1 - abattement)
            
            # Social charges (cotisations sociales)
            if self.tax_regime == TaxRegime.MICRO_BNC:
                self.social_charges = self.annual_revenue * 0.22  # 22% BNC
            else:
                self.social_charges = self.annual_revenue * 0.128  # 12.8% BIC vente
            
            # Income tax (progressive scale - simplified)
            self.income_tax = self._calculate_income_tax(self.taxable_income)
            
            self.corporate_tax = 0.0
        
        elif self.company_type in [CompanyType.SARL, CompanyType.SAS, CompanyType.SASU]:
            # Company: Corporate tax (IS)
            self.taxable_income = profit
            
            # IS rates (France 2026)
            if self.taxable_income <= 42500:
                self.corporate_tax = self.taxable_income * 0.15  # 15% reduced rate
            else:
                self.corporate_tax = (42500 * 0.15) + ((self.taxable_income - 42500) * 0.25)  # 25% standard
            
            # Dividends
            net_profit_after_tax = self.taxable_income - self.corporate_tax
            dividends = net_profit_after_tax * 0.70  # 70% distributed, 30% retained
            
            # Flat tax on dividends (PFU)
            dividend_tax = dividends * 0.30  # 30% flat tax (12.8% IR + 17.2% social)
            
            # Social charges on salary (if applicable)
            # Assuming 50k€ salary for founder
            salary = min(50000, self.taxable_income * 0.30)
            self.social_charges = salary * 0.82  # ~82% total charges (employer + employee)
            
            self.income_tax = dividend_tax + self._calculate_income_tax(salary)
            
            self.net_income = net_profit_after_tax - dividends * 0.30
        
        else:
            # Other company types (simplified)
            self.taxable_income = profit
            self.corporate_tax = self.taxable_income * 0.25
            self.social_charges = self.taxable_income * 0.45
            self.income_tax = 0.0
            self.net_income = self.taxable_income - self.corporate_tax - self.social_charges
        
        # Total
        self.total_tax = self.corporate_tax + self.social_charges + self.income_tax
        self.net_income = self.annual_revenue - self.expenses - self.total_tax
        
        if self.annual_revenue > 0:
            self.effective_rate = (self.total_tax / self.annual_revenue) * 100
        
        # Breakdown
        self.breakdown = {
            'revenue': self.annual_revenue,
            'expenses': self.expenses,
            'profit_before_tax': profit,
            'taxable_income': self.taxable_income,
            'corporate_tax': self.corporate_tax,
            'social_charges': self.social_charges,
            'income_tax': self.income_tax,
            'total_tax': self.total_tax,
            'net_income': self.net_income,
            'effective_rate': self.effective_rate,
        }
    
    def _calculate_income_tax(self, income: float) -> float:
        """
        Simplified French income tax (barème progressif 2026)
        
        Tranches:
        - 0 - 11,294€: 0%
        - 11,295 - 28,797€: 11%
        - 28,798 - 82,341€: 30%
        - 82,342 - 177,106€: 41%
        - > 177,106€: 45%
        """
        if income <= 11294:
            return 0.0
        elif income <= 28797:
            return (income - 11294) * 0.11
        elif income <= 82341:
            return (28797 - 11294) * 0.11 + (income - 28797) * 0.30
        elif income <= 177106:
            return (28797 - 11294) * 0.11 + (82341 - 28797) * 0.30 + (income - 82341) * 0.41
        else:
            return (28797 - 11294) * 0.11 + (82341 - 28797) * 0.30 + (177106 - 82341) * 0.41 + (income - 177106) * 0.45
    
    def to_dict(self) -> Dict:
        return {
            'company_type': self.company_type.value,
            'tax_regime': self.tax_regime.value,
            'annual_revenue': round(self.annual_revenue, 2),
            'expenses': round(self.expenses, 2),
            'breakdown': {k: round(v, 2) for k, v in self.breakdown.items()},
        }


@dataclass
class TaxRecommendation:
    """Tax optimization recommendation"""
    title: str
    description: str
    savings: float  # Estimated annual savings
    implementation_cost: float  # One-time cost
    complexity: str  # low, medium, high
    legality: str  # fully_legal, gray_area, aggressive
    
    def to_dict(self) -> Dict:
        return {
            'title': self.title,
            'description': self.description,
            'savings': round(self.savings, 2),
            'implementation_cost': round(self.implementation_cost, 2),
            'complexity': self.complexity,
            'legality': self.legality,
        }


class TaxOptimizer:
    """
    Optimize tax structure for micro-SaaS companies.
    
    Usage:
        optimizer = TaxOptimizer()
        
        # Compare scenarios
        comparison = optimizer.compare_scenarios(
            revenue=100000,
            expenses=30000
        )
        
        # Get recommendations
        recommendations = optimizer.get_recommendations(
            current_type=CompanyType.MICRO_ENTREPRENEUR,
            revenue=100000
        )
    """
    
    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path.home() / ".beamax" / "fiscal"
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def compare_scenarios(
        self,
        revenue: float,
        expenses: float,
        scenarios: Optional[List[tuple]] = None
    ) -> List[TaxScenario]:
        """
        Compare tax scenarios for given revenue/expenses.
        
        Args:
            revenue: Annual revenue (€)
            expenses: Annual expenses (€)
            scenarios: List of (CompanyType, TaxRegime) tuples. If None, compare all.
        
        Returns:
            List of TaxScenario, sorted by net income (descending)
        """
        logger.info("💶 Comparing tax scenarios...")
        logger.info(f"   Revenue: €{revenue:,.2f}")
        logger.info(f"   Expenses: €{expenses:,.2f}")
        
        if not scenarios:
            # Default scenarios to compare
            scenarios = [
                (CompanyType.MICRO_ENTREPRENEUR, TaxRegime.MICRO_BNC),
                (CompanyType.MICRO_ENTREPRENEUR, TaxRegime.MICRO_BIC),
                (CompanyType.SASU, TaxRegime.IS),
                (CompanyType.SAS, TaxRegime.IS),
                (CompanyType.SARL, TaxRegime.IS),
            ]
        
        results = []
        
        for company_type, tax_regime in scenarios:
            scenario = TaxScenario(
                company_type=company_type,
                tax_regime=tax_regime,
                annual_revenue=revenue,
                expenses=expenses,
            )
            scenario.calculate()
            results.append(scenario)
        
        # Sort by net income (descending)
        results.sort(key=lambda s: s.net_income, reverse=True)
        
        logger.info(f"✅ Comparison complete: {len(results)} scenarios")
        
        return results
    
    def get_recommendations(
        self,
        current_type: CompanyType,
        revenue: float,
        expenses: float = 0.0,
    ) -> List[TaxRecommendation]:
        """
        Get tax optimization recommendations.
        
        Args:
            current_type: Current company type
            revenue: Annual revenue (€)
            expenses: Annual expenses (€)
        
        Returns:
            List of recommendations
        """
        recommendations = []
        
        # 1. Company structure optimization
        if current_type == CompanyType.MICRO_ENTREPRENEUR and revenue > 77700:
            recommendations.append(TaxRecommendation(
                title="Passer en société (SASU/SAS)",
                description="Au-delà de 77,700€ de CA, le régime micro-entrepreneur n'est plus optimal. Une SASU/SAS permet de déduire les charges réelles et d'optimiser la rémunération (salaire + dividendes).",
                savings=revenue * 0.15,  # ~15% savings
                implementation_cost=1500,  # Frais création société
                complexity="medium",
                legality="fully_legal",
            ))
        
        # 2. Holding structure
        if revenue > 200000 and current_type in [CompanyType.SAS, CompanyType.SARL]:
            recommendations.append(TaxRecommendation(
                title="Créer une holding (intégration fiscale)",
                description="Structure holding → filiales permet de mutualiser les bénéfices/pertes, reporter les déficits, optimiser les dividendes (régime mère-fille), et préparer la transmission.",
                savings=revenue * 0.08,
                implementation_cost=3000,
                complexity="high",
                legality="fully_legal",
            ))
        
        # 3. R&D tax credit (CIR)
        if revenue > 50000:
            recommendations.append(TaxRecommendation(
                title="Crédit Impôt Recherche (CIR)",
                description="Si votre activité SaaS inclut de l'innovation technique (IA, algorithmes, etc.), vous pouvez déduire 30% des dépenses de R&D (salaires chercheurs, brevets, prototypes). Cumulable avec le CII (innovation).",
                savings=min(revenue * 0.30 * 0.50, 100000),  # 30% des dépenses R&D (assume 50% du CA)
                implementation_cost=5000,  # Expert CIR
                complexity="high",
                legality="fully_legal",
            ))
        
        # 4. International structure (Estonia e-Residency)
        if revenue > 100000:
            recommendations.append(TaxRecommendation(
                title="E-Residency Estonie (0% IS tant que bénéfices non distribués)",
                description="Créer une OÜ (société estonienne) via e-Residency. Avantages: 0% d'impôt sur les bénéfices réinvestis, 20% seulement sur dividendes distribués, 100% digital, comptabilité simplifiée. Attention: toujours soumis à TVA française si clients FR.",
                savings=revenue * 0.10,
                implementation_cost=2000,
                complexity="high",
                legality="gray_area",  # Légal mais substance économique requise
            ))
        
        # 5. VAT optimization
        if revenue > 85000:
            recommendations.append(TaxRecommendation(
                title="Franchise TVA → TVA intra-communautaire",
                description="Si vous avez des clients B2B européens, passer à la TVA permet d'utiliser l'auto-liquidation (reverse charge) et de récupérer la TVA sur vos achats. Gain net si > 85k€.",
                savings=expenses * 0.20,  # 20% TVA récupérable sur achats
                implementation_cost=500,
                complexity="low",
                legality="fully_legal",
            ))
        
        # 6. Expense optimization
        recommendations.append(TaxRecommendation(
            title="Maximiser les charges déductibles",
            description="Déductibles: bureau (loyer, électricité), matériel (ordinateur, téléphone), formations, logiciels SaaS, déplacements pros, repas clients (< 6,70€ déductibles à 100%), assurance RC Pro. Non-déductibles: amendes, cadeaux > 73€/personne.",
            savings=expenses * 0.25 * 0.25,  # 25% d'expenses supplémentaires → 25% d'IS économisé
            implementation_cost=0,
            complexity="low",
            legality="fully_legal",
        ))
        
        # 7. Dividend timing
        if current_type in [CompanyType.SAS, CompanyType.SARL, CompanyType.SASU]:
            recommendations.append(TaxRecommendation(
                title="Optimiser le timing des dividendes",
                description="Distribuer des dividendes uniquement quand vous en avez besoin (flat tax 30%). Sinon, laissez les bénéfices en trésorerie société (0% taxe). Permet de réinvestir et de lisser les revenus perso sur plusieurs années.",
                savings=revenue * 0.05,
                implementation_cost=0,
                complexity="low",
                legality="fully_legal",
            ))
        
        # Sort by savings / implementation cost ratio
        recommendations.sort(key=lambda r: r.savings / max(r.implementation_cost, 1), reverse=True)
        
        return recommendations
    
    def generate_report(
        self,
        scenarios: List[TaxScenario],
        recommendations: List[TaxRecommendation],
        revenue: float,
        expenses: float,
    ) -> str:
        """Generate markdown tax optimization report"""
        
        best_scenario = scenarios[0] if scenarios else None
        
        report = f"""# 💶 TAX OPTIMIZATION REPORT

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
**Revenue:** €{revenue:,.2f}/year  
**Expenses:** €{expenses:,.2f}/year  

---

## 🎯 Best Scenario

"""
        
        if best_scenario:
            report += f"""**Company Type:** {best_scenario.company_type.value}  
**Tax Regime:** {best_scenario.tax_regime.value}  

**Financial Summary:**
- Revenue: €{best_scenario.annual_revenue:,.2f}
- Expenses: €{best_scenario.expenses:,.2f}
- **Net Income: €{best_scenario.net_income:,.2f}**
- Total Tax: €{best_scenario.total_tax:,.2f}
- **Effective Rate: {best_scenario.effective_rate:.1f}%**

**Breakdown:**
- Corporate Tax (IS): €{best_scenario.corporate_tax:,.2f}
- Social Charges: €{best_scenario.social_charges:,.2f}
- Income Tax (IR): €{best_scenario.income_tax:,.2f}

---

## 📊 Scenario Comparison

| Company Type | Tax Regime | Net Income | Total Tax | Effective Rate |
|--------------|------------|------------|-----------|----------------|
"""
            
            for s in scenarios[:5]:
                report += f"| {s.company_type.value} | {s.tax_regime.value} | €{s.net_income:,.0f} | €{s.total_tax:,.0f} | {s.effective_rate:.1f}% |\n"
        
        report += f"""
---

## 💡 Recommendations ({len(recommendations)})

"""
        
        for i, rec in enumerate(recommendations, 1):
            legality_emoji = {
                'fully_legal': '✅',
                'gray_area': '⚠️',
                'aggressive': '❌'
            }.get(rec.legality, '❓')
            
            complexity_emoji = {
                'low': '🟢',
                'medium': '🟡',
                'high': '🔴'
            }.get(rec.complexity, '⚪')
            
            report += f"""### {i}. {rec.title}

{rec.description}

- **Savings:** €{rec.savings:,.2f}/year
- **Implementation Cost:** €{rec.implementation_cost:,.2f}
- **ROI:** {(rec.savings / max(rec.implementation_cost, 1)):.1f}x
- **Complexity:** {complexity_emoji} {rec.complexity}
- **Legality:** {legality_emoji} {rec.legality}

---

"""
        
        report += """
## ⚠️ DISCLAIMER

**This is NOT legal or tax advice.**

Tax laws are complex and change frequently. Always consult:
- A certified accountant (expert-comptable)
- A tax lawyer (avocat fiscaliste)
- URSSAF / Impôts.gouv.fr

**Recommended Resources:**
- https://www.impots.gouv.fr/
- https://www.autoentrepreneur.urssaf.fr/
- https://bpifrance-creation.fr/
- https://www.service-public.fr/professionnels-entreprises

---

**Generated by BeaMax Fiscal Optimizer**  
**Version:** 1.0.0
"""
        
        return report
    
    def save_report(self, report: str, filename: str = "tax_optimization_report.md") -> Path:
        """Save report to file"""
        report_path = self.data_dir / filename
        report_path.write_text(report)
        
        logger.info(f"💾 Report saved: {report_path}")
        
        return report_path


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Tax optimization analyzer")
    parser.add_argument('--revenue', type=float, required=True, help='Annual revenue (€)')
    parser.add_argument('--expenses', type=float, default=0, help='Annual expenses (€)')
    parser.add_argument('--current', help='Current company type', 
                       choices=[t.value for t in CompanyType],
                       default=CompanyType.MICRO_ENTREPRENEUR.value)
    args = parser.parse_args()
    
    optimizer = TaxOptimizer()
    
    # Compare scenarios
    scenarios = optimizer.compare_scenarios(args.revenue, args.expenses)
    
    # Get recommendations
    current_type = CompanyType(args.current)
    recommendations = optimizer.get_recommendations(current_type, args.revenue, args.expenses)
    
    # Generate report
    report = optimizer.generate_report(scenarios, recommendations, args.revenue, args.expenses)
    
    print(report)
    
    # Save
    optimizer.save_report(report)


if __name__ == '__main__':
    main()
