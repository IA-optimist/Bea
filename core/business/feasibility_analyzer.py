"""
JarvisMax — Feasibility Analyzer (P3.2)
Cognition-powered technical feasibility analysis for SaaS opportunities

Uses CognitionOrchestrator with Tree-of-Thought for multi-path analysis
"""
from __future__ import annotations

import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime
import uuid

from core.cognition.orchestrator import CognitionOrchestrator
from models.opportunity import Opportunity

logger = logging.getLogger(__name__)


class FeasibilityAnalyzer:
    """
    Analyze technical feasibility of SaaS opportunities
    
    Process:
    1. Extract opportunity details (title, description, pain points)
    2. Generate analysis prompt
    3. Execute cognition mission (Tree-of-Thought)
    4. Parse structured output
    5. Return analysis result
    
    Cognition confidence threshold: 0.8 (high confidence required)
    """
    
    
    def __init__(self):
        from core.llm_factory import LLMFactory
        from config.settings import get_settings
        settings = get_settings()
        factory = LLMFactory(settings)
        llm = factory.get(role="cognition")
        self.cognition = CognitionOrchestrator(llm_client=llm)

    async def analyze(self, opportunity: Opportunity, project_id: int = 1) -> Dict[str, Any]:
        """
        Analyze technical feasibility of an opportunity
        
        Args:
            opportunity: Opportunity object from database
            project_id: JarvisMax project ID (default: 1 = Central Chat)
        
        Returns:
            Dict with analysis results:
            {
                "recommendation": "BUILD" | "SKIP" | "NEEDS_MORE_RESEARCH",
                "reasoning": str,
                "tech_stack": ["python", "fastapi", ...],
                "dependencies": ["stripe", "sendgrid", ...],
                "complexity_score": 1-10,
                "estimated_hours": int,
                "mvp_features": ["user_auth", "dashboard", ...],
                "nice_to_have_features": [...],
                "out_of_scope": [...],
                "technical_risks": ["API rate limits", ...],
                "mitigation_strategies": ["Implement caching", ...],
                "market_fit_score": 0-100,
                "confidence_score": 0.0-1.0,
                "cognition_reasoning": str,
                "full_analysis": str,
                "mission_id": str,
                "duration_seconds": int,
            }
        """
        start_time = time.time()
        
        # Build analysis prompt
        prompt = self._build_analysis_prompt(opportunity)
        
        # Create mission dict (cognition expects Dict, not MissionState)
        mission_id = f"feasibility-{opportunity.id}-{uuid.uuid4().hex[:8]}"
        mission = {
            "mission_id": mission_id,
            "goal": f"Analyze technical feasibility: {opportunity.title}",
            "project_id": project_id,
            "metadata": {
                "opportunity_id": opportunity.id,
                "opportunity_url": opportunity.url,
                "source": opportunity.source,
                "total_score": opportunity.total_score,
            },
            "user_input": prompt,
        }
        
        logger.info(f"feasibility_analysis_started opportunity_id={opportunity.id} mission={mission_id}")
        
        try:
            # Execute cognition analysis
            result = await self.cognition.execute_mission_with_cognition(
                mission,
                enable_tot=True,
                enable_confidence=True,
                enable_learning=True,
            )
            
            duration = int(time.time() - start_time)
            
            # Parse result
            analysis = self._parse_analysis_result(result, opportunity, mission_id, duration)
            
            logger.info(
                f"feasibility_analysis_completed "
                f"opportunity_id={opportunity.id} "
                f"mission={mission_id} "
                f"recommendation={analysis.get('recommendation')} "
                f"confidence={analysis.get('confidence_score', 0):.3f} "
                f"duration={duration}s"
            )
            
            return analysis
        
        except Exception as e:
            logger.error(f"feasibility_analysis_failed opportunity_id={opportunity.id}: {e}", exc_info=True)
            duration = int(time.time() - start_time)
            
            # Return safe fallback
            return {
                "recommendation": "NEEDS_MORE_RESEARCH",
                "reasoning": f"Analysis failed: {str(e)}",
                "confidence_score": 0.0,
                "mission_id": mission_id,
                "duration_seconds": duration,
                "error": str(e),
            }
    
    def _build_analysis_prompt(self, opportunity: Opportunity) -> str:
        """Build cognition analysis prompt"""
        return f"""You are a senior technical architect analyzing the feasibility of building a SaaS MVP.

# OPPORTUNITY DETAILS

**Title:** {opportunity.title}

**Description:** {opportunity.description}

**Source:** {opportunity.source} (discovered: {opportunity.discovered_at.strftime('%Y-%m-%d')})

**Pain Points:**
{chr(10).join(f"• {p}" for p in (opportunity.pain_points or [])[:5])}

**Market Signals:**
• Upvotes: {opportunity.upvotes}
• Comments: {opportunity.comments}
• Demand Score: {opportunity.demand_score}/100
• Competition Score: {opportunity.competition_score}/100
• Monetization Score: {opportunity.monetization_score}/100

**Tags:** {', '.join(opportunity.tags or [])}

---

# YOUR TASK

Provide a comprehensive technical feasibility analysis with the following structure:

## 1. RECOMMENDATION
Choose ONE:
- **BUILD**: High confidence this is viable, proceed to MVP generation
- **SKIP**: Not technically feasible or too risky, abandon
- **NEEDS_MORE_RESEARCH**: Uncertain, requires more investigation

## 2. REASONING
Explain your recommendation in 2-3 sentences. What are the key factors?

## 3. TECH STACK
List recommended technologies (backend, frontend, database, infrastructure).
Format: ["python", "fastapi", "react", "postgresql", "docker", "redis"]

## 4. DEPENDENCIES
List external services/APIs needed (payment, email, AI, etc.).
Format: ["stripe", "sendgrid", "openai", "twilio"]

## 5. COMPLEXITY SCORE
Rate 1-10:
- 1-3: Simple CRUD app, < 1 week
- 4-6: Moderate complexity, 1-2 weeks
- 7-8: Complex integrations, 3-4 weeks
- 9-10: Very complex, > 1 month

## 6. ESTIMATED HOURS
Total development time for MVP (integer).

## 7. MVP FEATURES (Core)
What MUST be in v1? List 5-10 features.
Format: ["user_registration", "dashboard", "api_integration", "payment", "admin_panel"]

## 8. NICE-TO-HAVE FEATURES
What can wait for v2?
Format: ["social_login", "advanced_analytics", "mobile_app"]

## 9. OUT OF SCOPE
What should we explicitly NOT build for MVP?
Format: ["white_label", "enterprise_sso", "on_premise_deployment"]

## 10. TECHNICAL RISKS
What could go wrong? List 3-5 risks.
Format: ["API rate limits", "Complex authentication flow", "Real-time sync complexity"]

## 11. MITIGATION STRATEGIES
How to handle each risk?
Format: ["Implement caching layer", "Use OAuth library", "Queue-based processing"]

## 12. MARKET FIT SCORE
Rate 0-100: How well does the technical solution match the market demand?
Consider: demand score, pain points, competition, monetization potential.

---

# OUTPUT FORMAT

Respond with a structured analysis in this EXACT format:

```
RECOMMENDATION: [BUILD|SKIP|NEEDS_MORE_RESEARCH]

REASONING:
[Your 2-3 sentence explanation]

TECH_STACK:
["item1", "item2", ...]

DEPENDENCIES:
["item1", "item2", ...]

COMPLEXITY_SCORE: [1-10]

ESTIMATED_HOURS: [integer]

MVP_FEATURES:
["feature1", "feature2", ...]

NICE_TO_HAVE:
["feature1", "feature2", ...]

OUT_OF_SCOPE:
["feature1", "feature2", ...]

TECHNICAL_RISKS:
["risk1", "risk2", ...]

MITIGATION:
["strategy1", "strategy2", ...]

MARKET_FIT_SCORE: [0-100]
```

**IMPORTANT:** Use JSON array format for all lists. Be specific and actionable."""
    
    def _parse_analysis_result(
        self,
        result: Dict[str, Any],
        opportunity: Opportunity,
        mission_id: str,
        duration_seconds: int,
    ) -> Dict[str, Any]:
        """
        Parse cognition result into structured analysis
        
        Extracts fields from result['response'] text using simple parsing
        Falls back to safe defaults if parsing fails
        """
        response_text = result.get("response", "")
        confidence = result.get("confidence", {})
        
        # Extract structured data from response text
        parsed = self._extract_structured_data(response_text)
        
        return {
            # Recommendation
            "recommendation": parsed.get("recommendation", "NEEDS_MORE_RESEARCH"),
            "reasoning": parsed.get("reasoning", "Analysis incomplete"),
            
            # Technical
            "tech_stack": parsed.get("tech_stack", []),
            "dependencies": parsed.get("dependencies", []),
            "complexity_score": parsed.get("complexity_score", 5),
            "estimated_hours": parsed.get("estimated_hours", 40),
            
            # MVP scope
            "mvp_features": parsed.get("mvp_features", []),
            "nice_to_have_features": parsed.get("nice_to_have", []),
            "out_of_scope": parsed.get("out_of_scope", []),
            
            # Risks
            "technical_risks": parsed.get("technical_risks", []),
            "mitigation_strategies": parsed.get("mitigation", []),
            
            # Scores
            "market_fit_score": parsed.get("market_fit_score", opportunity.total_score),
            
            # Cognition metadata
            "confidence_score": confidence.get("score", 0.0),
            "cognition_reasoning": confidence.get("reasoning", ""),
            "full_analysis": response_text,
            "mission_id": mission_id,
            "duration_seconds": duration_seconds,
        }
    
    def _extract_structured_data(self, text: str) -> Dict[str, Any]:
        """
        Extract structured data from analysis text
        
        Simple line-by-line parser:
        - RECOMMENDATION: BUILD
        - TECH_STACK: ["python", "fastapi"]
        - COMPLEXITY_SCORE: 5
        """
        import re
        import json
        
        result = {}
        
        # Extract single-line fields
        patterns = {
            "recommendation": r"RECOMMENDATION:\s*(\w+)",
            "complexity_score": r"COMPLEXITY_SCORE:\s*(\d+)",
            "estimated_hours": r"ESTIMATED_HOURS:\s*(\d+)",
            "market_fit_score": r"MARKET_FIT_SCORE:\s*(\d+)",
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                value = match.group(1)
                if key in ["complexity_score", "estimated_hours", "market_fit_score"]:
                    result[key] = int(value)
                else:
                    result[key] = value.upper()
        
        # Extract multi-line text (REASONING)
        reasoning_match = re.search(r"REASONING:\s*\n(.*?)(?=\n[A-Z_]+:|$)", text, re.DOTALL)
        if reasoning_match:
            result["reasoning"] = reasoning_match.group(1).strip()
        
        # Extract JSON arrays
        array_fields = [
            "tech_stack", "dependencies", "mvp_features",
            "nice_to_have", "out_of_scope", "technical_risks", "mitigation"
        ]
        
        for field in array_fields:
            pattern = rf"{field.upper().replace('_', '_')}:\s*\n(\[.*?\])"
            match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                try:
                    result[field] = json.loads(match.group(1))
                except json.JSONDecodeError:
                    # Try simple comma-split fallback
                    raw = match.group(1).strip('[]')
                    result[field] = [item.strip(' "\'') for item in raw.split(',') if item.strip()]
        
        return result
