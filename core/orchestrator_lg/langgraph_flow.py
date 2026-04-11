"""
LangGraph orchestration backbone for JarvisMax.
Implements explicit graph-based execution flow.
Coexists with existing orchestrator — use USE_LANGGRAPH=true to activate.

NOTE: AgentRunner.run(agent_name, goal, settings) — adapter la signature.
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Fail-open imports ─────────────────────────────────────────────────────────
try:
    from langgraph.graph import StateGraph, END
    _LANGGRAPH_OK = True
except ImportError:
    _LANGGRAPH_OK = False
    logger.warning("[LangGraph] langgraph not installed — graph disabled")

try:
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage  # noqa: F401
    _LANGCHAIN_OK = True
except ImportError:
    _LANGCHAIN_OK = False
    logger.warning("[LangGraph] langchain_core not installed — LLM nodes disabled")

# ── State (TypedDict via typing_extensions) ──────────────────────────────────
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # type: ignore


class JarvisState(TypedDict):
    user_input: str
    conversation_history: List[Dict[str, Any]]
    plan: Optional[Dict[str, Any]]
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    agent_outputs: Dict[str, Any]
    final_answer: str
    errors: List[str]
    requires_approval: bool
    memory_updates: List[Dict[str, Any]]
    retry_count: int
    mission_id: Optional[str]


MAX_RETRIES = 2

# ── LLM factory ──────────────────────────────────────────────────────────────

def _get_llm():
    """Instantiate LLM from available config (OpenAI or Ollama)."""
    try:
        from langchain_openai import ChatOpenAI
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "")
        if api_key and api_key not in ("sk-placeholder", "sk-CHANGE_ME", ""):
            kwargs: Dict[str, Any] = {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "api_key": api_key,
            }
            if base_url:
                kwargs["base_url"] = base_url
            return ChatOpenAI(**kwargs)
    except ImportError:
        _silent_log.debug("suppressed_exception", src='langgraph_flow.py')
    try:
        from langchain_community.llms import Ollama  # type: ignore
        ollama_url = os.getenv("OLLAMA_HOST", "http://ollama:11434")
        model = os.getenv("OLLAMA_MODEL_MAIN", "llama3.1:8b")
        return Ollama(base_url=ollama_url, model=model)
    except ImportError:
        _silent_log.debug("suppressed_exception", src='langgraph_flow.py')
    return None

# ── Nodes ─────────────────────────────────────────────────────────────────────

def memory_read_node(state: JarvisState) -> JarvisState:
    """Inject relevant memory context before planning."""
    try:
        from core.knowledge.knowledge_index import search_similar
        memories = search_similar(state["user_input"], top_k=3)
        if memories:
            extra = [{"role": "system", "content": f"[Memory] {m}"} for m in memories]
            state["conversation_history"] = list(state.get("conversation_history") or []) + extra
    except Exception as e:
        logger.debug("[LangGraph:memory_read] skip: %s", e)
    return state


def intent_router_node(state: JarvisState) -> JarvisState:
    """Route intent — maps to meta_orchestrator logic, fail-open."""
    try:
        from core.domain_router import classify_domain
        domain = classify_domain(state["user_input"])
        state.setdefault("plan", {})["domain"] = domain  # type: ignore[index]
    except Exception as e:
        logger.debug("[LangGraph:intent_router] skip: %s", e)
        if not state.get("plan"):
            state["plan"] = {}
        state["plan"]["domain"] = "general"  # type: ignore[index]
    return state


def planner_node(state: JarvisState) -> JarvisState:
    """Build execution plan using existing planner."""
    try:
        from core.planner import build_plan
        plan = build_plan(
            objective=state["user_input"],
            context={"conversation_history": state.get("conversation_history", [])},
        )
        state["plan"] = plan if isinstance(plan, dict) else {"steps": plan, "domain": "general"}
    except Exception as e:
        logger.warning("[LangGraph:planner] failed: %s", e)
        state["errors"] = list(state.get("errors") or []) + [f"planner: {e}"]
        state["plan"] = {"steps": [], "domain": "general", "fallback": True}
    return state


def approval_gate_node(state: JarvisState) -> JarvisState:
    """Check if mission requires human approval (supervised mode)."""
    try:
        from core.execution_policy import requires_approval
        state["requires_approval"] = requires_approval(state.get("plan") or {})
    except Exception as e:
        logger.debug("[LangGraph:approval_gate] skip: %s", e)
        state["requires_approval"] = False
    return state


async def executor_node(state: JarvisState) -> JarvisState:
    """Execute using MetaOrchestrator with AgentRunner fallback (fail-open)."""
    try:
        final_answer = ""
        agent_outputs = {}

        # Priority: MetaOrchestrator
        try:
            from core.meta_orchestrator import get_meta_orchestrator
            orchestrator = get_meta_orchestrator()
            result = await orchestrator.run(
                user_input=state["user_input"],
            )
            final_answer = result.get("final_output", "")
            agent_outputs = result.get("agent_outputs", {})
            if final_answer:
                logger.info("[LangGraph] executor_node: MetaOrchestrator OK")
        except ImportError:
            logger.debug("[LangGraph] MetaOrchestrator not available, using AgentRunner")
        except Exception as e:
            logger.warning(f"[LangGraph] MetaOrchestrator failed ({e}), falling back to AgentRunner")

        # Fallback: AgentRunner
        if not final_answer:
            try:
                from core.agent_runner import AgentRunner
                runner = AgentRunner()
                result = await runner.run(state["user_input"])
                final_answer = result.get("final_output", "")
                agent_outputs = result.get("agent_outputs", {})
                logger.info("[LangGraph] executor_node: AgentRunner fallback OK")
            except Exception as e:
                logger.error(f"[LangGraph] AgentRunner also failed: {e}")
                state["errors"] = list(state.get("errors") or []) + [f"executor_node: {e}"]

        state["final_answer"] = final_answer
        state["agent_outputs"] = agent_outputs

    except Exception as e:
        logger.error(f"[LangGraph] executor_node critical error: {e}")
        state["errors"] = list(state.get("errors") or []) + [str(e)]

    return state


def verifier_node(state: JarvisState) -> JarvisState:
    """Verify output quality — decides retry or proceed."""
    answer = state.get("final_answer", "")
    if not answer or answer.strip() == "":
        state["errors"] = list(state.get("errors") or []) + ["verifier: empty final_answer"]
        logger.warning("[LangGraph:verifier] empty answer — retry=%d", state.get("retry_count", 0))
    return state


def self_improvement_node(state: JarvisState) -> JarvisState:
    """Trigger self-improvement check (fail-open, fire-and-forget)."""
    try:
        from core.self_improvement import get_self_improvement_manager
        sim = get_self_improvement_manager()
        sim.analyze_patterns()
        logger.debug("[LangGraph:self_improvement] analyze_patterns triggered")
    except Exception as e:
        logger.debug("[LangGraph:self_improvement] skip: %s", e)
    return state


def memory_write_node(state: JarvisState) -> JarvisState:
    """Persist mission result to knowledge index."""
    try:
        from core.knowledge.knowledge_index import store_experience
        store_experience(
            task=state["user_input"],
            result=state.get("final_answer", ""),
            success=not bool(state.get("errors")),
            metadata={"tool_calls": len(state.get("tool_calls") or [])},
        )
    except Exception as e:
        logger.debug("[LangGraph:memory_write] skip: %s", e)
    return state


def fallback_node(state: JarvisState) -> JarvisState:
    """Last resort: build final_answer from pipeline_guard."""
    try:
        from api.pipeline_guard import build_safe_final_output
        state["final_answer"] = build_safe_final_output(
            raw_output=state.get("final_answer", ""),
            agent_outputs=state.get("tool_results") or [],
            mission_id=state.get("mission_id") or "",
        )
    except Exception as e:
        logger.error("[LangGraph:fallback] pipeline_guard failed: %s", e)
        if not state.get("final_answer"):
            state["final_answer"] = "Mission exécutée. Réponse temporairement indisponible."
    return state

# ── Routing ───────────────────────────────────────────────────────────────────

def route_after_approval(state: JarvisState) -> str:
    if state.get("requires_approval"):
        return "fallback"  # Suspend for approval (future: approval queue)
    return "executor"


def route_after_verifier(state: JarvisState) -> str:
    """Retry if output empty and retries available, else proceed."""
    has_answer = bool((state.get("final_answer") or "").strip())
    retry_count = state.get("retry_count", 0)
    if not has_answer and retry_count < MAX_RETRIES:
        state["retry_count"] = retry_count + 1
        return "planner"  # Back to planner with error context
    return "self_improvement"


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_jarvis_graph():
    """Build and compile the JarvisMax LangGraph execution graph."""
    if not _LANGGRAPH_OK:
        return None

    g = StateGraph(JarvisState)

    # Nodes
    g.add_node("memory_read", memory_read_node)
    g.add_node("intent_router", intent_router_node)
    g.add_node("planner", planner_node)
    g.add_node("approval_gate", approval_gate_node)
    g.add_node("executor", executor_node)
    g.add_node("verifier", verifier_node)
    g.add_node("self_improvement", self_improvement_node)
    g.add_node("memory_write", memory_write_node)
    g.add_node("fallback", fallback_node)

    # Edges
    g.set_entry_point("memory_read")
    g.add_edge("memory_read", "intent_router")
    g.add_edge("intent_router", "planner")
    g.add_edge("planner", "approval_gate")
    g.add_conditional_edges("approval_gate", route_after_approval, {
        "executor": "executor",
        "fallback": "fallback",
    })
    g.add_edge("executor", "verifier")
    g.add_conditional_edges("verifier", route_after_verifier, {
        "planner": "planner",
        "self_improvement": "self_improvement",
    })
    g.add_edge("self_improvement", "memory_write")
    g.add_edge("memory_write", "fallback")
    g.add_edge("fallback", END)

    return g.compile()


# Singleton — built once on import
try:
    jarvis_graph = build_jarvis_graph()
    if jarvis_graph:
        logger.info("[LangGraph] Graph compiled successfully — 9 nodes")
    else:
        jarvis_graph = None
except Exception as _e:
    jarvis_graph = None
    logger.error("[LangGraph] Graph compilation failed: %s", _e)


def invoke(user_input: str, mission_id: str = "", conversation_history=None) -> dict:
    """
    Main entrypoint. Falls back to legacy pipeline if LangGraph unavailable.
    Returns dict with final_answer, errors, tool_results, memory_updates.
    """
    if jarvis_graph is None:
        logger.warning("[LangGraph] graph unavailable — using legacy pipeline")
        return _legacy_fallback(user_input, mission_id)

    initial_state: JarvisState = {
        "user_input": user_input,
        "conversation_history": list(conversation_history or []),
        "plan": None,
        "tool_calls": [],
        "tool_results": [],
        "agent_outputs": {},
        "final_answer": "",
        "errors": [],
        "requires_approval": False,
        "memory_updates": [],
        "retry_count": 0,
        "mission_id": mission_id,
    }

    try:
        config: Dict[str, Any] = {}
        if os.getenv("LANGCHAIN_TRACING_V2") == "true":
            config["run_name"] = f"jarvis-{mission_id or 'anon'}"

        result = jarvis_graph.invoke(initial_state, config=config)
        return {
            "final_answer": result.get("final_answer", ""),
            "errors": result.get("errors", []),
            "tool_results": result.get("tool_results", []),
            "memory_updates": result.get("memory_updates", []),
            "plan": result.get("plan", {}),
            "requires_approval": result.get("requires_approval", False),
        }
    except Exception as e:
        logger.error("[LangGraph] invoke failed: %s", e)
        return _legacy_fallback(user_input, mission_id)


def _legacy_fallback(user_input: str, mission_id: str = "") -> dict:
    """Fallback to existing agent_runner pipeline."""
    try:
        from core.agent_runner import AgentRunner
        runner = AgentRunner()
        # AgentRunner.run(agent_name, goal, settings=None)
        result = runner.run(agent_name="evaluator", goal=user_input)
        answer = ""
        if isinstance(result, dict):
            answer = result.get("final_output") or result.get("output") or result.get("result") or ""
        else:
            answer = str(result) if result else ""
        if not answer:
            try:
                from api.pipeline_guard import build_safe_final_output
                answer = build_safe_final_output("", [], mission_id)
            except Exception:
                answer = "Mission exécutée. Réponse temporairement indisponible."
        return {"final_answer": answer, "errors": [], "tool_results": [], "memory_updates": []}
    except Exception as e:
        return {
            "final_answer": f"Erreur pipeline: {e}",
            "errors": [str(e)],
            "tool_results": [],
            "memory_updates": [],
        }
