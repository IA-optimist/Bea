# Phase 7: Business Engine + AGI Integration (NEXT SESSION)

## Goal
Wire Phase 5 AGI cognition (Tree-of-Thought + Lifelong Learning) into Business Engine for autonomous profit generation.

## Current State (Phase 5 Complete)

**Cognition Modules Ready:**
- ✅ Tree-of-Thought (multi-path reasoning)
- ✅ Multi-Project Context (isolation + switching)
- ✅ Lifelong Learning (Voyager-style skill extraction)
- ✅ Chat API (conversational entry point)

**Business Engine Status:**
- ✅ ToT already integrated in FeasibilityAnalyzer (SHA cdb93b7)
- ⏳ Lifelong Learning NOT wired yet
- ⏳ Multi-project portfolio tracking NOT implemented
- ⏳ Performance metrics API NOT exposed

## Phase 7 Tasks

### 7.1: Wire Lifelong Learning into Business Pipeline
**Files to modify:**
- `core/business/feasibility_analyzer.py` — record missions
- `core/business/mission_runner.py` — auto skill extraction
- `api/routes/business.py` — add learning endpoints

**Features:**
- Auto-extract successful business patterns as skills
- Suggest skills for similar opportunities
- Track skill performance (success rate, confidence)
- Skill library API (`/api/v3/business/skills`)

### 7.2: Multi-Project Business Portfolio
**New file:** `core/business/portfolio_manager.py`

**Features:**
- Track opportunities per project
- Project-specific business metrics
- Cross-project skill transfer
- Portfolio performance dashboard

### 7.3: Performance Metrics API
**Endpoints to add:**
- `GET /api/v3/business/performance` — global metrics
- `GET /api/v3/business/performance/projects/{id}` — per-project
- `GET /api/v3/business/skills` — learned skills library
- `GET /api/v3/business/skills/suggest` — skill suggestions

### 7.4: First Autonomous Revenue Test
**Goal:** Generate + deploy ONE MVP autonomously

**Steps:**
1. Scan opportunities (existing)
2. Analyze with ToT (existing)
3. Generate MVP with skills (NEW)
4. Deploy with learning feedback (NEW)
5. Track revenue potential (NEW)

**Success Criteria:**
- MVP generated end-to-end
- Deployed to production
- Learning captured (skills extracted)
- No human intervention (except approval gates)

## Integration Points

### FeasibilityAnalyzer + Lifelong Learning
```python
# In feasibility_analyzer.py
from core.cognition.lifelong_learning import LifelongLearningEngine

class FeasibilityAnalyzer:
    def __init__(self, ...):
        self.learning_engine = LifelongLearningEngine()
    
    async def analyze(self, opportunity):
        # Existing ToT analysis
        result = await self.analyze_with_tot(opportunity)
        
        # NEW: Record for learning
        await self.learning_engine.record_mission(
            mission_id=f"biz-{opportunity.id}",
            goal=f"Analyze {opportunity.title}",
            result=result["analysis"],
            success=result["feasibility_score"] > 0.7,
            confidence=result.get("confidence", 0.5),
            tools_used=["tot", "feasibility_check"],
            execution_trace=result.get("reasoning_tree", [])
        )
        
        # Suggest relevant skills
        skills = await self.learning_engine.suggest_skills_for_goal(
            opportunity.title, limit=3
        )
        result["suggested_skills"] = skills
        
        return result
```

### MissionRunner + Skill Application
```python
# In mission_runner.py
async def run_with_skills(self, mission, suggested_skills):
    # Apply learned skills if validated
    for skill in suggested_skills:
        if skill.is_validated:
            # Execute skill code/sequence
            await self.apply_skill(mission, skill)
    
    # Run normal mission
    result = await self.run(mission)
    
    # Update skill success/failure
    for skill in suggested_skills:
        if result.success:
            skill.success_count += 1
        else:
            skill.failure_count += 1
    
    return result
```

## Metrics to Track

**Business Metrics:**
- Opportunities scanned
- Opportunities analyzed (with ToT)
- MVPs generated
- MVPs deployed
- Estimated revenue potential
- Actual revenue (when live)

**Learning Metrics:**
- Skills discovered
- Skills validated (>70% success)
- Skill application rate
- Skill composition patterns
- Failure pattern detection

**Cognition Metrics:**
- ToT usage rate (complex queries)
- Self-correction triggers
- Multi-project context switches
- Average confidence scores

## API Design (Phase 7)

### Business Performance
```http
GET /api/v3/business/performance
Response:
{
  "total_opportunities": 42,
  "analyzed": 38,
  "mvps_generated": 12,
  "mvps_deployed": 5,
  "estimated_revenue": "€15,000/month",
  "learning_stats": {
    "skills_discovered": 23,
    "skills_validated": 8,
    "skill_application_rate": 0.65
  }
}
```

### Skill Library
```http
GET /api/v3/business/skills?validated=true
Response:
{
  "skills": [
    {
      "skill_id": "skill-a3f2c1",
      "name": "Auto: SaaS MVP Generator Pattern",
      "success_rate": 0.85,
      "uses": 12,
      "confidence": 0.78,
      "tags": ["mvp", "saas", "fastapi"]
    }
  ]
}
```

### Skill Suggestion
```http
GET /api/v3/business/skills/suggest?goal=Build%20AI%20chatbot%20SaaS
Response:
{
  "suggestions": [
    {
      "skill_id": "skill-b7d9e2",
      "name": "AI API Integration Pattern",
      "relevance": 0.92,
      "success_rate": 0.80
    }
  ]
}
```

## Timeline Estimate

**Total: ~120 minutes (2 hours)**

- 7.1 Learning integration: 30 min
- 7.2 Portfolio manager: 30 min
- 7.3 Performance API: 30 min
- 7.4 First test run: 30 min

## Success Criteria (Phase 7 Complete)

✅ Lifelong Learning wired into business pipeline  
✅ Skills auto-extracted from successful MVPs  
✅ Multi-project portfolio tracking  
✅ Performance metrics API live  
✅ First autonomous MVP deployed with learning  
✅ €65k/month revenue target pathway validated

## Risk Mitigation

**Risk:** Skill extraction too aggressive (noise)  
**Mitigation:** Confidence threshold (>0.8), validation requirement (3+ uses, >70% success)

**Risk:** Multi-project context confusion  
**Mitigation:** Project isolation already implemented (Phase 5.2)

**Risk:** ToT overhead on simple opportunities  
**Mitigation:** Complexity detection (Phase 5.3), ToT only for "compare", "vs", "complex" keywords

## Next Session Checklist

1. [ ] Review Phase 5 deliverables (this session)
2. [ ] Implement 7.1 (Learning + Business)
3. [ ] Implement 7.2 (Portfolio Manager)
4. [ ] Implement 7.3 (Performance API)
5. [ ] Run 7.4 (First autonomous test)
6. [ ] Commit Phase 7
7. [ ] Update VISION.md with Phase 8 targets

---

**Phase 7 = AUTONOMOUS PROFIT ENGINE LIVE!!! 💰🚀**
