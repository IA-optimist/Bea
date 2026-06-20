"""Mission response assembly helpers for mission routes."""
from __future__ import annotations

import json
import logging
from typing import Any

from api.mission_outputs import extract_agent_outputs


def build_mission_response_data(mission_id: str, mission_record: Any) -> dict:
    """Build the API payload for GET /api/v2/missions/{mission_id}."""
    data = mission_record.to_dict()
    data["agent_outputs"] = extract_agent_outputs(mission_id)
    data["execution_trace"] = data.pop("execution_trace", [])

    try:
        raw_fo = data.get("final_output", "")
        parsed_envelope = None
        if raw_fo and raw_fo.strip().startswith("{"):
            try:
                parsed_envelope = json.loads(raw_fo)
                if "agent_outputs" in parsed_envelope and "status" in parsed_envelope:
                    data["result_envelope"] = parsed_envelope
                    parts = []
                    for agent_output in parsed_envelope.get("agent_outputs", []):
                        if agent_output.get("output_text"):
                            agent_name = agent_output.get("agent_name", "agent")
                            output_text = agent_output["output_text"][:1500]
                            parts.append(f"## {agent_name}\n{output_text}")
                    if parts:
                        data["final_output"] = (
                            f"# Résultats ({len(parts)} agents)\n\n"
                            + "\n\n---\n\n".join(parts)
                        )
                    else:
                        data["final_output"] = parsed_envelope.get("summary", raw_fo)
                else:
                    parsed_envelope = None
            except (json.JSONDecodeError, Exception):
                parsed_envelope = None

        if not parsed_envelope:
            try:
                from core.result_aggregator import aggregate_mission_result

                envelope = aggregate_mission_result(
                    mission_id=str(mission_id),
                    mission_status=str(getattr(mission_record, "status", "DONE")),
                    start_time=getattr(mission_record, "created_at", 0.0),
                    summary=data.get("plan_summary", "")[:500],
                )
                data["result_envelope"] = envelope.to_dict()
            except Exception:
                data["result_envelope"] = None

            try:
                from api.pipeline_guard import build_safe_final_output

                agent_outputs = data.get("agent_outputs") or {}
                if isinstance(agent_outputs, dict):
                    agent_outputs_list = [
                        {"agent_name": name, "result": result}
                        for name, result in agent_outputs.items()
                    ]
                else:
                    agent_outputs_list = list(agent_outputs)
                data["final_output"] = build_safe_final_output(
                    raw_output=raw_fo or (data.get("plan_summary") or "")[:2000],
                    agent_outputs=agent_outputs_list,
                    mission_id=str(mission_id or ""),
                )
            except Exception:
                if not data.get("final_output"):
                    data["final_output"] = "Mission exécutée. Réponse temporairement indisponible."
    except Exception as exc:
        logging.getLogger(__name__).error("[RESULT ENVELOPE] failed: %s", exc)
        data.setdefault("result_envelope", None)
        if not data.get("final_output"):
            data["final_output"] = "Mission exécutée. Réponse temporairement indisponible."

    data.setdefault("summary", data.get("plan_summary", "")[:500])
    data.setdefault("agents_selected", [])
    data.setdefault("domain", "general")
    data.setdefault("complexity", getattr(mission_record, "complexity", "medium"))

    decision_trace = getattr(mission_record, "decision_trace", {}) or {}
    data["decision_trace"] = decision_trace
    if "result_envelope" not in data or not data.get("result_envelope"):
        data["result_envelope"] = decision_trace.get("result_envelope")
    data["confidence_score"] = decision_trace.get("confidence_score", 0.0)
    data["skipped_agents"] = decision_trace.get("skipped_agents", [])
    data["final_output_source"] = decision_trace.get("final_output_source", "unknown")
    data["fallback_level_used"] = decision_trace.get("fallback_level_used", 0)
    data["approval_reason"] = decision_trace.get("approval_reason", "")
    data["approval_decision"] = decision_trace.get("approval_decision", "")
    data["risk_score"] = getattr(mission_record, "risk_score", 0)
    return data
