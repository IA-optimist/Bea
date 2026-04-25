"""core.autonomy — primitives for goal-driven autonomy.

Layered architecture :

  event_bus       : in-process pub/sub
  budget          : per-mission + daily limits (tokens, $, time, failures)
  stop_conditions : composable predicates that halt a loop
  daemon          : the outer loop (uses bus + budget + stop_conditions)
  skills          : registry of named, parameterizable workflows
  builtin_skills  : default skills shipped with JarvisMax
  learning        : outcome aggregator wired to the bus
  multi_choice    : human-in-the-loop multi-option decisions

Each layer is independently importable and unit-tested. The daemon
orchestrates them but never bypasses approval / budget.
"""
from core.autonomy.budget import (
    Budget,
    BudgetExceeded,
    BudgetTracker,
    get_budget_tracker,
    reset_budget_tracker,
)
from core.autonomy.daemon import (
    ActionResult,
    AutonomyDaemon,
    PlannedAction,
    event_bus_runner,
)
from core.autonomy.event_bus import (
    Event,
    EventBus,
    get_event_bus,
    reset_event_bus,
)
from core.autonomy.learning import (
    OutcomeLearner,
    get_outcome_learner,
    reset_outcome_learner,
)
from core.autonomy.multi_choice import (
    Choice,
    Decision,
    MultiChoiceStore,
    ask,
    get_multi_choice_store,
    reset_multi_choice_store,
)
from core.autonomy.skills import (
    Skill,
    SkillContext,
    SkillRegistry,
    SkillResult,
    get_skill_registry,
    register_skill,
    reset_skill_registry,
)
from core.autonomy.stop_conditions import (
    StopCheck,
    StopContext,
    all_of,
    any_of,
    confidence_condition,
    consecutive_failures_condition,
    default_mission_policy,
    iteration_condition,
    timeout_condition,
)

__all__ = [
    # event_bus
    "Event", "EventBus", "get_event_bus", "reset_event_bus",
    # budget
    "Budget", "BudgetExceeded", "BudgetTracker",
    "get_budget_tracker", "reset_budget_tracker",
    # daemon
    "ActionResult", "AutonomyDaemon", "PlannedAction", "event_bus_runner",
    # stop_conditions
    "StopCheck", "StopContext",
    "all_of", "any_of", "confidence_condition", "consecutive_failures_condition",
    "default_mission_policy", "iteration_condition", "timeout_condition",
    # skills
    "Skill", "SkillContext", "SkillRegistry", "SkillResult",
    "get_skill_registry", "register_skill", "reset_skill_registry",
    # learning
    "OutcomeLearner", "get_outcome_learner", "reset_outcome_learner",
    # multi_choice
    "Choice", "Decision", "MultiChoiceStore", "ask",
    "get_multi_choice_store", "reset_multi_choice_store",
]
