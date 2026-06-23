# Cron — Natural-Language Scheduled Tasks

Reference for FRIDAY's user-defined cron system: how natural-language schedules
become APScheduler jobs, how they fire, and how they persist.

Core files:
- [`friday/background/cron_scheduler.py`](../friday/background/cron_scheduler.py) — APScheduler wrapper
- [`friday/tools/cron_tools.py`](../friday/tools/cron_tools.py) — LLM-facing tools
- [`friday/memory/store.py`](../friday/memory/store.py) — SQLite `cron_jobs` table
- [`friday/cli.py`](../friday/cli.py) — scheduler startup wiring

---

## 1. Overview: cron vs watch-tasks

FRIDAY has two background execution primitives, and picking the right one matters:

| Primitive | Trigger | Use for |
|-----------|---------|---------|
| **Cron** (this doc) | Time-based — fires on a schedule (`0 8 * * 1-5`) | "Every weekday at 8am give me my briefing" |
| **Watch-task** ([heartbeat.py](../friday/background/heartbeat.py)) | Event-based — polls a condition until it changes | "Tell me when Ellen texts", "ping me when the build finishes" |

Cron jobs are *scheduled*. Watch-tasks are *event-triggered*. If the user says
"every X do Y" → cron. If they say "when X happens, tell me" → watch-task.
Both persist in SQLite and survive restarts, but they use different tables
(`cron_jobs` vs `watch_tasks`) and different runners.

---

## 2. Natural-language schedules

There is **no dedicated NL-to-cron parser**. The LLM itself is the parser.

