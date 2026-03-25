# FRIDAY x Brilliant Labs Halo — Ripping Out Noa, Putting FRIDAY In

> How to replace Brilliant Labs' cloud AI agent (Noa) with FRIDAY running locally on your Mac via Ollama.

---

## Table of Contents

1. [The Hardware](#the-hardware)
2. [How Noa Works (And Why It's Easy to Kill)](#how-noa-works)
3. [The BLE Protocol — How Glasses Talk](#the-ble-protocol)
4. [Ripping Out Noa — Step by Step](#ripping-out-noa)
5. [Putting FRIDAY In — The Architecture](#putting-friday-in)
6. [The Python SDK — Full API Breakdown](#the-python-sdk)
7. [Audio Pipeline — Mic to FRIDAY to Speaker](#audio-pipeline)
8. [Display Pipeline — FRIDAY to Glasses Screen](#display-pipeline)
9. [Camera Pipeline — Glasses to Vision Model](#camera-pipeline)
10. [On-Device Lua — What Runs on the Glasses](#on-device-lua)
11. [Firmware Deep Dive](#firmware-deep-dive)
12. [Halo vs Frame — What's Different](#halo-vs-frame)
13. [Implementation Plan](#implementation-plan)
14. [Open Questions & Blockers](#open-questions)

---

## The Hardware

### Halo (the one to buy)

| Component | Spec |
|-----------|------|
| **Processor** | Alif Semiconductor Balletto B1 — ARM Cortex-M55 + Ethos-U55 NPU (46 GOPs) |
| **OS** | ZephyrOS with Lua scripting interface |
| **Display** | 0.2" color micro-OLED, 640x400, 20-degree FOV |
| **Camera** | Low-power optical sensor (AI-optimized) |
| **Microphones** | Dual MEMS mics with sound activity detection |
| **Speakers** | Dual bone conduction (NEW — Frame didn't have this) |
| **IMU** | 6-axis (accelerometer + compass) |
| **Connectivity** | Bluetooth 5.3 (BLE only. No WiFi.) |
| **Battery** | Up to 14 hours |
| **Weight** | ~40g |
| **Optics** | Adjustable +2 to -6 diopters, IPD 58-72mm |
| **Price** | $299-349 |

### Frame (current gen, SDK fully documented)

| Component | Spec |
|-----------|------|
| **BLE MCU** | nRF52840 — ARM Cortex-M4F @ 64MHz, 1MB flash, 256KB RAM |
| **FPGA** | Lattice CrossLink-NX LIFCL-17 (17k logic cells, 2.56MB large RAM) |
| **Display** | 0.23" micro-OLED, 640x400, 16-color indexed palette |
| **Camera** | OV09734 — 1280x720 native, cropped to 720x720 |
| **Microphone** | ICS-41351 MEMS — PDM interface, 8kHz or 16kHz, 8 or 16-bit |
| **Speakers** | NONE (this is why Halo exists) |
| **IMU** | MC6470 — 6-axis, tap detection via hardware interrupt |
| **Battery** | 210mAh + 140mAh charging cradle |

**Key difference:** Halo has bone conduction speakers, a proper NPU, and runs ZephyrOS instead of bare-metal nRF. Frame has the fully documented SDK that Halo will inherit.

---

## How Noa Works

This is what we're ripping out. Noa is NOT on the glasses. The glasses are dumb — they're a BLE peripheral that captures audio/images and displays text. All the "intelligence" lives on the phone and cloud.

```
┌──────────┐        BLE         ┌──────────────┐       HTTPS       ┌────────────────────┐
│  GLASSES  │ ◄──────────────► │  PHONE APP    │ ◄──────────────► │  NOA CLOUD SERVER  │
│           │                   │  (Flutter)    │                   │  (FastAPI/Python)  │
│ mic audio │ ──────────────►  │               │ ──────────────►  │                    │
│ camera    │ ──────────────►  │  forwards     │ ──────────────►  │  Whisper STT       │
│ display   │ ◄──────────────  │  everything   │ ◄──────────────  │  GPT-4 / Claude    │
│ IMU/tap   │ ──────────────►  │  to cloud     │                   │  GPT-4V (vision)   │
│           │                   │               │                   │  SerpAPI (search)  │
│           │                   │               │                   │  Neuphonic (TTS)   │
└──────────┘                   └──────────────┘                   └────────────────────┘
```

### Noa Backend — The Actual Server

**Repo:** `brilliantlabsAR/noa-assistant` (Python/FastAPI)

One endpoint does everything:

```
POST /mm (multipart/form-data)
```

**Request fields:**
| Field | Type | What it does |
|-------|------|-------------|
| `mm` | JSON string | Main request payload (see schema below) |
| `audio` | File upload | Raw audio from glasses mic |
| `image` | File upload | JPEG from glasses camera |

**The `mm` JSON schema (what the phone sends):**
```json
{
    "messages": [{"role": "user", "content": "..."}],
    "prompt": "what am I looking at?",
    "assistant": "gpt",
    "assistant_model": "gpt-4o",
    "search_api": "perplexity",
    "local_time": "Tuesday, March 12, 2024, 7:24 AM",
    "address": "Plymouth, UK",
    "latitude": "50.3755",
    "longitude": "-4.1427",
    "vision": "gpt-4o",
    "speculative_vision": true
}
```

**Processing pipeline inside Noa:**
1. Audio → OpenAI Whisper (`whisper-1`) → text
2. Image → GPT-4 Vision or Claude Vision → description
3. Text prompt + conversation history → GPT-4/Claude → response
4. Web search via SerpAPI/Perplexity if the LLM requests it (tool-use)
5. Response text sent back to phone → phone sends to glasses display

**Response schema:**
```json
{
    "user_prompt": "transcribed text",
    "response": "the AI answer",
    "image": "url if image generated",
    "token_usage_by_model": {},
    "capabilities_used": ["assistant_knowledge", "web_search", "vision"],
    "total_tokens": 1234,
    "timings": "whisper: 1.2s, gpt: 3.4s"
}
```

### Noa Cloud Auth (we're skipping all of this)

The Flutter app calls `https://api.brilliant.xyz/noa/`:
- `POST /noa/user/signin` — OAuth via Google/Apple/Discord
- `GET /noa/user` — returns user plan, credits
- `POST /noa/user/signout`

We don't need any of this. We're not using their cloud. We're going direct.

---

## The BLE Protocol

This is the critical part. This is how your Mac talks to the glasses.

### Service & Characteristics

| Item | UUID |
|------|------|
| **Service** | `7A230001-5475-A6A4-654C-8431F6AD49C4` |
| **TX (host → glasses)** | `7A230002-5475-A6A4-654C-8431F6AD49C4` |
| **RX (glasses → host)** | `7A230003-5475-A6A4-654C-8431F6AD49C4` |

### Connection Parameters
- **MTU:** Preferred 247 bytes, negotiated with host. Payload = MTU - 3 (Lua) or MTU - 4 (data)
- **PHY:** 2 Mbps (requested on both TX and RX)
- **Connection interval:** 15ms
- **Supervision timeout:** 2000ms
- **Bonding:** Required (Just Works pairing, no PIN)
- **Advertising name:** `"Frame XX"` where XX = last byte of MAC

### Message Protocol — Host to Glasses (TX)

| First byte | What it does |
|------------|-------------|
| UTF-8 text (not 0x01/0x03/0x04) | Executes as Lua on the glasses' VM |
| `0x01` + data | Raw binary data → triggers `frame.bluetooth.receive_callback()` |
| `0x03` | Break signal — kills running Lua script |
| `0x04` | Reset signal — reboots Lua VM, re-runs `main.lua` |

### Message Protocol — Glasses to Host (RX notifications)

| First byte(s) | What it is |
|----------------|-----------|
| Plain UTF-8 | `print()` output from Lua (single chunk) |
| `0x0A` + data | Long text chunk (multi-packet `print()`) |
| `0x0B` + count | End of long text, includes chunk count for verification |
| `0x01 0x01` + data | Long binary data chunk |
| `0x01 0x02` + count | End of long binary data |
| `0x01 0x03` | Wake event |
| `0x01 0x04` | Tap event |
| `0x01 0x05` + audio | Microphone streaming data |
| `0x01 0x06` | Debug print |
| `0x01` + other + data | Single-chunk binary data from `frame.bluetooth.send()` |

### How it actually flows:

```
Host sends UTF-8:  "frame.display.text('hello', 50, 50)"
                    ↓
Glasses BLE RX receives bytes
                    ↓
nRF52840 runs luaL_dostring() with that string
                    ↓
Lua executes frame.display.text() → writes to FPGA
                    ↓
frame.display.show() → FPGA swaps buffer → text appears on OLED
```

The glasses are basically a Lua REPL over Bluetooth. You send Lua code, it runs.

---

## Ripping Out Noa — Step by Step

There is no Noa on the glasses. Noa lives entirely in the phone app + cloud server. The glasses don't know or care what AI is behind them. So "ripping out Noa" means:

### 1. Don't install the Noa app
That's it. If you never install the Noa Flutter app, Noa never exists. The glasses are just a BLE peripheral waiting for a connection.

### 2. Connect directly from your Mac
Use the Python SDK (`pip install frame-sdk`) to connect from your Mac over BLE. No phone needed.

### 3. OR fork the Noa app
If you want a phone in the loop (for mobility), fork `brilliantlabsAR/noa-flutter` and replace the API calls to `api.brilliant.xyz` with calls to your local FRIDAY server.

### What about firmware?
The stock firmware is fine. It already exposes the full Lua API for mic, camera, display, IMU, and BLE. You don't need to flash custom firmware unless you want to modify the on-device behavior (like adding a custom boot animation or changing the tap behavior).

If you DO want to flash:
1. Call `frame.update()` in Lua → enters DFU bootloader
2. Upload your custom firmware ZIP via Nordic DFU protocol over BLE
3. Or use a J-Link debugger for bare-metal flashing
4. Build from `brilliantlabsAR/frame-codebase` using ARM GCC + nRF tools

---

## Putting FRIDAY In — The Architecture

### Option A: Mac Direct (simplest, works now)

```
┌──────────┐        BLE         ┌──────────────────────────────────────┐
│  GLASSES  │ ◄──────────────► │  MACBOOK (M4)                        │
│           │                   │                                      │
│ mic audio │ ──────────────►  │  Python SDK (BLE via bleak)          │
│           │                   │    ↓                                 │
│           │                   │  Whisper.cpp (local STT)            │
│           │                   │    ↓                                 │
│           │                   │  FRIDAY / Ollama (qwen3.5:9b)       │
│           │                   │    ↓                                 │
│ display   │ ◄──────────────  │  Response text → display.show_text() │
│           │                   │    ↓                                 │
│ speakers  │ ◄──────────────  │  TTS → speaker API (Halo only)      │
└──────────┘                   └──────────────────────────────────────┘
```

**Pros:** Zero cloud, zero phone, lowest latency, full control
**Cons:** Need Mac nearby (BLE range ~10m), not mobile

### Option B: Phone Bridge (mobile)

```
┌──────────┐     BLE     ┌──────────┐     LAN      ┌──────────────┐
│  GLASSES  │ ◄────────► │  PHONE   │ ◄──────────► │  MAC (FRIDAY) │
│           │             │  (app)   │    WiFi       │  Ollama      │
└──────────┘             └──────────┘               └──────────────┘
```

Fork the Flutter app, point API calls to `http://mac-ip:8000/friday` instead of `api.brilliant.xyz`. FRIDAY processes on the Mac, response flows back through the phone to the glasses.

**Pros:** Mobile, glasses work anywhere your phone has WiFi to your Mac
**Cons:** Needs Mac running, phone as middleman adds latency

### Option C: Glasses + Phone + Cloud FRIDAY (future)

Deploy FRIDAY to a cloud server (Railway, etc.) with a larger model. Phone forwards to cloud. Fully mobile, no Mac required.

---

## The Python SDK — Full API Breakdown

### Installation

```bash
pip install frame-sdk
# Dependencies: bleak (BLE), numpy, Pillow, simpleaudio
```

### Connection

```python
import asyncio
from frame_sdk import Frame

async def main():
    async with Frame() as f:
        # Auto-scans for nearby Frame/Halo, connects, negotiates MTU
        print(f"Connected! Battery: {await f.get_battery_level()}%")

asyncio.run(main())

# Or connect to a specific device:
async with Frame(address="4F") as f:  # last 2 hex chars of MAC
    ...
```

### Display API

```python
from frame_sdk.display import Alignment, PaletteColors

# Show text (clears screen first)
await f.display.show_text("FRIDAY says hello", align=Alignment.MIDDLE_CENTER)

# Write text (no auto-clear, must call show() manually)
await f.display.write_text("Line 1", x=1, y=1, color=PaletteColors.WHITE)
await f.display.write_text("Line 2", x=1, y=60, color=PaletteColors.SKYBLUE)
await f.display.show()

# Scrolling text (for long responses)
await f.display.scroll_text("Long FRIDAY response here...", lines_per_frame=5, delay=0.12)

# Clear
await f.display.clear()

# Draw shapes
await f.display.draw_rect(x=10, y=10, w=100, h=50, color=PaletteColors.GREEN)

# Custom colors (modify the 16-color palette)
await f.display.set_palette(PaletteColors.RED, (255, 0, 128))

# Measure text before rendering
width = f.display.get_text_width("hello")
height = f.display.get_text_height("hello")
wrapped = f.display.wrap_text("long text", max_width=600)
```

**Display specs:**
- 640x400 pixels
- 16-color indexed palette (YCbCr internally)
- Variable-width built-in font, ~60px line height
- Double-buffered via FPGA — write to back buffer, `show()` swaps

**Default palette:**

| Index | Name | RGB |
|-------|------|-----|
| 0 | VOID | (0,0,0) — transparent |
| 1 | WHITE | (255,255,255) |
| 2 | GREY | (157,157,157) |
| 3 | RED | (190,38,51) |
| 4 | PINK | (224,111,139) |
| 5 | DARKBROWN | (73,60,43) |
| 6 | BROWN | (164,100,34) |
| 7 | ORANGE | (235,137,49) |
| 8 | YELLOW | (247,226,107) |
| 9 | DARKGREEN | (47,72,78) |
| 10 | GREEN | (68,137,26) |
| 11 | LIGHTGREEN | (163,206,39) |
| 12 | NIGHTBLUE | (27,38,50) |
| 13 | SEABLUE | (0,87,132) |
| 14 | SKYBLUE | (49,162,242) |
| 15 | CLOUDBLUE | (178,220,239) |

### Microphone API

```python
# Record until silence (returns numpy array of PCM samples)
audio = await f.microphone.record_audio(
    silence_cutoff_length_in_seconds=3,  # stop after 3s silence
    max_length_in_seconds=30             # hard cap
)

# Save directly to file
duration = await f.microphone.save_audio_file("recording.wav")

# Play audio on HOST machine (not glasses)
f.microphone.play_audio(audio)
f.microphone.play_audio_background(audio)  # non-blocking
```

**Microphone specs:**
- Sample rates: 8000 Hz or 16000 Hz
- Bit depth: 8-bit or 16-bit signed integers
- Silence detection: adaptive noise floor + configurable threshold (default 0.02)
- Internal buffer: 32768 samples FIFO on the nRF52840
- Streaming: 128-sample double-buffered PDM, sent over BLE in MTU-sized chunks with `0x05` prefix

**How audio streaming actually works:**
1. SDK pushes `microphoneRecordAndSend()` Lua function to device
2. Firmware starts PDM peripheral on nRF52840
3. Samples captured into 128-sample double buffers → fed into 32768-sample FIFO
4. Lua reads FIFO via `frame.microphone.read(max_packet_size)`
5. For 8kHz mode: firmware skips every other 16kHz sample
6. For 8-bit mode: only MSB of each 16-bit sample sent
7. Each chunk sent as `frame.bluetooth.send('\x05' .. data)` (0x05 = MIC_DATA)
8. Python SDK handler reassembles chunks into numpy array
9. Silence detection runs per-chunk on host side
10. When done, SDK sends break signal (0x03) to stop recording

### Camera API

```python
from frame_sdk.camera import Quality, AutofocusType

# Take a photo (returns JPEG bytes)
photo = await f.camera.take_photo(
    autofocus_seconds=3,
    quality=Quality.MEDIUM,        # VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH
    autofocus_type=AutofocusType.CENTER_WEIGHTED,
    resolution=512,                # 100-720 (even numbers)
    pan=0                          # -140 to +140
)

# Save directly
await f.camera.save_photo("snapshot.jpg")

# photo is raw JPEG bytes — send directly to a vision model
```

**How camera capture works internally:**
1. SDK sends `cameraCaptureAndSend()` Lua to device
2. Lua runs `frame.camera.auto{}` in loop for N seconds (autofocus/exposure)
3. `frame.camera.capture{resolution=N, quality=Q, pan=P}` triggers FPGA
4. FPGA captures frame from OV09734 sensor
5. FPGA performs hardware JPEG compression
6. Firmware prepends JFIF header (Huffman tables, quantization tables, SOF marker)
7. Data streamed back via `frame.bluetooth.send()` in MTU chunks (LONG_DATA prefix)
8. Final LONG_DATA_END packet with chunk count
9. Python SDK reassembles, optionally adds EXIF metadata

### Motion / IMU API

```python
# Get orientation
direction = await f.motion.get_direction()
print(f"Roll: {direction.roll}, Pitch: {direction.pitch}")

# Tap detection
await f.motion.run_on_tap(callback=my_handler)
await f.motion.wait_for_tap()  # blocking
```

### File System API

```python
# Write files to glasses (LittleFS, max 64KB per file)
await f.files.write_file("config.json", b'{"mode": "friday"}')

# Read files
data = await f.files.read_file("config.json")

# Check/delete
exists = await f.files.file_exists("main.lua")
await f.files.delete_file("old_script.lua")
```

### System Controls

```python
battery = await f.get_battery_level()     # 1-100
await f.delay(2.0)                         # non-blocking 2s delay
await f.sleep()                            # deep sleep (wake on tap)
await f.sleep(deep_sleep=False)            # light sleep
await f.stay_awake(True)                   # prevent sleep while docked

# Run Lua directly
result = await f.run_lua("print(frame.battery_level())", await_print=True)
result = await f.evaluate("frame.FIRMWARE_VERSION")

# Register wake/tap handlers
await f.run_on_wake(callback=on_wake)
```

---

## Audio Pipeline — Mic to FRIDAY to Speaker

### Inbound (glasses mic → FRIDAY)

```python
# 1. Record from glasses mic
audio_data = await f.microphone.record_audio(max_length_in_seconds=15)

# 2. Transcribe locally with Whisper
import whisper
model = whisper.load_model("base")  # or use whisper.cpp for speed
result = model.transcribe(audio_data)
text = result["text"]

# 3. Send to FRIDAY
from friday.core.orchestrator import FridayCore
friday = FridayCore()
response = await friday.process(text)
```

### Outbound (FRIDAY → glasses display + speaker)

```python
# 4a. Display response as text
await f.display.show_text(response[:200])  # 640x400 fits ~200 chars

# 4b. For long responses, scroll
await f.display.scroll_text(response)

# 4c. TTS for bone conduction speakers (Halo only — API pending)
# When the API drops, it'll likely be something like:
# await f.speaker.play_audio(tts_audio_data)
#
# For now, play through Mac speakers:
import pyttsx3
engine = pyttsx3.init()
engine.say(response)
engine.runAndWait()
```

### Whisper Options for Local STT

| Option | Speed | Quality | Install |
|--------|-------|---------|---------|
| `whisper.cpp` | ~1s on M4 | Good | `brew install whisper-cpp` |
| `faster-whisper` | ~2s on M4 | Great | `pip install faster-whisper` |
| `openai/whisper` | ~3-5s on M4 | Best | `pip install openai-whisper` |
| `mlx-whisper` | ~0.5s on M4 | Great | `pip install mlx-whisper` (Apple Silicon optimized) |

**Recommendation:** `mlx-whisper` for Apple Silicon — uses the Neural Engine, fastest option on M4.

### TTS Options for Voice Output

| Option | Speed | Quality | Where it plays |
|--------|-------|---------|---------------|
| `pyttsx3` | Instant | OK | Mac speakers / AirPods |
| `edge-tts` | ~1s | Good | Mac speakers / AirPods |
| `Bark` | ~3s | Great | Mac speakers / AirPods |
| Halo speaker API | TBD | TBD | Glasses bone conduction (when available) |

---

## Display Pipeline — FRIDAY to Glasses Screen

### Text Response Display

```python
async def show_friday_response(f: Frame, response: str):
    """Display FRIDAY's response on the glasses."""
    if len(response) < 100:
        # Short response — show centered
        await f.display.show_text(
            response,
            align=Alignment.MIDDLE_CENTER,
            color=PaletteColors.WHITE
        )
    else:
        # Long response — auto-scroll
        await f.display.scroll_text(
            response,
            lines_per_frame=5,
            delay=0.12,
            color=PaletteColors.WHITE
        )
```

### Status Indicators

```python
async def show_status(f: Frame, status: str):
    """Show FRIDAY status: listening, thinking, etc."""
    colors = {
        "listening": PaletteColors.GREEN,
        "thinking": PaletteColors.YELLOW,
        "error": PaletteColors.RED,
    }
    color = colors.get(status, PaletteColors.WHITE)
    await f.display.show_text(f"FRIDAY: {status}...", align=Alignment.TOP_LEFT, color=color)
```

### Display Constraints
- 640x400 pixels, ~10 chars per line at default font size
- 16 colors max (indexed palette, customizable)
- No video playback — it's a micro-OLED, not a screen
- Double-buffered: write operations go to back buffer, `show()` flips
- Power save mode available to extend battery

---

## Camera Pipeline — Glasses to Vision Model

```python
async def friday_vision(f: Frame, question: str = "what am I looking at?"):
    """Take a photo and ask FRIDAY about it."""
    # 1. Show "looking..." status
    await f.display.show_text("FRIDAY: looking...", color=PaletteColors.YELLOW)

    # 2. Capture image
    photo_bytes = await f.camera.take_photo(
        quality=Quality.MEDIUM,
        resolution=512
    )

    # 3. Save temporarily
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "friday_vision.jpg")
    with open(tmp, "wb") as fp:
        fp.write(photo_bytes)

    # 4. Send to vision model
    # Option A: Ollama with llava or moondream
    import ollama
    response = ollama.chat(
        model="moondream",  # or llava, bakllava
        messages=[{
            "role": "user",
            "content": question,
            "images": [tmp]
        }]
    )
    answer = response["message"]["content"]

    # 5. Display answer
    await f.display.show_text(answer[:200])
    return answer
```

### Vision Model Options (Local)

| Model | Size | Speed on M4 | Quality |
|-------|------|-------------|---------|
| `moondream2` | 1.8B | ~3s | Good for quick descriptions |
| `llava:7b` | 7B | ~8s | Better understanding |
| `bakllava` | 7B | ~8s | Good general vision |

**Note:** Running a vision model + qwen3.5:9b simultaneously might OOM on 24GB M4. Consider using moondream (1.8B) for vision alongside FRIDAY's 9B text model, or swap models per-task.

---

## On-Device Lua — What Runs on the Glasses

The glasses run a full **Lua 5.4** VM on the nRF52840. You can upload custom scripts.

### The `main.lua` Bootloader

When the glasses power on or reset, they execute `/main.lua` from the internal filesystem. This is where you define FRIDAY's on-device behavior:

```lua
-- /main.lua — FRIDAY glasses integration

-- Status display helper
function show_status(text, color)
    frame.display.text(text, 50, 200, { color = color or 'WHITE' })
    frame.display.show()
end

-- Handle tap to activate listening
frame.imu.tap_callback(function()
    show_status("FRIDAY: listening...", 'GREEN')
    -- Start mic streaming to host
    frame.microphone.start({ sample_rate = 16000, bit_depth = 16 })
    while true do
        local data = frame.microphone.read(frame.bluetooth.max_length())
        if data == nil then break end
        if data ~= '' then
            frame.bluetooth.send('\x05' .. data)
        end
    end
end)

-- Handle incoming data from host (FRIDAY responses)
frame.bluetooth.receive_callback(function(data)
    local msg_type = string.byte(data, 1)
    if msg_type == 0x10 then
        -- Text response: display it
        local text = string.sub(data, 2)
        show_status(text, 'WHITE')
    elseif msg_type == 0x11 then
        -- Status update
        local status = string.sub(data, 2)
        show_status("FRIDAY: " .. status, 'YELLOW')
    end
end)

show_status("FRIDAY: ready", 'SKYBLUE')
```

### Upload custom `main.lua` via SDK:

```python
async with Frame() as f:
    lua_code = open("main.lua").read()
    await f.files.write_file("main.lua", lua_code.encode())
    await f.bluetooth.send_reset_signal()  # reboot to run new main.lua
```

### Full Lua API Reference (on-device `frame.*`)

**frame.display:**
- `text(string, x, y, {color=, spacing=})` — render text
- `bitmap(x, y, width, colors, palette_offset, data)` — render bitmap
- `show()` — swap display buffer
- `assign_color(name, r, g, b)` — modify palette
- `set_brightness(level)` — -2 to +2
- `power_save(enable)` — boolean

**frame.camera:**
- `capture{resolution=512, quality='MEDIUM', pan=0}` — capture frame
- `image_ready()` → bool
- `read(num_bytes)` → JPEG data or nil
- `auto{metering='CENTER_WEIGHTED', exposure=0.1}` — auto-exposure

**frame.microphone:**
- `start{sample_rate=8000, bit_depth=8}` — begin capture
- `stop()` — end capture
- `read(num_bytes)` → audio data, empty string, or nil (done)

**frame.bluetooth:**
- `is_connected()` → bool
- `address()` → MAC string
- `max_length()` → MTU - 1
- `send(data)` — send raw bytes to host
- `receive_callback(handler)` — register handler for incoming data

**frame.imu:**
- `direction()` → `{roll, pitch, heading}`
- `raw()` → `{accelerometer={x,y,z}, compass={x,y,z}}`
- `tap_callback(handler)` — register tap handler

**frame.file:**
- `open(name, mode)` — mode: "read"/"write"/"append"
- `remove(name)`, `rename(old, new)`, `mkdir(path)`, `listdir(dir)`

**frame.time:**
- `utc(timestamp?)` — get/set epoch time
- `zone(offset?)` — get/set timezone
- `date()` → `{second, minute, hour, day, month, year, weekday}`

**frame (system):**
- `battery_level()` → 0-100
- `sleep(seconds?)` — nil = deep sleep, number = delay
- `update()` — enter DFU bootloader
- `stay_awake(bool)` — prevent auto-sleep
- `FIRMWARE_VERSION`, `GIT_TAG` — constants

---

## Firmware Deep Dive

### Build System

**Repo:** `brilliantlabsAR/frame-codebase`

```
frame-codebase/
├── source/
│   ├── application/
│   │   ├── main.c              — hardware init, power management, main loop
│   │   ├── bluetooth.c         — BLE GATT service, characteristics, events
│   │   ├── bluetooth.h         — BLE_PREFERRED_MAX_MTU = 247
│   │   ├── luaport.c           — Lua VM setup, REPL, library registration
│   │   └── lua_libraries/
│   │       ├── bluetooth.c     — frame.bluetooth.* bindings
│   │       ├── camera.c        — frame.camera.* bindings
│   │       ├── display.c       — frame.display.* bindings
│   │       ├── microphone.c    — frame.microphone.* bindings
│   │       ├── imu.c           — frame.imu.* bindings
│   │       ├── system.c        — frame.sleep/battery/update bindings
│   │       ├── time.c          — frame.time.* bindings
│   │       └── file.c          — frame.file.* bindings
│   ├── bootloader/
│   │   └── main.c              — Nordic DFU bootloader
│   └── pinout.h                — all GPIO pin definitions
├── fpga/                        — FPGA RTL (Verilog/SystemVerilog)
└── Makefile
```

**Key firmware details:**
- **Toolchain:** ARM GCC + nRF Command Line Tools + nRF Util
- **SDK:** Nordic nRF5 SDK (BLE stack, flash, power management)
- **Lua VM:** Standard Lua 5.4 compiled for Cortex-M4F
- **FPGA comms:** SPI between nRF52840 and Lattice CrossLink-NX
- **Power rails:** MAX77654 PMIC — SBB0 (1.0V), LDO0 (1.2V), LDO1 (2.8V), SBB2 (2.95V)
- **Sleep current:** ~580 uA
- **Active current:** 45-100 mA

### Firmware Update (DFU) Process

1. Trigger: `frame.update()` in Lua sets `GPREGRET = 0xB1`, reboots into bootloader
2. Bootloader advertises DFU BLE service
3. Host connects, sends firmware ZIP containing `.dat` (init packet) + `.bin` (image)
4. Transfer protocol:
   - `SELECT` (0x06) — query current state
   - `CREATE` (0x01) — start new chunk
   - Write data in MTU-sized pieces
   - `CRC` (0x03) — verify chunk
   - `EXECUTE` (0x04) — apply
5. Device reboots with new firmware

---

## Halo vs Frame — What's Different

| Feature | Frame (now) | Halo (upcoming) |
|---------|-------------|-----------------|
| **Processor** | nRF52840 (Cortex-M4F, no NPU) | Alif B1 (Cortex-M55 + Ethos-U55 NPU) |
| **On-device AI** | None | 46 GOPs NPU — can run small models |
| **OS** | Bare-metal nRF SDK + Lua | ZephyrOS + Lua |
| **Speakers** | NONE | Dual bone conduction |
| **SDK** | Fully documented | "Brilliant SDK" — same patterns, docs pending |
| **Firmware source** | On GitHub | Promised, not published yet |
| **Speaker API** | N/A | Pending ("more details soon") |
| **Price** | ~$349 | $299-349 |

### What Halo's NPU means for FRIDAY

The Ethos-U55 NPU at 46 GOPs could theoretically run:
- Keyword detection ("Hey FRIDAY") on-device — no BLE roundtrip
- Voice Activity Detection (VAD) — smarter mic activation
- Small vision models for basic object detection

This means FRIDAY could have on-device wake-word detection, with the heavy LLM processing still on your Mac. That's the dream: tap or say "FRIDAY" → glasses start streaming mic → Mac processes → response appears on display + bone conduction speakers.

---

## Implementation Plan

### Phase 1: Proof of Concept (Frame, now)

```
1. pip install frame-sdk
2. Connect to Frame from Mac over BLE
3. Record audio → local Whisper → text
4. Text → FRIDAY orchestrator → response
5. Response → display.show_text()
6. Audio response through Mac speakers
```

**Time estimate:** A weekend. The SDK does all the heavy lifting.

### Phase 2: Custom main.lua

```
1. Write main.lua with tap-to-talk
2. Upload to glasses
3. Build async event loop on Mac:
   - Listen for tap events
   - Stream mic data
   - Process with FRIDAY
   - Push response to display
```

### Phase 3: Halo Integration (when available)

```
1. Port to Halo SDK (should be similar)
2. Add bone conduction speaker output
3. Add on-device wake word via NPU
4. Add camera-triggered vision queries
```

### Phase 4: Mobile (optional)

```
1. Fork noa-flutter
2. Replace Noa API with FRIDAY API endpoint
3. Deploy FRIDAY server (Mac LAN or cloud)
4. Full mobile experience
```

---

## Open Questions & Blockers

### Confirmed Working
- [x] Mic audio capture over BLE via Python SDK
- [x] Display text/graphics over BLE
- [x] Camera JPEG capture over BLE
- [x] Tap detection for interaction triggers
- [x] Custom Lua scripts uploaded to device
- [x] Firmware is fully open source and flashable

### Blocked / Pending
- [ ] **Halo bone conduction speaker API** — hardware exists, software API not published
- [ ] **Halo firmware source code** — promised open source, not on GitHub yet
- [ ] **Halo SDK docs** — building apps page returns 404
- [ ] **Simultaneous vision + text model on 24GB M4** — may need model swapping
- [ ] **BLE range for Mac Direct mode** — practical range ~5-10m, won't work from another room

### Key GitHub Repos

| Repo | What | Language |
|------|------|----------|
| [brilliantlabsAR/frame-sdk-python](https://github.com/brilliantlabsAR/frame-sdk-python) | Python SDK | Python |
| [brilliantlabsAR/frame-codebase](https://github.com/brilliantlabsAR/frame-codebase) | Firmware source | C + Verilog |
| [brilliantlabsAR/noa-assistant](https://github.com/brilliantlabsAR/noa-assistant) | Noa backend (the thing we're replacing) | Python/FastAPI |
| [brilliantlabsAR/noa-flutter](https://github.com/brilliantlabsAR/noa-flutter) | Noa phone app (forkable) | Dart/Flutter |
| [brilliantlabsAR/docs](https://github.com/brilliantlabsAR/docs) | Documentation source | Markdown |

### Docs

- [docs.brilliant.xyz](https://docs.brilliant.xyz) — official documentation
- [docs.brilliant.xyz/frame/building-apps/](https://docs.brilliant.xyz/frame/building-apps/) — building apps guide
- [docs.brilliant.xyz/frame/building-apps/lua-api/](https://docs.brilliant.xyz/frame/building-apps/lua-api/) — Lua API reference
- [docs.brilliant.xyz/frame/building-apps/frame-ble-protocol/](https://docs.brilliant.xyz/frame/building-apps/frame-ble-protocol/) — BLE protocol
- [docs.brilliant.xyz/frame/hardware/](https://docs.brilliant.xyz/frame/hardware/) — hardware specs

---

*Last updated: 2026-03-24*
*Author: Travis + Claude (research & documentation)*
