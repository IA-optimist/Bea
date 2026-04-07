"""
JARVIS MAX — OrchestratorV2 — BUDGET/DAG DELEGATE
===================================================
STATUS: ACTIVE INTERNAL DELEGATE — used by MetaOrchestrator for budget-constrained missions.

DO NOT INSTANTIATE DIRECTLY. Use:
    from core import get_meta_orchestrator
    orch = get_meta_orchestrator()
    await orch.run(user_input="...", use_budget=True)

MetaOrchestrator.v2 lazy-loads this class automatically when use_budget=True.

RESPONSIBILITY: Adds three capabilities ON TOP of JarvisOrchestrator:
  1. BudgetGuard  — max_tokens / max_time_s / max_cost_usd enforcement
  2. TaskDAG      — topological-sort parallel execution layers
  3. CheckpointStore — resume interrupted DAGs (asyncpg + SQLite fallback)

HEADER NOTE: previous "DEPRECATED" comment was incorrect.
This module IS used (not deprecated) for DAG/budget missions.
It IS an internal delegate (not for direct external use).
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)


# ══════════════════════════════════════════════════════════════
# 1. Budget
# ══════════════════════════════════════════════════════════════

# Cost per 1K tokens (approximate)
_COST_PER_1K: dict[str, float] = {
    "gpt-4o":              0.005,
    "gpt-4o-mini":         0.000150,
    "gpt-4-turbo":         0.010,
    "claude-opus-4-6":     0.015,
    "claude-sonnet-4-6":   0.003,
    "claude-haiku-4-5-20251001": 0.00025,
    "default":             0.001,
}


@dataclass
class BudgetConfig:
    max_tokens:   int   = 50_000
    max_time_s:   float = 300.0
    max_cost_usd: float = 1.00


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    """Tracks token usage, elapsed time and estimated cost. Thread-safe."""

    def __init__(self, config: BudgetConfig):
        self.cfg        = config
        self._tokens    = 0
        self._cost_usd  = 0.0
        self._start     = time.monotonic()
        self._warned    = False
        self._lock      = threading.Lock()

    # ── Public ──────────────────────────────────────────────

    def charge(self, text: str, model: str = "default") -> int:
        """Count tokens in text, accumulate cost, raise BudgetExceeded if over limit."""
        n = _count_tokens(text)
        with self._lock:
            self._tokens   += n
            rate            = _COST_PER_1K.get(model, _COST_PER_1K["default"])
            self._cost_usd += n / 1000 * rate
        self.check()
        return n

    def check(self) -> None:
        """Raise BudgetExceeded if any limit is hit."""
        elapsed = time.monotonic() - self._start
        with self._lock:
            tokens    = self._tokens
            cost_usd  = self._cost_usd

        if tokens > self.cfg.max_tokens:
            raise BudgetExceeded(
                f"Token budget exceeded: {tokens} > {self.cfg.max_tokens}"
            )
        if elapsed > self.cfg.max_time_s:
            raise BudgetExceeded(
                f"Time budget exceeded: {elapsed:.1f}s > {self.cfg.max_time_s}s"
            )
        if cost_usd > self.cfg.max_cost_usd:
            raise BudgetExceeded(
                f"Cost budget exceeded: ${cost_usd:.4f} > ${self.cfg.max_cost_usd}"
            )

    @property
    def tokens(self) -> int:
        with self._lock:
            return self._tokens

    @property
    def elapsed_s(self) -> float:
        return time.monotonic() - self._start

    @property
    def cost_usd(self) -> float:
        return self._cost_usd

    def snapshot(self) -> dict:
        return {
            "tokens":    self._tokens,
            "elapsed_s": round(self.elapsed_s, 2),
            "cost_usd":  round(self._cost_usd, 6),
        }


def _count_tokens(text: str) -> int:
    """Count BPE tokens using tiktoken; fallback to len//4."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        return max(1, len(text) // 4)


# ══════════════════════════════════════════════════════════════
# 2. TaskDAG
# ══════════════════════════════════════════════════════════════

def build_dag_layers(tasks: list[dict]) -> list[list[dict]]:
    """
    Build parallel execution layers from a task list.

    Each task dict may have:
        "deps": list[str]   — names of tasks that must complete first
        "priority": int     — lower = earlier (used when no deps)

    Returns list of layers; each layer's tasks can run concurrently.
    """
    if not tasks:
        return []

    has_deps = any(t.get("deps") for t in tasks)
    if has_deps:
        return _kahn_layers(tasks)
    return _priority_layers(tasks)


