# User Config — `~/Friday/user.json`

FRIDAY has **one config file** and it lives somewhere you can actually see it:

```
~/Friday/user.json
```

That's the top level of your home directory, no dot prefix, visible in Finder. Everything FRIDAY knows about you is in this single JSON — identity, tone, slang, contact nicknames, briefing watchlist, and your full CV. The file is chmod 600 (only your user account can read it) and is never committed.

## Setup

Three ways:

```bash
friday init              # interactive wizard — covers the basics
friday config edit       # open in $EDITOR for advanced fields
friday config open       # reveal ~/Friday/ in Finder (macOS)
```

Or the Mac app: **Settings → Profile** writes the same file.

If you're migrating from a pre-0.4 install, FRIDAY auto-copies your existing `~/.friday/user.json` and `~/.friday/cv.json` into the new merged file on first launch. No action needed.

## Why one file

Every time FRIDAY talks to a model, it injects a compact snapshot of this file into the system prompt — bio, CV highlights, contact aliases, watchlist. So the assistant *always* knows:

- Who you are and how to address you
- What you're building / working on
- Who your people are (when you say "Mama" it knows)
- What topics to surface in briefings

Keeping all of that in one loadable file means no stale state, no "which file holds X" confusion, and no copy-paste between systems.

## Schema

```jsonc
{
  // Identity
  "name":         "Ada",
  "bio":          "ML engineer, Lagos",
  "location":     "Lagos, Nigeria",
  "country_code": "NG",                      // ISO-2, biases web-search region
  "email":        "ada@example.com",
  "phone":        "+2348012345678",          // E.164 — used by SMS/iMessage-to-self
  "github":       "ada",
  "website":      "ada.dev",

  // Voice / personality
  "tone":  "direct, dry humour",
  "slang": { "oya": "let's go", "abeg": "please" },

  // Relationships — nickname → real name/label
  "contact_aliases": {
    "Mama":    "Mother",
    "Uncle T": "Tunde Adeyemi"
  },

  // Daily briefing feed — handles or search queries
  "briefing_watchlist": [
    { "handle": "@nigerianstat", "note": "policy stats relevant to Nigeria" },
    { "query":  "robotics africa funding", "note": "funding news" }
  ],

  // Full CV — used for job applications AND injected into every system prompt
  "cv": {
    "name":    "Ada Example",
    "title":   "ML Engineer",
    "summary": "3 years shipping production ML systems.",
    "contact": { "email": "ada@example.com", "phone": "+2348012345678", "...": "..." },
    "experience": [
      { "role": "ML Engineer", "company": "Example Co", "period": "2023 — Present",
        "highlights": ["Shipped X that lifted Y by 18%"] }
    ],
    "projects":       [ { "name": "ExampleProject", "summary": "...", "tech": ["Python"] } ],
    "skills":         { "languages": ["Python", "SQL"], "ai_ml": ["PyTorch"] },
    "education":      [ { "school": "...", "qualification": "BSc CS", "period": "2019 — 2023" } ],
    "certifications": []
  }
}
```

The full working example lives at [`docs/user.example.json`](user.example.json) — copy it to `~/Friday/user.json` and edit in place.

## Privacy

- File is chmod 600 on write.
- Never committed — `~/Friday/` is outside the repo.
- Nothing in the file is sent to cloud LLMs unless your prompt actually needs it (signing off an email, tailoring a CV to a posting, etc.).
- To wipe everything: `rm -rf ~/Friday` — FRIDAY recreates defaults next run.
- Runtime data (WhatsApp session, browser profile, SQLite cache, local models) still lives in `~/.friday/` (hidden). That's not meant to be hand-edited.
