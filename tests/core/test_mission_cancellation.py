"""Mission cancellation contract tests."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import BackgroundTasks

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api.event_emitter as event_emitter
import api.routes.missions as missions
from api.schemas_missions import AbortRequest, TaskRequest
from core.task_queue import CoreTaskQueue, TaskState


class _Mission:
    def __init__(self, mission_id: str) -> None:
        self.mission_id = mission_id
        self.status = "PENDING"
        self.created_at = time.time()
        self.decision_trace: dict[str, object] = {}
        self.submitted_by = None
        self.result = ""
        self.output = ""
        self.error = ""

    def to_dict(self) -> dict:
        return {
            "mission_id": self.mission_id,
            "status": self.status,
            "created_at": self.created_at,
        }


class _MissionSystem:
    def __init__(self, mission_id: str) -> None:
        self.mission = _Mission(mission_id)
        self.complete_called = False
        self.cancel_called = False
        self.reject_called = False

    def submit(self, *_args, **_kwargs):
        return self.mission

    def get(self, _mission_id: str):
        return self.mission

    def set_final_output(self, _mission_id: str, value: str):
        self.mission.output = value
        self.mission.result = value

    def complete(self, _mission_id: str, result_text: str = ""):
        self.complete_called = True
        self.mission.status = "DONE"
        self.mission.result = result_text
        self.mission.output = result_text
        return self.mission

    def cancel(self, _mission_id: str, reason: str = ""):
        self.cancel_called = True
        self.mission.status = "CANCELLED"
        self.mission.decision_trace["cancelled"] = True
        self.mission.decision_trace["cancel_reason"] = reason
        self.mission.error = reason
        return self.mission

    def reject(self, _mission_id: str, note: str = ""):
        self.reject_called = True
        self.mission.status = "REJECTED"
        self.mission.error = note
        return self.mission


class _SlowOrchestrator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def run(self, **_kwargs):
        self.started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class _ControlledOrchestrator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, **_kwargs):
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(
            status=SimpleNamespace(value="DONE"),
            output="ok",
            error="",
            metadata={},
            source="fallback",
        )


def _patch_routes(ms, orch, queue):
    originals = {
        "_check_auth": missions._check_auth,
        "_get_mission_system": missions._get_mission_system,
        "_get_orchestrator": missions._get_orchestrator,
        "_get_kernel_adapter": missions._get_kernel_adapter,
        "_get_task_queue": missions._get_task_queue,
        "get_authenticated_principal": missions.get_authenticated_principal,
        "emit_mission_created": event_emitter.emit_mission_created,
    }
    missions._check_auth = lambda *_args, **_kwargs: None
    missions._get_mission_system = lambda: ms
    missions._get_orchestrator = lambda: orch
    missions._get_kernel_adapter = lambda: None
    missions._get_task_queue = lambda: queue
    missions.get_authenticated_principal = lambda _request: "test:principal"
    event_emitter.emit_mission_created = lambda *_args, **_kwargs: None
    return originals


def _restore_routes(originals):
    missions._check_auth = originals["_check_auth"]
    missions._get_mission_system = originals["_get_mission_system"]
    missions._get_orchestrator = originals["_get_orchestrator"]
    missions._get_kernel_adapter = originals["_get_kernel_adapter"]
    missions._get_task_queue = originals["_get_task_queue"]
    missions.get_authenticated_principal = originals["get_authenticated_principal"]
    event_emitter.emit_mission_created = originals["emit_mission_created"]
    missions._running_missions.clear()
    missions._active_mission_tasks.clear()


def _print_case(name: str, **values) -> None:
    rendered = ", ".join(f"{k}={v}" for k, v in values.items())
    print(f"{name}: {rendered}")


async def case_core_task_queue_cancel_mission_matches_mission_id() -> None:
    queue = CoreTaskQueue()
    task = await queue.enqueue("work", mission_id="mission-1", task_id="task-1")
    assert await queue.cancel_mission("mission-1") is True
    stored = await queue.get(task.id)
    assert stored is not None
    assert stored.state == TaskState.CANCELLED, stored.state
    _print_case("core_task_queue", cancelled=stored.state.value, task_id=stored.id, mission_id=stored.mission_id)


async def case_api_abort_cancels_active_task_before_sleep_finishes() -> None:
    ms = _MissionSystem("mission-cancel")
    orch = _SlowOrchestrator()
    queue = CoreTaskQueue()
    await queue.enqueue("work", mission_id="mission-cancel", task_id="bg-task-1")
    originals = _patch_routes(ms, orch, queue)
    try:
        await missions.submit_task(
            TaskRequest(input="long mission", mode="auto"),
            BackgroundTasks(),
            SimpleNamespace(state=SimpleNamespace(user={})),
            None,
            None,
        )
        task = missions._active_mission_tasks["mission-cancel"]
        await asyncio.wait_for(orch.started.wait(), timeout=1)
        started = time.monotonic()
        await missions.abort_mission(
            "mission-cancel",
            AbortRequest(reason="stop"),
            None,
            None,
        )
        try:
            await asyncio.wait_for(task, timeout=1)
        except asyncio.CancelledError:
            pass

        elapsed = time.monotonic() - started
        assert elapsed < 2.0, (
            f"annulation trop lente : {elapsed}s (sleep(10) simule n'a pas du se terminer naturellement)"
        )
        assert orch.cancelled is True
        assert ms.complete_called is False
        assert ms.cancel_called is True
        assert task.cancelled() is True
        _print_case(
            "api_abort",
            elapsed=round(elapsed, 3),
            orch_cancelled=orch.cancelled,
            ms_complete_called=ms.complete_called,
            ms_cancel_called=ms.cancel_called,
            task_cancelled=task.cancelled(),
        )
    finally:
        _restore_routes(originals)


async def case_api_nominal_completion_marks_complete() -> None:
    ms = _MissionSystem("mission-ok")
    orch = _ControlledOrchestrator()
    queue = CoreTaskQueue()
    originals = _patch_routes(ms, orch, queue)
    try:
        await missions.submit_task(
            TaskRequest(input="normal mission", mode="auto"),
            BackgroundTasks(),
            SimpleNamespace(state=SimpleNamespace(user={})),
            None,
            None,
        )
        task = missions._active_mission_tasks["mission-ok"]
        await asyncio.wait_for(orch.started.wait(), timeout=1)
        orch.release.set()
        await asyncio.wait_for(task, timeout=1)
        assert ms.complete_called is True, "normal path should complete"
        assert task.cancelled() is False
        _print_case(
            "api_nominal",
            ms_complete_called=ms.complete_called,
            task_cancelled=task.cancelled(),
        )
    finally:
        _restore_routes(originals)


async def main() -> None:
    await asyncio.wait_for(case_core_task_queue_cancel_mission_matches_mission_id(), timeout=2)
    await asyncio.wait_for(case_api_abort_cancels_active_task_before_sleep_finishes(), timeout=3)
    await asyncio.wait_for(case_api_nominal_completion_marks_complete(), timeout=2)
    print("mission cancellation contract: PASS")


if __name__ == "__main__":
    asyncio.run(main())
