# FRIDAY x Oura Ring — Complete API Reference
### *"The arc reactor equivalent. FRIDAY's window into your body."*

---

## Table of Contents

1. [Critical Note — Membership Required](#critical-note--membership-required)
2. [Quick Setup](#quick-setup)
3. [Authentication](#authentication)
4. [Base URL & Headers](#base-url--headers)
5. [All Endpoints — Complete List](#all-endpoints--complete-list)
6. [Endpoint Deep Dives](#endpoint-deep-dives)
7. [Webhooks — Real-Time Updates](#webhooks--real-time-updates)
8. [Rate Limits & Sync Behaviour](#rate-limits--sync-behaviour)
9. [FRIDAY Integration Layer](#friday-integration-layer)
10. [Biometric Interpretation Guide](#biometric-interpretation-guide)
11. [FRIDAY Autonomous Action Map](#friday-autonomous-action-map)
12. [Sandbox Testing](#sandbox-testing)
13. [Gotchas & Known Issues](#gotchas--known-issues)

---

## Critical Note — Membership Required

Before buying the ring, know this:

**Gen3 and Oura Ring 4 users without an active Oura Membership
will NOT be able to access their data through the Oura API.**

```
Oura Ring 4 purchase:     ~£349
Oura Membership:          ~£5.99/month (after 6-month free trial)
Without membership:       API access blocked entirely

The ring comes with a 6-month free trial of membership.
After that — £5.99/month or lose API access.
```

This is not optional. Build the membership cost into your budget.

---

## Quick Setup

### Step 1 — Get Personal Access Token (PAT)

After buying the ring and setting up your account:

```
1. Go to: https://cloud.ouraring.com/personal-access-tokens
2. Click "Create New Personal Access Token"
3. Name it "FRIDAY"
4. Copy the token — you only see it once
5. Add to .env:
   OURA_ACCESS_TOKEN=your_token_here
```

### Step 2 — Install

```bash
uv add oura-ring httpx
# oura-ring is the community Python wrapper
# httpx for direct API calls where needed
```

### Step 3 — First Call

```python
from oura_ring import OuraClient
import os

client = OuraClient(os.environ["OURA_ACCESS_TOKEN"])

# Test it
info = client.get_personal_info()
print(info)
# {"id": "...", "age": ..., "weight": ..., "height": ..., "email": "..."}

# Get today's readiness
readiness = client.get_daily_readiness()
print(readiness[0]["score"])  # e.g. 87
```

### Step 4 — Sandbox (Before Ring Arrives)

Test FRIDAY's biometric integration before you have the ring.
Oura provides a sandbox with realistic sample data.

```python
import httpx

# Sandbox base URL — returns sample data, no auth needed
SANDBOX_URL = "https://api.ouraring.com/v2/sandbox/usercollection"

async with httpx.AsyncClient() as client:
    # Works without a real token in sandbox mode
    response = await client.get(
        f"{SANDBOX_URL}/heartrate",
        headers={"Authorization": "Bearer sandbox_token"}
    )
    print(response.json())
```

---

## Authentication

Two methods. For FRIDAY (personal use), PAT is fine.

### Personal Access Token (PAT) — Use This

Simple. One token. Works for personal use.

```python
headers = {
    "Authorization": f"Bearer {os.environ['OURA_ACCESS_TOKEN']}"
}
```

Token never expires unless you revoke it.
Rotate it if you think it's compromised.

### OAuth2 — Only If Building Multi-User App

If you ever add Oura to Diaspora AI or a public product:

```python
# OAuth2 scopes available
SCOPES = [
    "personal",       # Personal info (age, weight, height)
    "daily",          # Daily summaries (sleep, activity, readiness)
    "heartrate",      # Heart rate data
    "workout",        # Workout sessions
    "tag",            # User-created tags
    "session",        # Meditation/breathing sessions
    "spo2",           # Blood oxygen
    "stress",         # Daily stress score (Gen3/Ring4 only)
    "ring_configuration"  # Ring hardware info
]

# Auth URL pattern
AUTH_URL = (
    "https://cloud.ouraring.com/oauth/authorize"
    f"?response_type=code"
    f"&client_id={CLIENT_ID}"
    f"&redirect_uri={REDIRECT_URI}"
    f"&scope={'+'.join(SCOPES)}"
)

# Token endpoint
TOKEN_URL = "https://api.ouraring.com/oauth/token"
```

For FRIDAY — stick with PAT. OAuth2 is overkill for personal use.

---

## Base URL & Headers

```python
BASE_URL = "https://api.ouraring.com/v2/usercollection"

HEADERS = {
    "Authorization": f"Bearer {os.environ['OURA_ACCESS_TOKEN']}",
    "Content-Type": "application/json"
}

# NEVER pass token as query parameter — it's blocked in V2
# WRONG:  GET /heartrate?access_token=xxx
# CORRECT: GET /heartrate with Authorization header
```

---

## All Endpoints — Complete List

Every endpoint available in V2 as of March 2026:

```
GET  /v2/usercollection/personal_info
GET  /v2/usercollection/heartrate
GET  /v2/usercollection/daily_activity
GET  /v2/usercollection/daily_activity/{document_id}
GET  /v2/usercollection/daily_readiness
GET  /v2/usercollection/daily_readiness/{document_id}
GET  /v2/usercollection/daily_sleep
GET  /v2/usercollection/daily_sleep/{document_id}
GET  /v2/usercollection/daily_stress
GET  /v2/usercollection/daily_stress/{document_id}
GET  /v2/usercollection/daily_resilience
GET  /v2/usercollection/daily_resilience/{document_id}
GET  /v2/usercollection/daily_spo2
GET  /v2/usercollection/daily_spo2/{document_id}
GET  /v2/usercollection/daily_cardiovascular_age
GET  /v2/usercollection/daily_cardiovascular_age/{document_id}
GET  /v2/usercollection/sleep
GET  /v2/usercollection/sleep/{document_id}
GET  /v2/usercollection/sleep_time
GET  /v2/usercollection/sleep_time/{document_id}
GET  /v2/usercollection/session
GET  /v2/usercollection/session/{document_id}
GET  /v2/usercollection/workout
GET  /v2/usercollection/workout/{document_id}
GET  /v2/usercollection/vo2_max
GET  /v2/usercollection/vo2_max/{document_id}
GET  /v2/usercollection/rest_mode_period
GET  /v2/usercollection/rest_mode_period/{document_id}
GET  /v2/usercollection/ring_configuration
GET  /v2/usercollection/ring_configuration/{document_id}
GET  /v2/usercollection/enhanced_tag
GET  /v2/usercollection/enhanced_tag/{document_id}

POST /v2/webhook/subscription
GET  /v2/webhook/subscription
PUT  /v2/webhook/subscription/{id}
DELETE /v2/webhook/subscription/{id}
PUT  /v2/webhook/subscription/renew/{id}
```

---

## Endpoint Deep Dives

### Heart Rate — Most Important For FRIDAY

```
GET /v2/usercollection/heartrate
```

The only endpoint that gives you **granular time-series data.**
Every other endpoint is daily summaries.

Parameters:
```
start_datetime  ISO 8601 with time: "2026-03-22T00:00:00"
end_datetime    ISO 8601 with time: "2026-03-22T23:59:59"
```

Response:
```json
{
  "data": [
    {
      "bpm": 68,
      "source": "awake",
      "timestamp": "2026-03-22T02:31:00+00:00"
    },
    {
      "bpm": 71,
      "source": "awake",
      "timestamp": "2026-03-22T02:32:00+00:00"
    }
  ],
  "next_token": null
}
```

Source values:
```
"awake"       — measured while awake, every ~5 minutes
"sleep"       — measured during sleep, every minute
"rest"        — measured during detected rest
"workout"     — measured during workout
"ppg_calorie" — background measurement
```

Frequency:
```
During sleep:  ~1 reading per minute
While awake:   ~1 reading per 5 minutes
               (only when ring syncs to phone)
```

Important limitation: readings only appear after ring syncs to phone
via Bluetooth. Not true real-time streaming.

Python:
```python
from datetime import datetime, timedelta

async def get_recent_heart_rate(minutes: int = 30) -> list[dict]:
    now = datetime.now()
    start = now - timedelta(minutes=minutes)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/heartrate",
            headers=HEADERS,
            params={
                "start_datetime": start.isoformat(),
                "end_datetime": now.isoformat()
            }
        )
        data = response.json().get("data", [])
        return sorted(data, key=lambda x: x["timestamp"])

# Get latest single reading
async def get_current_hr() -> int | None:
    readings = await get_recent_heart_rate(minutes=10)
    if readings:
        return readings[-1]["bpm"]
    return None
```

---

### Daily Readiness — FRIDAY's Primary State Indicator

```
GET /v2/usercollection/daily_readiness
```

Parameters:
```
start_date  YYYY-MM-DD
end_date    YYYY-MM-DD
```

Response:
```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "contributors": {
        "activity_balance": 80,
        "body_temperature": 99,
        "hrv_balance": 72,
        "previous_day_activity": 85,
        "previous_night": 91,
        "recovery_index": 88,
        "resting_heart_rate": 94,
        "sleep_balance": 78
      },
      "day": "2026-03-22",
      "score": 84,
      "temperature_deviation": -0.12,
      "temperature_trend_deviation": 0.18,
      "timestamp": "2026-03-22T00:00:00+00:00"
    }
  ]
}
```

Interpreting readiness score:
```
85-100  Excellent — high energy, good decision-making day
70-84   Good — normal day, most tasks fine
60-69   Fair — some fatigue, avoid big decisions if possible
45-59   Low — tired, this is a recovery day
0-44    Very low — body is cooked, FRIDAY should be direct about this
```

Contributors breakdown (each 0-100):
```
activity_balance     — recent activity vs historical baseline
body_temperature     — deviation from your personal baseline
hrv_balance          — HRV trend over past 2 weeks
previous_day_activity— yesterday's activity impact
previous_night       — last night's sleep contribution
recovery_index       — how much HRV rose during sleep (key metric)
resting_heart_rate   — how low HR went during sleep
sleep_balance        — recent sleep duration vs what you need
```

Python:
```python
async def get_todays_readiness() -> dict:
    today = datetime.now().date().isoformat()

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/daily_readiness",
            headers=HEADERS,
            params={"start_date": today, "end_date": today}
        )
        data = response.json().get("data", [])
        return data[0] if data else {}
```

---

### Daily Sleep — Detailed Sleep Analysis

```
GET /v2/usercollection/daily_sleep
```

Response:
```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "contributors": {
        "deep_sleep": 72,
        "efficiency": 94,
        "latency": 88,
        "rem_sleep": 65,
        "restfulness": 71,
        "timing": 45,
        "total_sleep": 80
      },
      "day": "2026-03-22",
      "score": 76,
      "timestamp": "2026-03-22T00:00:00+00:00"
    }
  ]
}
```

Key contributors:
```
deep_sleep    — slow-wave sleep %, critical for physical recovery
efficiency    — % of time in bed actually sleeping
latency       — how quickly you fell asleep (high = fell asleep fast)
rem_sleep     — REM %, critical for memory and mood
restfulness   — how much you moved during sleep
timing        — alignment with your optimal sleep window
total_sleep   — total duration vs your personal need
```

Detailed sleep session (granular):
```
GET /v2/usercollection/sleep

Returns individual sleep sessions with:
- sleep_phase_5_min: array of sleep stages every 5 minutes
  Values: 1=awake, 2=REM, 3=light, 4=deep
- heart_rate: 5-minute interval HR during sleep
- hrv: 5-minute interval HRV during sleep
- movement_30_sec: movement every 30 seconds
- average_hrv: HRV average for full night
- lowest_heart_rate: lowest HR reached (lower = better recovery)
- total_sleep_duration: in seconds
```

---

### Daily Stress — The Jarvis Nightmare Detector

```
GET /v2/usercollection/daily_stress
```

**Gen3 / Ring 4 only. Not available on Gen2.**

Response:
```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "day": "2026-03-22",
      "stress_high": 45,
      "recovery_high": 120,
      "day_summary": "stressful"
    }
  ]
}
```

Fields:
```
stress_high    — minutes of high stress during the day
recovery_high  — minutes of high recovery/calm during the day
day_summary    — "restored" | "normal" | "stressful" | "tense"
```

This is the metric that would have detected Stark's nightmare.
High stress_high during sleep hours = nightmare/disturbance.

---

### Daily Resilience — Medium-Term Stress Capacity

```
GET /v2/usercollection/daily_resilience
```

**Gen3 / Ring 4 only.**

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "contributors": {
        "daytime_recovery": 72,
        "daytime_stress": 45,
        "sleep_recovery": 88
      },
      "day": "2026-03-22",
      "level": "adequate"
    }
  ]
}
```

Level values:
```
"exceptional"  — very high capacity to handle stress
"strong"       — good capacity
"adequate"     — normal
"limited"      — getting close to burnout territory
"overwhelmed"  — system is overwhelmed
```

This is the 14-day rolling metric. Changes slowly.
Useful for FRIDAY to spot burnout trajectory before it hits.

---

### Daily Activity — Movement & Energy

```
GET /v2/usercollection/daily_activity
```

Response includes:
```json
{
  "active_calories": 342,
  "average_met_minutes": 1.2,
  "contributors": {
    "meet_daily_targets": 75,
    "move_every_hour": 60,
    "recovery_time": 88,
    "stay_active": 71,
    "training_frequency": 50,
    "training_volume": 45
  },
  "equivalent_walking_distance": 6200,
  "high_activity_met_minutes": 45,
  "high_activity_time": 1800,
  "inactivity_alerts": 2,
  "low_activity_met_minutes": 120,
  "low_activity_time": 7200,
  "medium_activity_met_minutes": 200,
  "medium_activity_time": 5400,
  "meters_to_target": 2800,
  "non_wear_time": 3600,
  "resting_time": 50400,
  "score": 68,
  "sedentary_met_minutes": 450,
  "sedentary_time": 28800,
  "steps": 6234,
  "target_calories": 500,
  "target_meters": 9000,
  "total_calories": 2100
}
```

FRIDAY relevant fields:
```
steps               — total steps today
sedentary_time      — seconds sitting still (in seconds — divide by 3600 for hours)
inactivity_alerts   — how many times ring detected prolonged inactivity
score               — overall activity score 0-100
```

---

### Daily SpO2 — Blood Oxygen

```
GET /v2/usercollection/daily_spo2
```

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "day": "2026-03-22",
      "spo2_percentage": {
        "average": 97.8,
        "breathing_disturbance_index": 4.2
      }
    }
  ]
}
```

Normal SpO2: 95-100%
Below 94%: flag for FRIDAY
Below 90%: medical concern — FRIDAY escalates

breathing_disturbance_index: 0-100
Higher = more breathing disruptions during sleep
Correlated with sleep apnea risk

---

### VO2 Max — Cardiovascular Fitness

```
GET /v2/usercollection/vo2_max
```

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "day": "2026-03-22",
      "vo2_max": 46.5,
      "timestamp": "2026-03-22T07:00:00+00:00"
    }
  ]
}
```

VO2 Max ranges for men:
```
< 35    Below average
35-42   Average
42-50   Good
50-56   Very good
> 56    Excellent
```

Updates slowly — maybe weekly. Long-term fitness tracker.

---

### Daily Cardiovascular Age

```
GET /v2/usercollection/daily_cardiovascular_age
```

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "day": "2026-03-22",
      "vascular_age": 28
    }
  ]
}
```

Derived from HRV, resting HR, VO2 Max trends.
Your cardiovascular system's estimated biological age.
If vascular_age < actual age — good. If higher — worth noting.

---

### Workout — Exercise Detection

```
GET /v2/usercollection/workout
```

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "activity": "running",
      "average_heart_rate": 142,
      "calories": 320,
      "day": "2026-03-22",
      "distance": 5200,
      "end_datetime": "2026-03-22T08:30:00+00:00",
      "intensity": "moderate",
      "label": null,
      "source": "automatic_detected",
      "start_datetime": "2026-03-22T08:00:00+00:00"
    }
  ]
}
```

Important for FRIDAY: if `workout` session detected and HR is high
— do NOT flag as stress. Travis is exercising.

---

### Sleep Time — Optimal Window

```
GET /v2/usercollection/sleep_time
```

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "day": "2026-03-22",
      "optimal_bedtime": {
        "day_tz": 60,
        "end_offset": -30,
        "start_offset": -60
      },
      "recommendation": "follow_optimal_bedtime",
      "status": "optimal_found"
    }
  ]
}
```

FRIDAY can use this to tell Travis when he should ideally sleep
based on his own historical patterns.

---

### Ring Configuration

```
GET /v2/usercollection/ring_configuration
```

```json
{
  "data": [
    {
      "id": "8f9a5221-...",
      "color": "stealth_black",
      "design": "balance",
      "firmware_version": "2.9.27",
      "hardware_type": "gen4",
      "set_up_at": "2026-03-01T10:00:00+00:00",
      "size": 10
    }
  ]
}
```

Useful for: confirming ring is set up correctly.
hardware_type tells you if it's gen3 or gen4
(gen4 = all stress/resilience features available)

---

## Webhooks — Real-Time Updates

Webhooks are the closest thing to real-time. When ring syncs to phone,
Oura pushes data to your endpoint.

**This is how FRIDAY gets notified instead of constantly polling.**

### Supported Event Types

```
create.daily_activity
create.daily_cardiovascular_age
create.daily_readiness
create.daily_resilience
create.daily_sleep
create.daily_spo2
create.daily_stress
create.enhanced_tag
create.heartrate
create.rest_mode_period
create.ring_configuration
create.session
create.sleep
create.sleep_time
create.tag
create.vo2_max
create.workout
```

### Create Webhook Subscription

```python
async def create_webhook(
    callback_url: str,
    event_type: str
) -> dict:
    """
    Register FRIDAY's endpoint to receive Oura data pushes.
    callback_url must be publicly accessible.
    For Mac Mini at home: use ngrok or Cloudflare Tunnel.
    """

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.ouraring.com/v2/webhook/subscription",
            headers=HEADERS,
            json={
                "callback_url": callback_url,
                "event_type": event_type,
                "data_type": event_type.split(".")[1],
                "verification_token": os.environ["WEBHOOK_VERIFY_TOKEN"]
            }
        )
        return response.json()

# Subscribe to the most important events
FRIDAY_WEBHOOK_SUBSCRIPTIONS = [
    "create.heartrate",          # Most granular — every sync
    "create.daily_readiness",    # Morning readiness score
    "create.daily_stress",       # Daily stress summary
    "create.daily_sleep",        # Sleep score each morning
    "create.daily_resilience",   # Resilience level changes
]
```

### Receive Webhook

```python
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()

@app.post("/oura/webhook")
async def receive_oura_webhook(request: Request):

    # Verify it's actually from Oura
    verification_token = request.headers.get("X-Oura-Verification-Token")
    if verification_token != os.environ["WEBHOOK_VERIFY_TOKEN"]:
        raise HTTPException(status_code=401, detail="Invalid token")

    payload = await request.json()

    event_type = payload.get("event_type")
    data = payload.get("data", {})

    # Route to FRIDAY's biometric processor
    await process_oura_event(event_type, data)

    return {"status": "received"}


async def process_oura_event(event_type: str, data: dict):
    """Process incoming Oura webhook and update FRIDAY's context."""

    if event_type == "create.heartrate":
        await handle_heart_rate_update(data)

    elif event_type == "create.daily_readiness":
        await handle_readiness_update(data)

    elif event_type == "create.daily_stress":
        await handle_stress_update(data)

    elif event_type == "create.daily_sleep":
        await handle_sleep_update(data)

    elif event_type == "create.daily_resilience":
        await handle_resilience_update(data)
```

### Expose Locally (Cloudflare Tunnel — Free)

For Mac Mini at home to receive webhooks:

```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared

# Create tunnel
cloudflared tunnel --url http://localhost:8000

# Returns a public URL like:
# https://random-words-here.trycloudflare.com

# Use that URL as your webhook callback_url
# It's persistent while the tunnel is running
```

---

## Rate Limits & Sync Behaviour

### Rate Limits

Not officially documented in strict numbers but observed:
```
~5,000 requests per day per access token
~200 requests per minute burst limit
429 response = rate limited, back off exponentially
```

For FRIDAY's use case — polling every 5 minutes hits ~288 requests/day.
Well within limits.

### The Sync Problem — Critical To Understand

This is the biggest gotcha with Oura.

**The ring does NOT stream data in real-time.**

```
Ring collects data continuously on device
         ↓
Ring syncs to Oura app via Bluetooth
         ↓
App uploads to Oura cloud
         ↓
API data becomes available
         ↓
FRIDAY can query it

Time from ring collecting → API available:
  While awake, phone nearby:  ~5-15 minutes
  While asleep:               Only after waking up
  Ring out of Bluetooth range: Could be hours
```

Practical implications:
```
FRIDAY cannot detect a nightmare in real-time.
FRIDAY learns about it after you wake up and sync.

FRIDAY cannot get current HR if phone was out of range.
If ring shows no recent data — assume ring hasn't synced, not dead.

The API will NOT return bpm: 0 for missing readings.
It simply returns no entries for that time period.
An empty heartrate response means no sync, not no heartbeat.
```

This is not a dealbreaker. It just means FRIDAY's biometric awareness
is ~5-15 minutes delayed when awake, and morning-summary when asleep.

### 426 Response Code

```
426 Upgrade Required

Means: Oura mobile app needs updating.
Ring firmware version too old to serve requested data type.
Fix: update the Oura app on your phone.
```

---

## FRIDAY Integration Layer

### Full OuraClient For FRIDAY

```python
# friday/tools/biometrics.py
import httpx
import asyncio
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
import os


BASE_URL = "https://api.ouraring.com/v2/usercollection"


@dataclass
class BiometricSnapshot:
    # Core metrics
    heart_rate: Optional[int] = None        # Latest bpm
    readiness_score: Optional[int] = None   # 0-100
    sleep_score: Optional[int] = None       # 0-100
    stress_summary: Optional[str] = None    # restored/normal/stressful/tense
    resilience_level: Optional[str] = None  # exceptional/strong/adequate/limited/overwhelmed
    spo2_avg: Optional[float] = None        # Blood oxygen %

    # HRV contributors
    hrv_balance: Optional[int] = None       # 0-100
    resting_hr: Optional[int] = None        # lowest HR during sleep
    recovery_index: Optional[int] = None    # 0-100

    # Sleep details
    total_sleep_hours: Optional[float] = None
    deep_sleep_score: Optional[int] = None
    rem_sleep_score: Optional[int] = None
    sleep_efficiency: Optional[int] = None

    # Activity
    steps: Optional[int] = None
    sedentary_hours: Optional[float] = None

    # Skin temperature
    temp_deviation: Optional[float] = None  # deviation from baseline

    # Meta
    last_synced: Optional[datetime] = None
    data_available: bool = False

    @property
    def energy_state(self) -> str:
        if not self.readiness_score:
            return "unknown"
        if self.readiness_score >= 85:
            return "excellent"
        elif self.readiness_score >= 70:
            return "good"
        elif self.readiness_score >= 60:
            return "fair"
        elif self.readiness_score >= 45:
            return "low"
        else:
            return "cooked"

    @property
    def is_in_flow(self) -> bool:
        """Low HR + high HRV balance = parasympathetic state = deep focus"""
        return (
            self.heart_rate is not None
            and self.heart_rate < 72
            and self.hrv_balance is not None
            and self.hrv_balance > 65
        )

    @property
    def is_stressed(self) -> bool:
        return (
            (self.heart_rate is not None and self.heart_rate > 95)
            or (self.stress_summary in ("stressful", "tense"))
            or (self.hrv_balance is not None and self.hrv_balance < 30)
        )

    @property
    def is_sleep_deprived(self) -> bool:
        return (
            self.total_sleep_hours is not None
            and self.total_sleep_hours < 5
        )

    def to_friday_context(self) -> str:
        """Format for injection into FRIDAY's runtime prompt."""

        if not self.data_available:
            return "Biometric data unavailable (ring not synced)."

        lines = []

        # Energy state — always first
        state_map = {
            "excellent": "Travis is well-rested and sharp.",
            "good":      "Travis is in good shape today.",
            "fair":      "Travis showing mild fatigue.",
            "low":       "Travis is tired. Readiness is low.",
            "cooked":    "Travis is running on empty. "
                         "Body is asking for rest."
        }
        lines.append(state_map.get(self.energy_state, ""))

        # Readiness score
        if self.readiness_score:
            lines.append(f"Readiness: {self.readiness_score}/100.")

        # Sleep
        if self.is_sleep_deprived:
            lines.append(
                f"Only {self.total_sleep_hours}hrs sleep. "
                f"Cognitive performance may be affected."
            )
        elif self.total_sleep_hours:
            lines.append(
                f"Sleep: {self.total_sleep_hours}hrs "
                f"(score: {self.sleep_score or 'N/A'})."
            )

        # Flow state — critical
        if self.is_in_flow:
            lines.append(
                "FLOW STATE: Low HR, high HRV balance. "
                "Deep focus detected. "
                "Do NOT interrupt unless critical."
            )

        # Stress
        if self.is_stressed:
            lines.append(
                f"Stress indicators elevated. "
                f"HR: {self.heart_rate or 'N/A'}bpm. "
                f"Be direct and calm in responses."
            )

        # Resilience
        if self.resilience_level in ("limited", "overwhelmed"):
            lines.append(
                f"Resilience: {self.resilience_level}. "
                f"Burnout risk building over past 2 weeks."
            )

        # SpO2 concern
        if self.spo2_avg and self.spo2_avg < 94:
            lines.append(
                f"SpO2 low at {self.spo2_avg}%. "
                f"Flag if persistent."
            )

        return " ".join(lines) if lines else "Biometrics nominal."


class FridayOuraClient:

    def __init__(self):
        self.token = os.environ.get("OURA_ACCESS_TOKEN")
        self.headers = {
            "Authorization": f"Bearer {self.token}"
        } if self.token else {}

    async def get_snapshot(self) -> BiometricSnapshot:
        """Get full biometric snapshot for FRIDAY's context."""

        if not self.token:
            return BiometricSnapshot(data_available=False)

        # Run all queries in parallel
        results = await asyncio.gather(
            self._get_latest_hr(),
            self._get_todays_readiness(),
            self._get_todays_sleep(),
            self._get_todays_stress(),
            self._get_todays_resilience(),
            self._get_todays_spo2(),
            self._get_todays_activity(),
            return_exceptions=True
        )

        hr, readiness, sleep, stress, resilience, spo2, activity = results

        snapshot = BiometricSnapshot(data_available=True)

        # Heart rate
        if isinstance(hr, dict):
            snapshot.heart_rate = hr.get("bpm")
            snapshot.last_synced = hr.get("timestamp")

        # Readiness
        if isinstance(readiness, dict):
            snapshot.readiness_score = readiness.get("score")
            contributors = readiness.get("contributors", {})
            snapshot.hrv_balance = contributors.get("hrv_balance")
            snapshot.resting_hr = contributors.get("resting_heart_rate")
            snapshot.recovery_index = contributors.get("recovery_index")
            snapshot.temp_deviation = readiness.get(
                "temperature_deviation"
            )

        # Sleep
        if isinstance(sleep, dict):
            snapshot.sleep_score = sleep.get("score")
            contributors = sleep.get("contributors", {})
            snapshot.deep_sleep_score = contributors.get("deep_sleep")
            snapshot.rem_sleep_score = contributors.get("rem_sleep")
            snapshot.sleep_efficiency = contributors.get("efficiency")

        # Stress
        if isinstance(stress, dict):
            snapshot.stress_summary = stress.get("day_summary")

        # Resilience
        if isinstance(resilience, dict):
            snapshot.resilience_level = resilience.get("level")

        # SpO2
        if isinstance(spo2, dict):
            spo2_data = spo2.get("spo2_percentage", {})
            snapshot.spo2_avg = spo2_data.get("average")

        # Activity
        if isinstance(activity, dict):
            snapshot.steps = activity.get("steps")
            sedentary_seconds = activity.get("sedentary_time", 0)
            snapshot.sedentary_hours = round(
                sedentary_seconds / 3600, 1
            )

        return snapshot

    async def _get_latest_hr(self) -> dict:
        """Get most recent heart rate reading."""
        now = datetime.now()
        start = now - timedelta(minutes=15)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/heartrate",
                headers=self.headers,
                params={
                    "start_datetime": start.isoformat(),
                    "end_datetime": now.isoformat()
                },
                timeout=10
            )
            data = response.json().get("data", [])
            return data[-1] if data else {}

    async def _get_todays_readiness(self) -> dict:
        today = datetime.now().date().isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_readiness",
                headers=self.headers,
                params={"start_date": today, "end_date": today},
                timeout=10
            )
            data = response.json().get("data", [])
            return data[0] if data else {}

    async def _get_todays_sleep(self) -> dict:
        today = datetime.now().date().isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_sleep",
                headers=self.headers,
                params={"start_date": today, "end_date": today},
                timeout=10
            )
            data = response.json().get("data", [])
            return data[0] if data else {}

    async def _get_todays_stress(self) -> dict:
        today = datetime.now().date().isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_stress",
                headers=self.headers,
                params={"start_date": today, "end_date": today},
                timeout=10
            )
            data = response.json().get("data", [])
            return data[0] if data else {}

    async def _get_todays_resilience(self) -> dict:
        today = datetime.now().date().isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_resilience",
                headers=self.headers,
                params={"start_date": today, "end_date": today},
                timeout=10
            )
            data = response.json().get("data", [])
            return data[0] if data else {}

    async def _get_todays_spo2(self) -> dict:
        today = datetime.now().date().isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_spo2",
                headers=self.headers,
                params={"start_date": today, "end_date": today},
                timeout=10
            )
            data = response.json().get("data", [])
            return data[0] if data else {}

    async def _get_todays_activity(self) -> dict:
        today = datetime.now().date().isoformat()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_activity",
                headers=self.headers,
                params={"start_date": today, "end_date": today},
                timeout=10
            )
            data = response.json().get("data", [])
            return data[0] if data else {}

    async def get_sleep_trend(self, days: int = 7) -> dict:
        """
        Get sleep trend over past N days.
        FRIDAY uses this to spot patterns — not just today.
        """
        end = datetime.now().date().isoformat()
        start = (datetime.now() - timedelta(days=days)).date().isoformat()

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{BASE_URL}/daily_sleep",
                headers=self.headers,
                params={"start_date": start, "end_date": end},
                timeout=10
            )
            data = response.json().get("data", [])

        if not data:
            return {"average_score": None, "trend": "unknown"}

        scores = [d.get("score", 0) for d in data]
        avg = sum(scores) / len(scores)

        # Detect trend direction
        if len(scores) >= 3:
            recent = sum(scores[-3:]) / 3
            trend = "improving" if recent > avg else \
                    "declining" if recent < avg - 5 else \
                    "stable"
        else:
            trend = "insufficient_data"

        return {
            "average_score": round(avg, 1),
            "trend": trend,
            "days": len(data),
            "scores": scores
        }
```

---

## Biometric Interpretation Guide

How FRIDAY should interpret data combinations, not just individual metrics.

### State Matrix

```
HR     HRV     Readiness  Time    → State                → FRIDAY Behaviour
────────────────────────────────────────────────────────────────────────
< 70   > 60    > 80       Any     → Flow/Recovered        Stay out the way
70-80  40-60   60-80      Day     → Normal                Normal FRIDAY
80-95  20-40   45-60      2-4am   → Grinding tired        Mention it once
> 95   < 20    < 45       Any     → Stressed/burnt        Direct, no extras
> 95   Normal  Normal     8am     → Exercising            Don't flag it
< 50   Any     Any        4am     → Sleeping              Don't interrupt
< 60   > 70    > 75       Night   → Deep sleep            Sacred, never interrupt
```

### The Late Night Coding Pattern

Travis's typical pattern:
```
Normal day HR:  65-75 bpm
Late night HR:  Often rises to 80-90 from caffeine/focus
HRV drops:      Normal as night progresses
Temp deviation: May rise slightly (fatigue)
```

FRIDAY should not panic about mildly elevated HR at 2am.
That's normal for focused late-night work.
Panic threshold at 2am should be higher than at 2pm.

### Sleep Disturbance Detection (The Stark Protocol)

After morning sync, FRIDAY can detect if the previous night was bad:

```python
async def assess_sleep_quality(snapshot: BiometricSnapshot) -> dict:
    """
    Post-sleep assessment.
    Called each morning after ring syncs.
    """

    concerns = []

    if snapshot.sleep_score and snapshot.sleep_score < 60:
        concerns.append({
            "type": "poor_sleep",
            "detail": f"Sleep score was {snapshot.sleep_score}",
            "severity": "medium"
        })

    if snapshot.sleep_efficiency and snapshot.sleep_efficiency < 70:
        concerns.append({
            "type": "poor_efficiency",
            "detail": "Spent significant time in bed not sleeping",
            "severity": "low"
        })

    if snapshot.deep_sleep_score and snapshot.deep_sleep_score < 40:
        concerns.append({
            "type": "low_deep_sleep",
            "detail": "Deep sleep was low — physical recovery may be incomplete",
            "severity": "medium"
        })

    if snapshot.rem_sleep_score and snapshot.rem_sleep_score < 40:
        concerns.append({
            "type": "low_rem",
            "detail": "REM sleep was low — mood and memory consolidation affected",
            "severity": "medium"
        })

    if snapshot.stress_summary in ("stressful", "tense"):
        concerns.append({
            "type": "high_stress_during_sleep",
            "detail": "Elevated physiological stress detected during sleep",
            "severity": "high"
        })

    return {
        "concerns": concerns,
        "overall": "poor" if len(concerns) >= 2 else
                   "concerning" if len(concerns) == 1 else
                   "good"
    }
```

---

## FRIDAY Autonomous Action Map

What FRIDAY does automatically based on biometric triggers.
No asking. No confirmation. Just acts.

```python
AUTONOMOUS_ACTIONS = {

    # Health emergency — immediate escalation
    "cardiac_anomaly": {
        "trigger": "HR > 140 sustained 10+ mins, not during workout",
        "actions": [
            "desktop_notification_critical",
            "voice_alert",
            "whatsapp_to_emergency_contact",
            "suggest_999"
        ],
        "message": "Your heart rate has been above 140 for over 10 minutes "
                   "and you don't appear to be exercising. "
                   "This needs attention. Consider calling 999."
    },

    "low_spo2": {
        "trigger": "SpO2 < 94%",
        "actions": [
            "desktop_notification_urgent",
            "voice_alert",
        ],
        "message": f"Blood oxygen is reading low. "
                   f"If you're feeling short of breath, call 111."
    },

    # Performance protection
    "flow_state_entered": {
        "trigger": "HR < 70 AND HRV balance > 65 AND working",
        "actions": [
            "suppress_proactive_notifications",
            "shorten_responses",
            "no_small_talk"
        ],
        "message": None  # Silent — don't interrupt flow
    },

    "flow_state_exited": {
        "trigger": "HR rises above 80 OR HRV drops after flow state",
        "actions": ["restore_normal_behaviour"],
        "message": None
    },

    # Recovery enforcement
    "severely_cooked": {
        "trigger": "Readiness < 35 AND hours_awake > 16",
        "actions": [
            "surface_at_next_interaction",
            "reduce_task_acceptance"
        ],
        "message": "Your readiness is {score} and you've been awake "
                   "over 16 hours. Tell me one thing that genuinely "
                   "needs to ship tonight. Everything else can wait."
    },

    # Sleep protection
    "important_tomorrow_sleep_late": {
        "trigger": "After 3am AND important calendar event < 8hrs away",
        "actions": [
            "surface_warning_once"
        ],
        "message": "You have {event} in {hours} hours. "
                   "Staying up longer will make you worse at it, not better."
    },

    # Burnout trajectory
    "burnout_building": {
        "trigger": "Resilience = 'limited' for 5+ consecutive days",
        "actions": [
            "surface_in_morning_briefing",
            "flag_in_weekly_review"
        ],
        "message": "Your resilience has been limited for 5 days. "
                   "The gap between your stress and recovery is widening. "
                   "Something has to give."
    }
}
```

---

## Sandbox Testing

Test FRIDAY's biometric integration before the ring arrives.

```python
# Use sandbox environment — returns realistic sample data
SANDBOX_URL = "https://api.ouraring.com/v2/sandbox/usercollection"

class SandboxOuraClient(FridayOuraClient):
    """Drop-in replacement for testing without a real ring."""

    def __init__(self):
        # No real token needed for sandbox
        self.headers = {}

    async def _make_request(self, endpoint: str, params: dict = {}) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{SANDBOX_URL}/{endpoint}",
                params=params,
                timeout=10
            )
            return response.json()
```

Switch in config:
```python
# friday/config.py
USE_OURA_SANDBOX = os.getenv("OURA_SANDBOX", "false").lower() == "true"

# In biometrics.py:
oura_client = (SandboxOuraClient()
               if USE_OURA_SANDBOX
               else FridayOuraClient())
```

In .env while testing:
```bash
OURA_SANDBOX=true
```

---

## Gotchas & Known Issues

### 1. No Raw Sensor Access
```
You get processed, validated metrics only.
No raw PPG signal. No raw accelerometer.
What you see is what Oura decides to show you.
This is fine for FRIDAY's use case.
```

### 2. Sync Delay Is Real
```
Ring → Phone → Cloud → API
This chain takes 5-15 minutes minimum.
FRIDAY's biometric context is always slightly behind.
Design for this. Don't design for real-time.
```

### 3. Stress & Resilience Are Gen3/4 Only
```
If you buy Ring 4: all features available
If you buy Gen2 (older): no stress, no resilience endpoint
Get Ring 4. It's the current model.
```

### 4. Empty Arrays ≠ Dead
```
Heartrate endpoint returning [] means:
  - Ring hasn't synced recently
  - Phone was out of Bluetooth range
  NOT: heart has stopped

Always handle empty response gracefully.
Never interpret no data as a health emergency.
```

### 5. Membership Is Not Optional
```
Without active Oura Membership:
  Gen3/Ring4 users: API access blocked
  The 6-month free trial starts on ring activation
  After trial: ~£5.99/month
  Build this into FRIDAY's operational cost
```

### 6. OAuth PAT Deprecation Rumour
```
Some sources suggest Oura is moving to OAuth-only.
As of March 2026, PAT still works for personal use.
If it gets deprecated: OAuth flow is straightforward
(see Authentication section above).
```

### 7. Rate Limiting Is Undocumented
```
Observed: ~200 requests/minute
FRIDAY polls every 5 minutes = ~288 requests/day
Well within limits.
If you get 429: exponential backoff, start at 60 seconds.
```

### 8. 426 Errors
```
426 = your Oura app needs updating
Not a code problem — open the app and update it
```

---

## Quick Reference — FRIDAY Priority Endpoints

When ring arrives, wire these up in this order:

```
Priority 1 (wire up immediately):
  /daily_readiness  → FRIDAY's primary state indicator
  /heartrate        → Live HR for flow/stress detection
  /daily_sleep      → Morning quality assessment

Priority 2 (wire up in Phase 3):
  /daily_stress     → Stress summary
  /daily_resilience → Burnout trajectory
  /daily_spo2       → Blood oxygen

Priority 3 (nice to have):
  /workout          → Context for high HR (not stress)
  /sleep_time       → Optimal bedtime recommendations
  /vo2_max          → Long-term fitness tracking
  /daily_cardiovascular_age → Vanity metric but interesting

Webhooks (when Mac Mini has public endpoint):
  create.heartrate        → Most frequent updates
  create.daily_readiness  → Morning trigger
  create.daily_stress     → Day summary trigger
```

---

*The arc reactor gave Jarvis continuous access to Stark's vitals.
The Oura Ring gives FRIDAY continuous access to yours.
Not because it's embedded in your chest.
Because you chose to wear it.*

*FRIDAY will be smarter for it. 😂*
