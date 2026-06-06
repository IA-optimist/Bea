"""
Memory Graph — Auto-Linker
============================
Automatically creates graph nodes and edges from runtime events.
Called by observability hooks — never blocks execution.
"""
from __future__ import annotations

import structlog

from core.memory_graph.graph_schema import Edge, EdgeType, Node, NodeType

log = structlog.get_logger()


class GraphLinker:
    """Fail-open auto-linker that translates runtime events into graph relationships."""

    def __init__(self, graph):
        self._graph = graph

    # ── Mission lifecycle ──

    def link_mission(self, mission_id: str, label: str = "", **meta) -> str:
        """Create or update a mission node."""
        try:
            node = Node(id=f"m:{mission_id}", type=NodeType.MISSION, label=label, metadata=meta)
            self._graph.add_node(node)
            return node.id
        except Exception as e:
            log.debug("graph_link_failed", event="mission", err=str(e))
            return f"m:{mission_id}"

    def link_step(self, mission_id: str, step_id: str, agent_id: str = "", label: str = "", **meta) -> str:
        """Create step node and link it to mission and agent."""
        try:
            step_nid = f"s:{step_id}"
            mission_nid = f"m:{mission_id}"
            self._graph.add_node(Node(id=step_nid, type=NodeType.STEP, label=label, metadata=meta))
            if mission_nid in self._graph._nodes:
                self._graph.add_edge(Edge(source=mission_nid, target=step_nid, type=EdgeType.TRIGGERED))
            if agent_id:
                agent_nid = f"a:{agent_id}"
                self._ensure_node(agent_nid, NodeType.AGENT, agent_id)
                self._graph.add_edge(Edge(source=step_nid, target=agent_nid, type=EdgeType.EXECUTED_BY))
            return step_nid
        except Exception as e:
            log.debug("graph_link_failed", event="step", err=str(e))
            return f"s:{step_id}"

    def link_outcome(self, step_id: str, outcome_id: str, success: bool, label: str = "", **meta) -> str:
        """Create outcome node and link to step."""
        try:
            outcome_nid = f"o:{outcome_id}"
            step_nid = f"s:{step_id}"
            meta["success"] = success
            self._graph.add_node(Node(id=outcome_nid, type=NodeType.OUTCOME, label=label, metadata=meta))
            if step_nid in self._graph._nodes:
                self._graph.add_edge(Edge(source=step_nid, target=outcome_nid, type=EdgeType.PRODUCED))
            return outcome_nid
        except Exception as e:
            log.debug("graph_link_failed", event="outcome", err=str(e))
            return f"o:{outcome_id}"

    # ── Tool usage ──

    def link_tool_use(self, step_id: str, tool_name: str, success: bool = True, **meta) -> None:
        try:
            step_nid = f"s:{step_id}"
            tool_nid = f"t:{tool_name}"
            self._ensure_node(tool_nid, NodeType.TOOL, tool_name)
            if step_nid in self._graph._nodes:
                meta["success"] = success
                self._graph.add_edge(Edge(
                    source=step_nid, target=tool_nid, type=EdgeType.USED_TOOL,
                    weight=1.0 if success else 0.5, metadata=meta,
                ))
        except Exception as _exc:
            log.warning("swallowed_exception", action="link_mission_to_tools", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Patches / bugs ──

    def link_patch(self, patch_id: str, bug_id: str = "", module_path: str = "", **meta) -> str:
        try:
            patch_nid = f"p:{patch_id}"
            self._graph.add_node(Node(id=patch_nid, type=NodeType.PATCH, label=patch_id, metadata=meta))
            if bug_id:
                bug_nid = f"b:{bug_id}"
                self._ensure_node(bug_nid, NodeType.BUG, bug_id)
                self._graph.add_edge(Edge(source=bug_nid, target=patch_nid, type=EdgeType.FIXED_BY))
            if module_path:
                mod_nid = f"mod:{module_path}"
                self._ensure_node(mod_nid, NodeType.MODULE, module_path)
                self._graph.add_edge(Edge(source=patch_nid, target=mod_nid, type=EdgeType.IMPROVED))
            return patch_nid
        except Exception:
            return f"p:{patch_id}"

    # ── Dependencies ──

    def link_dependency(self, source_module: str, target_module: str, **meta) -> None:
        try:
            src = f"mod:{source_module}"
            tgt = f"mod:{target_module}"
            self._ensure_node(src, NodeType.MODULE, source_module)
            self._ensure_node(tgt, NodeType.MODULE, target_module)
            self._graph.add_edge(Edge(source=src, target=tgt, type=EdgeType.DEPENDS_ON, metadata=meta))
        except Exception as _exc:
            log.warning("swallowed_exception", action="link_module_dep_graph", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    def link_secret_requirement(self, connector_id: str, secret_key: str) -> None:
        try:
            conn_nid = f"conn:{connector_id}"
            sec_nid = f"sec:{secret_key}"
            self._ensure_node(conn_nid, NodeType.CONNECTOR, connector_id)
            self._ensure_node(sec_nid, NodeType.SECRET, secret_key)
            self._graph.add_edge(Edge(source=conn_nid, target=sec_nid, type=EdgeType.REQUIRES_SECRET))
        except Exception as _exc:
            log.warning("swallowed_exception", action="link_connector_requires_secret", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Lessons ──

    def link_lesson(self, lesson_id: str, mission_id: str = "", label: str = "", **meta) -> None:
        try:
            lesson_nid = f"l:{lesson_id}"
            self._graph.add_node(Node(id=lesson_nid, type=NodeType.LESSON, label=label, metadata=meta))
            if mission_id:
                mission_nid = f"m:{mission_id}"
                if mission_nid in self._graph._nodes:
                    self._graph.add_edge(Edge(source=lesson_nid, target=mission_nid, type=EdgeType.LEARNED_FROM))
        except Exception as _exc:
            log.warning("swallowed_exception", action="link_lesson_to_mission", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Intent ──

    def link_intent(self, request_id: str, request_text: str, intent: str, workflow_id: str = "") -> None:
        try:
            req_nid = f"req:{request_id}"
            int_nid = f"int:{intent}"
            self._graph.add_node(Node(id=req_nid, type=NodeType.USER_REQUEST, label=request_text[:100]))
            self._ensure_node(int_nid, NodeType.INTENT, intent)
            self._graph.add_edge(Edge(source=req_nid, target=int_nid, type=EdgeType.INFERRED_AS))
            if workflow_id:
                wf_nid = f"wf:{workflow_id}"
                self._ensure_node(wf_nid, NodeType.WORKFLOW, workflow_id)
                self._graph.add_edge(Edge(source=int_nid, target=wf_nid, type=EdgeType.RESOLVED_VIA))
        except Exception as _exc:
            log.warning("swallowed_exception", action="link_intent_to_workflow", exc_type=type(_exc).__name__, exc_msg=str(_exc)[:200])

    # ── Helpers ──

    def _ensure_node(self, nid: str, ntype: NodeType, label: str) -> None:
        if nid not in self._graph._nodes:
            self._graph.add_node(Node(id=nid, type=ntype, label=label))
