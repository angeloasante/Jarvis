"""Monitor Scheduler — runs forever in the background.

Checks all active monitors on their schedules.
Queues alerts for the briefing agent when things change.
"""

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from friday.memory.store import get_memory_store

log = logging.getLogger("friday.monitor")


class MonitorScheduler:
    """Background scheduler for persistent monitors."""

    FREQUENCY_MINUTES = {
        "realtime": 15,
        "hourly": 60,
        "daily": 1440,
        "weekly": 10080,
    }

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._started = False

    async def start(self):
        """Load all active monitors from DB and schedule them."""
        if self._started:
            return

        db = get_memory_store().db
        rows = db.execute("SELECT * FROM monitors WHERE active = 1").fetchall()

        if not rows:
            log.info("Monitor scheduler: no active monitors.")
            self._started = True
            return

        columns = [desc[0] for desc in db.execute("SELECT * FROM monitors LIMIT 0").description]

        for row in rows:
            monitor = dict(zip(columns, row))
            self._schedule(monitor)

        self.scheduler.start()
        self._started = True
        log.info(f"Monitor scheduler started. Watching {len(rows)} targets.")

    def _schedule(self, monitor: dict):
        """Schedule a single monitor for recurring checks."""
        interval = self.FREQUENCY_MINUTES.get(monitor["frequency"], 60)

        self.scheduler.add_job(
            self._run_check,
            trigger=IntervalTrigger(minutes=interval),
            args=[monitor["id"]],
            id=monitor["id"],
            replace_existing=True,
            max_instances=1,
        )

    async def _run_check(self, monitor_id: str):
        """Run a check for a specific monitor."""
        from friday.tools.monitor_tools import run_monitor_check

        db = get_memory_store().db
        row = db.execute("SELECT * FROM monitors WHERE id = ? AND active = 1", (monitor_id,)).fetchone()

        if not row:
            # Monitor deleted or paused — remove job
            try:
                self.scheduler.remove_job(monitor_id)
            except Exception:
                pass
            return

        columns = [desc[0] for desc in db.execute("SELECT * FROM monitors LIMIT 0").description]
        monitor = dict(zip(columns, row))

        try:
            result = await run_monitor_check(monitor)
            if result.data and result.data.get("changed"):
                topic = result.data.get("topic", monitor_id)
                material = result.data.get("material", False)
                log.info(
                    f"Monitor '{topic}' detected change "
                    f"(material={material}, importance={result.data.get('importance', 'normal')})"
                )
        except Exception as e:
            log.error(f"Monitor check failed for {monitor_id}: {e}")

    def add_monitor(self, monitor: dict):
        """Called when a new monitor is created at runtime."""
        self._schedule(monitor)
        if not self.scheduler.running:
            self.scheduler.start()
            self._started = True

    def remove_monitor(self, monitor_id: str):
        """Called when a monitor is deleted or paused."""
        try:
            self.scheduler.remove_job(monitor_id)
        except Exception:
            pass

    def get_status(self) -> dict:
        """Get scheduler status for debugging."""
        jobs = self.scheduler.get_jobs() if self.scheduler.running else []
        return {
            "running": self.scheduler.running if self._started else False,
            "job_count": len(jobs),
            "jobs": [{"id": j.id, "next_run": str(j.next_run_time)} for j in jobs],
        }


# Singleton
_scheduler: MonitorScheduler | None = None


def get_monitor_scheduler() -> MonitorScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = MonitorScheduler()
    return _scheduler