The tool schema ([`cron_tools.py:42-54`](../friday/tools/cron_tools.py#L42)) tells
the model to convert plain English into a standard 5-field cron expression:

```
"description": "Create a scheduled cron job. The LLM converts natural language
schedules to cron expressions. Examples: '0 8 * * 1-5' = weekdays 8am,
'0 18 * * 5' = Friday 6pm, '*/15 * * * *' = every 15 min."
```

The resulting `schedule` string is then validated by
`CronTrigger.from_crontab()` — so anything APScheduler accepts is valid.

### What works

- Fixed times: "8am on weekdays", "6pm every Friday"
- Intervals: "every 15 minutes", "every 2 hours"
- Day-of-week ranges: "Monday through Friday"
- Specific dates of month: "the 1st of every month"
- Combinations: "every 30 min between 9am and 5pm on weekdays"

### What doesn't

- Sub-minute resolution — 5-field cron has minute granularity, no seconds.
- One-shot schedules ("at 3pm tomorrow") — use a reminder / watch-task instead;
  cron is for recurring jobs only.
- Timezone-relative phrasing ("8am Tokyo time") — schedule runs in the process's
  local tz (see section 6).
- Complex human rules ("every second Tuesday except holidays") — the LLM may
  produce a best-effort cron, but cron itself can't express exclusions.

---

## 3. The four tools

All four live in [`friday/tools/cron_tools.py`](../friday/tools/cron_tools.py)
and are routed through the `system_agent` (see
[`router.py:387`](../friday/core/router.py#L387)).

### `create_cron`

```json
{
  "name": "morning_briefing",
  "schedule": "0 8 * * 1-5",
  "task": "Give me my morning briefing",
  "channel": "cli"
}
```

- `name` — short identifier, shown in notifications
- `schedule` — standard 5-field cron (`min hour dom month dow`)
- `task` — natural-language instruction that will be fed back through the
  orchestrator at fire time
- `channel` — `cli` | `imessage` | `telegram` (default `cli`)

Validates the schedule via `CronTrigger.from_crontab`; rejects invalid
expressions before writing to DB.

### `list_crons`

No arguments. Returns all rows from `cron_jobs` ordered by `created_at DESC`,
including `last_run`, `run_count`, and `enabled` flag.

### `delete_cron`

```json
{ "job_id": "a1b2c3d4" }
```

Removes the row and calls `scheduler.remove_job(job_id)`. IDs are 8-char
UUID prefixes.

### `toggle_cron`

```json
{ "job_id": "a1b2c3d4", "enabled": false }
```

Flips the `enabled` flag. When disabling, the APScheduler job is removed from
the runtime (but the row stays in DB). When re-enabling, the job is
re-scheduled from the stored cron string.

---

## 4. What happens when a cron fires

Implemented in `CronScheduler._run_job`
([`cron_scheduler.py:84-124`](../friday/background/cron_scheduler.py#L84)):

1. APScheduler invokes `_run_job(job_id)` at the scheduled time.
2. The row is re-fetched from SQLite (to honour any just-made disable/delete).
3. If an `execute_fn` is wired in, the stored `task` string is passed to it:
   ```python
   result_text = await asyncio.wait_for(self._execute_fn(job["task"]), timeout=120)
   ```
   `execute_fn` runs the task through FRIDAY's orchestrator — so the cron gets
   the full LLM + tool loop, not a direct tool call. The task string is
   effectively "what the user would have typed."
4. `last_run` and `run_count` are updated in SQLite.
5. The result is passed to `notify_fn` — by default `notify_phone_async`
   (see [`cli.py:131-133`](../friday/cli.py#L131)), which pushes to the
   configured notification channel.

Timeout is a hard 120 seconds. Exceptions are caught and surfaced as the
notification text.

---

## 5. Persistence

Cron jobs live in SQLite — **not** in APScheduler's own job store.
APScheduler is used purely as the in-memory trigger engine; the source of
truth is the `cron_jobs` table in
[`friday/memory/store.py:120-131`](../friday/memory/store.py#L120):

```sql
CREATE TABLE IF NOT EXISTS cron_jobs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    schedule    TEXT NOT NULL,   -- 5-field cron expression
    task        TEXT NOT NULL,   -- NL instruction
    channel     TEXT DEFAULT 'cli',
    enabled     INTEGER DEFAULT 1,
    last_run    TEXT,
    next_run    TEXT,
    run_count   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);
```

DB path: `MEMORY_DIR / "friday.db"` (see
[`friday/core/config.py:84`](../friday/core/config.py#L84)).

On startup, `CronScheduler.start()`
([`cron_scheduler.py:40-58`](../friday/background/cron_scheduler.py#L40))
reads every row where `enabled = 1` and registers a fresh APScheduler job for
each. Restart-safety comes from this reload — no jobstore plugin is configured.

---

## 6. Timezone handling

`AsyncIOScheduler` is constructed with **no explicit `timezone=` argument**
([`cron_scheduler.py:27-33`](../friday/background/cron_scheduler.py#L27)). That
means APScheduler defaults to `tzlocal.get_localzone()` — the system
timezone of the machine FRIDAY runs on.

Implications:
- No `user.json` timezone override is applied.
- The Mac's System Settings → Date & Time timezone is what counts.
- If the user says "8am" they get 8am in the machine's local time.
- Travelling with the laptop will shift all crons unless the system tz is pinned.

To pin a timezone, pass `timezone=ZoneInfo("Europe/London")` into
`AsyncIOScheduler(...)` — currently not wired through.

---

## 7. Examples

### Morning briefing, weekdays at 8am

```json
{
  "name": "morning_briefing",
  "schedule": "0 8 * * 1-5",
  "task": "Give me my morning briefing — unread emails, calendar, and top news."
}
```

### Weekly activity summary, Sunday 9pm

```json
{
  "name": "weekly_summary",
  "schedule": "0 21 * * 0",
  "task": "Summarise this week's activity: commits, messages, calendar events.",
  "channel": "imessage"
}
```

### Stretch reminder, every 2 hours between 9am and 5pm

```json
{
  "name": "stretch",
  "schedule": "0 9-17/2 * * *",
  "task": "Remind me to stand up and stretch."
}
```

---

## 8. Relationship to heartbeat

Cron and heartbeat are **independent**. Heartbeat
([`friday/background/heartbeat.py`](../friday/background/heartbeat.py)) is a
single polling loop that checks all active `watch_tasks`. Cron is a separate
APScheduler instance with per-job triggers. They share:

- The same SQLite database.
- The same `notify_fn` wiring (`notify_phone_async` from
  [`friday/tools/notify.py`](../friday/tools/notify.py)).

They do **not** share:
- A task queue — cron jobs never enter the heartbeat loop.
- Scheduling logic — heartbeat ticks on an interval, cron fires on trigger times.

Both start from [`cli.py:120-135`](../friday/cli.py#L120) during FRIDAY boot.

---

## 9. Debugging

### Logs

Cron uses the logger `friday.cron`
([`cron_scheduler.py:20`](../friday/background/cron_scheduler.py#L20)). Startup,
scheduling, and every fire are logged. Look in whichever log sink FRIDAY is
writing to (stdout by default; the CLI doesn't pin a log file).

Key log lines to grep:
- `Cron scheduler started. N active job(s).`
- `Scheduled cron '<name>' (<schedule>)`
- `Cron firing: '<name>' — task: <first 60 chars>`
- `Invalid cron schedule for '<name>'` (validation failure on startup)

### Inspect scheduled jobs

Fastest path — SQLite directly:

```bash
sqlite3 ~/.friday/memory/friday.db \
  "SELECT id, name, schedule, enabled, last_run, run_count FROM cron_jobs;"
```

In-process status: `CronScheduler.get_status()` returns `running`,
`total_jobs`, `active_jobs`, `scheduler_running`.

### Manual trigger

There is no public "fire now" method. Two options:

1. Temporarily edit the `schedule` to a minute ahead via `create_cron` (after
   deleting the original), or
2. Call `await cron._run_job(job_id)` directly from a REPL — the underscore
   prefix means it's unstable, but it does execute the full pipeline.

---

## 10. Limitations

- **Minute granularity.** Five-field cron has no sub-minute field.
- **No missed-run catch-up.** Jobs are created with `misfire_grace_time=None`
  and `coalesce=True`
  ([`cron_scheduler.py:28-32`](../friday/background/cron_scheduler.py#L28)) —
  if FRIDAY was offline at trigger time, that fire is silently skipped.
  Multiple missed fires collapse into at most one.
- **Mac asleep = cron skipped.** APScheduler runs in-process; if the Mac is
  asleep, no timer fires. The job does not queue up for wake.
- **`max_instances=1`.** A job cannot overlap itself — if a previous run is
  still executing, the new trigger is dropped.
- **120s per-job timeout.** Long-running tasks (deep research, video
  processing) will be killed and reported as `timed out after 120s`.
- **No jitter / concurrency control across jobs.** Ten jobs scheduled for
  `0 8 * * *` all fire simultaneously and all hit the orchestrator.
- **Fragile to system tz changes.** Travelling shifts all crons (section 6).

---

Summary: FRIDAY's cron is an APScheduler wrapper backed by a SQLite `cron_jobs` table. The LLM converts natural language into 5-field cron expressions via the `create_cron` tool schema. Four tools (`create_cron`, `list_crons`, `delete_cron`, `toggle_cron`) handle CRUD. Fires run stored task strings back through the orchestrator. Jobs survive restarts by reloading on boot; no catch-up on missed runs.