def _priority_layers(tasks: list[dict]) -> list[list[dict]]:
    """Group tasks by priority into sequential layers."""
    by_prio: dict[int, list[dict]] = {}
    for t in tasks:
        p = int(t.get("priority", 2))
        by_prio.setdefault(p, []).append(t)
    return [by_prio[k] for k in sorted(by_prio)]


def _kahn_layers(tasks: list[dict]) -> list[list[dict]]:
    """Kahn's BFS topological sort → parallel layers."""
    name_map  = {t.get("agent", t.get("name", str(i))): t
                 for i, t in enumerate(tasks)}
    in_degree: dict[str, int] = {n: 0 for n in name_map}
    graph:     dict[str, list[str]] = {n: [] for n in name_map}

    cyclic: list[dict] = []
    for name, task in name_map.items():
        for dep in (task.get("deps") or []):
            if dep not in name_map:
                continue
            graph[dep].append(name)
            in_degree[name] += 1

    queue  = deque(n for n, d in in_degree.items() if d == 0)
    layers: list[list[dict]] = []
    visited: set[str] = set()

    while queue:
        layer_names = list(queue)
        queue.clear()
        layer = [name_map[n] for n in layer_names]
        layers.append(layer)
        for n in layer_names:
            visited.add(n)
            for child in graph[n]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

    # Handle cycles: append remaining via priority
    remaining = [name_map[n] for n in name_map if n not in visited]
    if remaining:
        log.warning("dag_cycles_detected", count=len(remaining))
        cyclic_layers = _priority_layers(remaining)
        layers.extend(cyclic_layers)

    return layers


# ══════════════════════════════════════════════════════════════
# 3. CheckpointStore
# ══════════════════════════════════════════════════════════════

_CREATE_CP = """
CREATE TABLE IF NOT EXISTS orchestrator_checkpoints (
    id          TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    layer_idx   INTEGER NOT NULL,
    state_json  TEXT NOT NULL,
    done        BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
"""


