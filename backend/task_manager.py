"""Background task manager — asyncio-based task tracking.
Adapted from senior repo. Lets the frontend poll task status even after page refresh.

Place this file at: backend/task_manager.py
"""

from __future__ import annotations
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Coroutine

# ── Task store ────────────────────────────────────────────────────────────────

class TaskInfo:
    __slots__ = ("id", "type", "campaign_id", "status", "progress", "result", "error", "created_at", "updated_at")

    def __init__(self, task_id: str, task_type: str, campaign_id: str):
        self.id = task_id
        self.type = task_type
        self.campaign_id = campaign_id
        self.status = "running"          # running | completed | failed
        self.progress = ""
        self.result: Any = None
        self.error: str | None = None
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "type":        self.type,
            "campaign_id": self.campaign_id,
            "status":      self.status,
            "progress":    self.progress,
            "result":      self.result,
            "error":       self.error,
            "created_at":  self.created_at,
            "updated_at":  self.updated_at,
        }


_tasks: dict[str, TaskInfo] = {}
_asyncio_tasks: dict[str, asyncio.Task] = {}


def _update(task: TaskInfo, **kwargs: Any) -> None:
    for k, v in kwargs.items():
        setattr(task, k, v)
    task.updated_at = datetime.now(timezone.utc).isoformat()


async def _run_task(task_id: str, coro: Coroutine) -> None:
    """Wrapper: runs a coroutine and captures result/error into the store."""
    task = _tasks[task_id]
    try:
        result = await coro
        _update(task, status="completed", result=result)
        print(f"✅ task.completed id={task_id} type={task.type}")
    except Exception as e:
        _update(task, status="failed", error=str(e))
        print(f"❌ task.failed id={task_id} type={task.type} error={e}")


def start_task(task_type: str, campaign_id: str, coro: Coroutine) -> str:
    """Launch a background coroutine and return its task_id immediately."""
    task_id = str(uuid.uuid4())
    info = TaskInfo(task_id, task_type, campaign_id)
    _tasks[task_id] = info

    loop = asyncio.get_event_loop()
    at = loop.create_task(_run_task(task_id, coro))
    _asyncio_tasks[task_id] = at

    print(f"🚀 task.started id={task_id} type={task_type} campaign={campaign_id}")
    return task_id


def get_task(task_id: str) -> dict | None:
    info = _tasks.get(task_id)
    return info.to_dict() if info else None


def list_tasks(campaign_id: str | None = None) -> list[dict]:
    tasks = list(_tasks.values())
    if campaign_id:
        tasks = [t for t in tasks if t.campaign_id == campaign_id]
    # Most recent first, max 50
    return [t.to_dict() for t in sorted(tasks, key=lambda t: t.created_at, reverse=True)][:50]


def get_active_tasks() -> list[dict]:
    """Get all currently running tasks — useful for debug endpoint."""
    return [t.to_dict() for t in _tasks.values() if t.status == "running"]