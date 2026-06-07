"""llm_tracer — traçage léger des appels LLM (coût, latence, erreurs, qualité).

Inspiration Langfuse/LangSmith, **sans dépendance** (SQLite stdlib). Indispensable
pour un agent autonome : savoir ce qu'il dépense, ce qui rate, et où. Un backend
Langfuse/OTel pourra s'y brancher plus tard ; le cœur reste local et autonome.

Usage :
    tr = LLMTracer("data/llm_traces.db")
    with tr.span(model="bea-v3.1", mission_id="m1") as s:
        ... appel LLM ...
        s.set(prompt_tokens=120, completion_tokens=80, cost_usd=0.0012)
    tr.stats()  # {calls, cost_usd, error_rate, by_model}
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


class _Span:
    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost_usd = 0.0

    def set(self, prompt_tokens: int = 0, completion_tokens: int = 0,
            cost_usd: float = 0.0) -> None:
        self.prompt_tokens = int(prompt_tokens)
        self.completion_tokens = int(completion_tokens)
        self.cost_usd = float(cost_usd)


class LLMTracer:
    def __init__(self, db_path: str = ":memory:") -> None:
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS llm_calls ("
            "ts REAL, model TEXT, mission_id TEXT, prompt_tokens INTEGER, "
            "completion_tokens INTEGER, cost_usd REAL, latency_ms REAL, "
            "ok INTEGER, error TEXT)"
        )
        self._conn.commit()

    def record(self, model: str, prompt_tokens: int = 0, completion_tokens: int = 0,
               cost_usd: float = 0.0, latency_ms: float = 0.0, ok: bool = True,
               error: str = "", mission_id: str = "") -> None:
        self._conn.execute(
            "INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), model, mission_id, int(prompt_tokens), int(completion_tokens),
             float(cost_usd), float(latency_ms), 1 if ok else 0, error[:300]),
        )
        self._conn.commit()

    @contextmanager
    def span(self, model: str, mission_id: str = ""):
        """Mesure la latence et enregistre l'appel (succès ou exception)."""
        span = _Span()
        t0 = time.time()
        try:
            yield span
        except Exception as e:
            self.record(model, span.prompt_tokens, span.completion_tokens,
                        span.cost_usd, (time.time() - t0) * 1000, ok=False,
                        error=str(e), mission_id=mission_id)
            raise
        else:
            self.record(model, span.prompt_tokens, span.completion_tokens,
                        span.cost_usd, (time.time() - t0) * 1000, ok=True,
                        mission_id=mission_id)

    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
            "COALESCE(SUM(prompt_tokens+completion_tokens),0) toks, "
            "COALESCE(SUM(CASE WHEN ok=0 THEN 1 ELSE 0 END),0) errs FROM llm_calls"
        ).fetchone()
        n = row["n"] or 0
        by_model = {
            r["model"]: {"calls": r["c"], "cost_usd": round(r["cost"], 6)}
            for r in self._conn.execute(
                "SELECT model, COUNT(*) c, COALESCE(SUM(cost_usd),0) cost "
                "FROM llm_calls GROUP BY model"
            ).fetchall()
        }
        return {
            "calls": n,
            "cost_usd": round(row["cost"], 6),
            "total_tokens": row["toks"],
            "error_rate": round((row["errs"] / n), 4) if n else 0.0,
            "by_model": by_model,
        }

    def cost_by_mission(self, mission_id: str) -> float:
        r = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) c FROM llm_calls WHERE mission_id=?",
            (mission_id,),
        ).fetchone()
        return round(r["c"], 6)

    def close(self) -> None:
        self._conn.close()


_TRACER: "LLMTracer | None" = None


def get_tracer() -> "LLMTracer":
    """Tracer singleton du process (DB via env BEA_LLM_TRACE_DB, défaut :memory:)."""
    global _TRACER
    if _TRACER is None:
        import os
        _TRACER = LLMTracer(os.getenv("BEA_LLM_TRACE_DB", ":memory:"))
    return _TRACER
