---
name: youtube-watcher
description: Fetch and summarize YouTube video transcripts. Use when asked to watch, summarize, or answer questions about a YouTube video.
agents: [research_agent, deep_research_agent]
---

# YouTube Watcher

When Travis sends a YouTube link or says "summarize this video", "watch this", "what's this video about":

## Flow

1. Extract the video URL from the message
2. Fetch the transcript using yt-dlp (installed at /opt/homebrew/bin/yt-dlp)
3. Summarize or answer questions based on the transcript

## How to Fetch Transcript

Run this command via the terminal/exec tool:

```bash
yt-dlp --write-auto-sub --sub-lang en --skip-download --print-json "VIDEO_URL" 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
subs = data.get('subtitles', {}).get('en') or data.get('automatic_captions', {}).get('en', [])
if subs:
    # Get the vtt/json subtitle URL
    for s in subs:
        if s.get('ext') == 'json3':
            print(s['url'])
            break
    else:
        print(subs[0]['url'])
else:
    print('NO_SUBS')
"
```

Simpler approach — just get the subtitle text directly:

```bash
yt-dlp --write-auto-sub --sub-lang en --skip-download -o "/tmp/yt_sub" "VIDEO_URL" 2>/dev/null && cat /tmp/yt_sub.en.vtt 2>/dev/null | grep -v "^$" | grep -v "^WEBVTT" | grep -v "^Kind:" | grep -v "^Language:" | grep -v "^[0-9][0-9]:" | head -200
```

## After Getting Transcript

- **"Summarize this video"** → Read transcript, give 3-5 bullet point summary
- **"What does X say about Y?"** → Search transcript for relevant sections, quote key parts
- **"Key takeaways?"** → Extract main points, actionable items
- **"Is this worth watching?"** → Quick summary + opinion on content quality

## Also Get Video Info

```bash
yt-dlp --print "%(title)s|%(uploader)s|%(duration_string)s|%(view_count)s" "VIDEO_URL" 2>/dev/null
```

Returns: title | channel | duration | views

## What NOT to Do

- Don't download the actual video file (skip-download always)
- Don't say "I can't watch videos" — you CAN via transcripts
- If no subtitles available, say so and offer to search for a text summary of the video topic instead
