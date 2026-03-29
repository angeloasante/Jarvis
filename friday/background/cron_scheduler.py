"""Cron Scheduler — user-defined scheduled tasks.

Users create crons conversationally ("remind me every weekday at 8am to check email").
FRIDAY parses the schedule, stores in SQLite, and APScheduler executes on time.
Each cron fires a task string through the orchestrator — full LLM processing.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from friday.memory.store import get_memory_store
from friday.core.types import ToolResult

log = logging.getLogger("friday.cron")


class CronScheduler:
    """Manages user-defined cron jobs backed by SQLite + APScheduler."""

    def __init__(self, execute_fn: Optional[Callable] = None, notify_fn: Optional[Callable] = None):
        self.scheduler = AsyncIOScheduler(
            job_defaults={
                "misfire_grace_time": None,
                "coalesce": True,
                "max_instances": 1,
            },
        )
        self._started = False
        # execute_fn(task: str) -> str — runs a task through the orchestrator
        self._execute_fn = execute_fn
        # notify_fn(text: str) — sends output to user
        self._notify_fn = notify_fn or self._default_notify

    async def start(self):
        """Load all enabled cron jobs from DB and schedule them."""
        if self._started:
            return

        db = get_memory_store().db
        rows = db.execute("SELECT * FROM cron_jobs WHERE enabled = 1").fetchall()

        for row in rows:
            job = dict(row)
            self._schedule_job(job)

        if rows:
            self.scheduler.start()
            log.info(f"Cron scheduler started. {len(rows)} active job(s).")
        else:
            log.info("Cron scheduler: no active jobs.")

        self._started = True

    async def stop(self):
        if self._started:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
            self._started = False

    def _schedule_job(self, job: dict):
        """Add a single cron job to APScheduler."""
        try:
            trigger = CronTrigger.from_crontab(job["schedule"])
        except ValueError as e:
            log.error(f"Invalid cron schedule for '{job['name']}': {job['schedule']} — {e}")
            return

        self.scheduler.add_job(
            self._run_job,
            trigger=trigger,
            args=[job["id"]],
            id=job["id"],
            replace_existing=True,
            max_instances=1,
        )
        log.debug(f"Scheduled cron '{job['name']}' ({job['schedule']})")

    async def _run_job(self, job_id: str):
        """Execute a cron job — runs task through orchestrator."""
        db = get_memory_store().db
        row = db.execute("SELECT * FROM cron_jobs WHERE id = ? AND enabled = 1", (job_id,)).fetchone()

        if not row:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass
            return

        job = dict(row)
        now = datetime.now()

        log.info(f"Cron firing: '{job['name']}' — task: {job['task'][:60]}")

        result_text = None
        try:
            if self._execute_fn:
                result_text = await asyncio.wait_for(
                    self._execute_fn(job["task"]),
                    timeout=120,
                )
        except asyncio.TimeoutError:
            result_text = f"Cron '{job['name']}' timed out after 120s."
            log.warning(result_text)
        except Exception as e:
            result_text = f"Cron '{job['name']}' failed: {e}"
            log.error(result_text)

        # Update job state
        db.execute(
            "UPDATE cron_jobs SET last_run = ?, run_count = run_count + 1 WHERE id = ?",
            (now.isoformat(), job_id),
        )
        db.commit()

        # Notify user with result
        if result_text:
            await self._notify_fn(f"⏰ [{job['name']}] {result_text}")

    # ── CRUD ────────────────────────────────────────────────────────────────

    def create_job(self, name: str, schedule: str, task: str, channel: str = "cli") -> ToolResult:
        """Create a new cron job."""
        # Validate cron expression
        try:
            CronTrigger.from_crontab(schedule)
        except ValueError as e:
            return ToolResult(success=False, data={"error": f"Invalid cron schedule: {e}"})

        job_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()

        db = get_memory_store().db
        db.execute(
            "INSERT INTO cron_jobs (id, name, schedule, task, channel, enabled, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (job_id, name, schedule, task, channel, now),
        )
        db.commit()

        job = {
            "id": job_id, "name": name, "schedule": schedule,
            "task": task, "channel": channel, "enabled": 1,
        }
        self._schedule_job(job)

        # Ensure scheduler is running
        if not self.scheduler.running:
            self.scheduler.start()

        return ToolResult(success=True, data={
            "id": job_id, "name": name, "schedule": schedule,
            "task": task, "channel": channel,
            "message": f"Cron '{name}' created. Schedule: {schedule}",
        })

    def list_jobs(self) -> ToolResult:
        """List all cron jobs."""
        db = get_memory_store().db
        rows = db.execute("SELECT * FROM cron_jobs ORDER BY created_at DESC").fetchall()
        jobs = [dict(r) for r in rows]
        return ToolResult(success=True, data=jobs)

    def delete_job(self, job_id: str) -> ToolResult:
        """Delete a cron job."""
        db = get_memory_store().db
        row = db.execute("SELECT name FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return ToolResult(success=False, data={"error": f"No cron job with ID '{job_id}'"})

        name = row["name"]
        db.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        db.commit()

        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

        return ToolResult(success=True, data={"message": f"Cron '{name}' deleted."})

    def toggle_job(self, job_id: str, enabled: bool) -> ToolResult:
        """Enable or disable a cron job."""
        db = get_memory_store().db
        row = db.execute("SELECT name FROM cron_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return ToolResult(success=False, data={"error": f"No cron job with ID '{job_id}'"})

        name = row["name"]
        db.execute("UPDATE cron_jobs SET enabled = ? WHERE id = ?", (1 if enabled else 0, job_id))
        db.commit()

        if enabled:
            job = dict(db.execute("SELECT * FROM cron_jobs WHERE id = ?", (job_id,)).fetchone())
            self._schedule_job(job)
            if not self.scheduler.running:
                self.scheduler.start()
        else:
            try:
                self.scheduler.remove_job(job_id)
            except Exception:
                pass

        state = "enabled" if enabled else "disabled"
        return ToolResult(success=True, data={"message": f"Cron '{name}' {state}."})

    def get_status(self) -> dict:
        db = get_memory_store().db
        total = db.execute("SELECT COUNT(*) FROM cron_jobs").fetchone()[0]
        active = db.execute("SELECT COUNT(*) FROM cron_jobs WHERE enabled = 1").fetchone()[0]
        return {
            "running": self._started,
            "total_jobs": total,
            "active_jobs": active,
            "scheduler_running": self.scheduler.running if self._started else False,
        }

    @staticmethod
    async def _default_notify(text: str):
        from rich.console import Console
        console = Console()
        console.print(f"\n  [bold cyan]⏰ FRIDAY[/bold cyan] [cyan]{text}[/cyan]\n")


# Singleton
_cron: CronScheduler | None = None


def get_cron_scheduler(execute_fn=None, notify_fn=None) -> CronScheduler:
    global _cron
    if _cron is None:
        _cron = CronScheduler(execute_fn=execute_fn, notify_fn=notify_fn)
    return _cron