class CheckpointStore:
    """Checkpoint DAG progress. asyncpg primary, SQLite fallback."""

    def __init__(self, settings):
        self.s     = settings
        self._pool = None
        self._sqlite_path: str | None = None
        self._backend: str | None = None   # "pg" | "sqlite" | None

    async def ensure_table(self) -> None:
        if await self._try_pg():
            return
        await self._ensure_sqlite()

    async def save(self, session_id: str, layer_idx: int, state: dict) -> None:
        cp_id = f"{session_id}:{layer_idx}"
        data  = json.dumps(state)
        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO orchestrator_checkpoints
                            (id, session_id, layer_idx, state_json, updated_at)
                        VALUES ($1,$2,$3,$4,NOW())
                        ON CONFLICT (id) DO UPDATE
                            SET state_json=EXCLUDED.state_json, updated_at=NOW();
                        """,
                        cp_id, session_id, layer_idx, data,
                    )
                return
            except Exception as e:
                log.warning("checkpoint_pg_save_failed", err=str(e)[:80])

        if self._backend == "sqlite":
            await self._sqlite_upsert(cp_id, session_id, layer_idx, data)

    async def load(self, session_id: str, layer_idx: int) -> dict | None:
        cp_id = f"{session_id}:{layer_idx}"
        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT state_json FROM orchestrator_checkpoints WHERE id=$1;",
                        cp_id,
                    )
                if row:
                    return json.loads(row["state_json"])
            except Exception as e:
                log.warning("checkpoint_pg_load_failed", err=str(e)[:80])

        if self._backend == "sqlite":
            return await self._sqlite_load(cp_id)
        return None

    async def mark_done(self, session_id: str) -> None:
        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE orchestrator_checkpoints SET done=TRUE WHERE session_id=$1;",
                        session_id,
                    )
                return
            except Exception:
                pass
        if self._backend == "sqlite":
            await self._sqlite_mark_done(session_id)

    async def list_incomplete(self) -> list[dict]:
        if self._backend == "pg":
            try:
                pool = await self._get_pg_pool()
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT id,session_id,layer_idx FROM orchestrator_checkpoints "
                        "WHERE done=FALSE ORDER BY created_at;"
                    )
                return [dict(r) for r in rows]
            except Exception:
                pass
        if self._backend == "sqlite":
            return await self._sqlite_list_incomplete()
        return []

    # ── asyncpg helpers ───────────────────────────────────────

    async def _try_pg(self) -> bool:
        try:
            pool = await self._get_pg_pool()
            if pool is None:
                return False
            async with pool.acquire() as conn:
                await conn.execute(_CREATE_CP)
            self._backend = "pg"
            log.debug("checkpoint_backend_pg")
            return True
        except Exception as e:
            log.debug("checkpoint_pg_unavailable", err=str(e)[:80])
            return False

    async def _get_pg_pool(self):
        if self._pool is not None:
            return self._pool
        try:
            import asyncpg
            dsn = getattr(self.s, "database_url", None) or getattr(self.s, "pg_dsn", None)
            if not dsn:
                return None
            self._pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
            return self._pool
        except Exception:
            return None

    # ── SQLite helpers ────────────────────────────────────────

    async def _ensure_sqlite(self) -> None:
        try:
            from core.db import get_sqlite_path
            self._sqlite_path = get_sqlite_path()
        except Exception:
            import os, tempfile
            self._sqlite_path = os.path.join(tempfile.gettempdir(), "jarvis_checkpoints.db")

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sqlite_create_table)
        self._backend = "sqlite"
        log.debug("checkpoint_backend_sqlite", path=self._sqlite_path)

    def _sqlite_create_table(self) -> None:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        con.execute("""
            CREATE TABLE IF NOT EXISTS orchestrator_checkpoints (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                layer_idx INTEGER,
                state_json TEXT,
                done INTEGER DEFAULT 0
            );
        """)
        con.commit()
        con.close()

    async def _sqlite_upsert(self, cp_id, session_id, layer_idx, data) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            self._sqlite_upsert_sync,
            cp_id, session_id, layer_idx, data,
        )

    def _sqlite_upsert_sync(self, cp_id, session_id, layer_idx, data) -> None:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        con.execute(
            "INSERT OR REPLACE INTO orchestrator_checkpoints"
            "(id,session_id,layer_idx,state_json) VALUES(?,?,?,?);",
            (cp_id, session_id, layer_idx, data),
        )
        con.commit()
        con.close()

    async def _sqlite_load(self, cp_id: str) -> dict | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sqlite_load_sync, cp_id)

    def _sqlite_load_sync(self, cp_id: str) -> dict | None:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        cur = con.execute(
            "SELECT state_json FROM orchestrator_checkpoints WHERE id=?;", (cp_id,)
        )
        row = cur.fetchone()
        con.close()
        return json.loads(row[0]) if row else None

    async def _sqlite_mark_done(self, session_id: str) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._sqlite_mark_done_sync, session_id)

    def _sqlite_mark_done_sync(self, session_id: str) -> None:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        con.execute(
            "UPDATE orchestrator_checkpoints SET done=1 WHERE session_id=?;",
            (session_id,),
        )
        con.commit()
        con.close()

    async def _sqlite_list_incomplete(self) -> list[dict]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sqlite_list_incomplete_sync)

    def _sqlite_list_incomplete_sync(self) -> list[dict]:
        import sqlite3
        con = sqlite3.connect(self._sqlite_path)
        cur = con.execute(
            "SELECT id,session_id,layer_idx FROM orchestrator_checkpoints WHERE done=0;"
        )
        rows = [{"id": r[0], "session_id": r[1], "layer_idx": r[2]} for r in cur.fetchall()]
        con.close()
        return rows


# ══════════════════════════════════════════════════════════════
# 4. OrchestratorV2
# ══════════════════════════════════════════════════════════════

# Fallback agent mapping: if agent X fails, try agent Y
_FALLBACK_AGENTS: dict[str, str] = {
    "coder-agent":    "debug-agent",
    "planner-agent":  "orchestrator-agent",
    "search-agent":   "researcher-agent",
    "writer-agent":   "summarizer-agent",
}

# Agents whose output should be injected as context for other agents
_CONTEXT_PROVIDERS = frozenset({
    "security-agent", "planner-agent", "researcher-agent", "auditor-agent"
})


class OrchestratorV2:
    """
    Thin wrapper adding BudgetGuard + TaskDAG + CheckpointStore
    around JarvisOrchestrator, plus multi-agent context sharing.

    Falls back gracefully if JarvisOrchestrator is unavailable.
    """

    def __init__(self, settings):
        self.s            = settings
        self._checkpoints = CheckpointStore(settings)
        self._inner       = None   # lazy JarvisOrchestrator
        self._comm        = None   # lazy AgentComm

    def _get_comm(self):
        if self._comm is None:
            from core.agent_comm import get_agent_comm
            self._comm = get_agent_comm()
        return self._comm

    def _get_inner(self):
        if self._inner is None:
            from core.orchestrator import JarvisOrchestrator
            self._inner = JarvisOrchestrator(self.s)
        return self._inner

    async def run(
        self,
        user_input: str,
        mode:       str         = "auto",
        session_id: str | None  = None,
        budget:     BudgetConfig | None = None,
        **kwargs,
    ):
        """
        Run a mission with optional budget enforcement.
        Delegates to JarvisOrchestrator.run(); wraps with BudgetGuard.
        """
        cfg   = budget or BudgetConfig()
        guard = BudgetGuard(cfg)
        sid   = session_id or str(uuid.uuid4())

        # charge the input tokens
        try:
            guard.charge(user_input)
        except BudgetExceeded as e:
            log.warning("budget_exceeded_on_input", err=str(e))
            raise

        await self._checkpoints.ensure_table()

        try:
            inner   = self._get_inner()
            session = await inner.run(
                user_input=user_input,
                mode=mode,
                session_id=sid,
                **kwargs,
            )
            # charge output tokens
            try:
                report = getattr(session, "final_report", "") or ""
                guard.charge(report)
            except BudgetExceeded as e:
                log.warning("budget_exceeded_post_run", err=str(e))
                # report the overage but still return session
                setattr(session, "_budget_warning", str(e))

            await self._checkpoints.mark_done(sid)
            log.info(
                "orchestrator_v2_done",
                session_id=sid,
                **guard.snapshot(),
            )
            return session

        except BudgetExceeded:
            raise
        except Exception as e:
            log.error("orchestrator_v2_failed", err=str(e)[:200])
            raise

    async def run_dag(
        self,
        tasks:      list[dict],
        mode:       str         = "auto",
        session_id: str | None  = None,
        budget:     BudgetConfig | None = None,
    ) -> list[Any]:
        """
        Execute a list of tasks respecting dependency order.
        Returns list of results in task order.
        """
        cfg   = budget or BudgetConfig()
        guard = BudgetGuard(cfg)
        sid   = session_id or str(uuid.uuid4())

        await self._checkpoints.ensure_table()

        layers  = build_dag_layers(tasks)
        results = {}   # task-name → result

        for layer_idx, layer in enumerate(layers):
            guard.check()

            # Check if layer already checkpointed
            cp = await self._checkpoints.load(sid, layer_idx)
            if cp:
                log.debug("dag_layer_resumed", session_id=sid, layer=layer_idx)
                results.update(cp.get("results", {}))
                continue

            layer_results = await asyncio.gather(
                *[self._run_single_task(t, sid, mode, guard) for t in layer],
                return_exceptions=True,
            )

            layer_map = {}
            for task, result in zip(layer, layer_results):
                name = task.get("agent", task.get("name", "unknown"))
                layer_map[name] = (
                    str(result) if isinstance(result, Exception) else result
                )
            results.update(layer_map)

            await self._checkpoints.save(sid, layer_idx, {"results": results})

        await self._checkpoints.mark_done(sid)
        return [results.get(t.get("agent", t.get("name", ""))) for t in tasks]

    async def _run_single_task(
        self, task: dict, session_id: str, mode: str, guard: BudgetGuard
    ):
        agent_name = task.get("agent", task.get("name", "unknown-agent"))
        mission    = task.get("task", task.get("mission", str(task)))

        # ── Cross-agent context injection ─────────────────────
        comm = self._get_comm()
        ctx_block = comm.format_session_context(session_id)
        if ctx_block:
            mission = f"{ctx_block}\n\n---\nTask: {mission}"

        # ── Specific context from security/planner agents ──────
        for provider in _CONTEXT_PROVIDERS:
            prior = comm.get_agent_output(session_id, provider, output_type="result")
            if prior and provider != agent_name:
                snippet = str(prior.payload)[:300]
                mission = f"[{provider} output]: {snippet}\n\n{mission}"

        try:
            guard.charge(mission)
            inner    = self._get_inner()
            task_sid = f"{session_id}-{uuid.uuid4().hex[:8]}"
            session  = await inner.run(user_input=mission, mode=mode, session_id=task_sid)
            report   = getattr(session, "final_report", "") or ""
            guard.charge(report)

            # ── Self-critic evaluation ─────────────────────────
            original_task = task.get("task", task.get("mission", str(task)))
            report = await self._critic_pass(
                session_id, agent_name, original_task, report, mode, guard
            )

            # Publish result to AgentComm for cross-agent access
            await comm.publish(session_id, agent_name, "result", report[:1000])
            return report

        except BudgetExceeded:
            raise

        except Exception as primary_err:
            log.warning("dag_task_failed", agent=agent_name,
                        task=str(task)[:80], err=str(primary_err)[:80])

            # ── Dynamic re-planning: try fallback agent ────────
            fallback = task.get("fallback_agent") or _FALLBACK_AGENTS.get(agent_name)
            if fallback:
                log.info("dag_task_rerouting", from_agent=agent_name, to_agent=fallback)
                fallback_task = dict(task)
                fallback_task["agent"] = fallback
                fallback_task.pop("fallback_agent", None)
                try:
                    return await self._run_single_task(
                        fallback_task, session_id, mode, guard
                    )
                except Exception as fb_err:
                    log.warning("dag_fallback_also_failed",
                                fallback=fallback, err=str(fb_err)[:80])
                    await comm.publish(session_id, agent_name, "error", str(fb_err)[:200])
                    raise fb_err

            await comm.publish(session_id, agent_name, "error", str(primary_err)[:200])
            raise

    async def _critic_pass(
        self,
        session_id:  str,
        agent_name:  str,
        task:        str,
        report:      str,
        mode:        str,
        guard:       BudgetGuard,
    ) -> str:
        """
        Run self-critic evaluation and trigger up to MAX_RERUNS reruns
        if quality is insufficient. Returns the best report.
        """
        try:
            from core.self_critic import get_critic
            from core.improvement_memory import get_improvement_memory
        except ImportError:
            return report   # modules not available yet

        critic = get_critic(self.s)
        cr     = await critic.evaluate(session_id, agent_name, task, report)

        if not critic.should_rerun(cr):
            return report

        # ── Emit WS thinking event ─────────────────────────────
        try:
            from api.ws_hub import get_hub
            await get_hub().emit_agent_thinking(
                session_id, agent_name,
                f"Self-critic: score {cr.overall:.1f}/10 — triggering rerun "
                f"({cr.rerun_count + 1}/{2}). Feedback: {cr.feedback[:100]}"
            )
        except Exception:
            pass

        # ── Rerun with injected feedback ───────────────────────
        augmented = critic.build_rerun_prompt(task, report, cr.feedback, cr.suggestions)
        try:
            guard.charge(augmented)
            critic.increment_rerun(cr.task_hash)
            inner       = self._get_inner()
            rerun_sid   = f"{session_id}-rerun-{uuid.uuid4().hex[:6]}"
            rerun_sess  = await inner.run(
                user_input=augmented, mode=mode, session_id=rerun_sid
            )
            new_report  = getattr(rerun_sess, "final_report", "") or report
            guard.charge(new_report)

            # Evaluate rerun and record improvement
            new_cr = await critic.evaluate(session_id, agent_name, task, new_report)
            try:
                mem = get_improvement_memory(self.s)
                await mem.record_improvement(
                    agent_name   = agent_name,
                    task         = task,
                    score_before = cr.overall,
                    score_after  = new_cr.overall,
                    feedback     = cr.feedback,
                )
            except Exception as mem_err:
                log.warning("improvement_record_failed", err=str(mem_err)[:80])

            log.info(
                "critic_rerun_complete",
                agent=agent_name,
                before=cr.overall,
                after=new_cr.overall,
                delta=round(new_cr.overall - cr.overall, 2),
            )
            return new_report

        except BudgetExceeded:
            log.warning("critic_rerun_budget_exceeded", agent=agent_name)
            return report
        except Exception as rerun_err:
            log.warning("critic_rerun_failed", agent=agent_name, err=str(rerun_err)[:80])
            return report
