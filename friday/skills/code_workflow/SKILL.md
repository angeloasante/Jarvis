---
name: code-workflow
description: Structured coding workflow — plan before coding, test after, verify before delivering. Use for any code task.
agents: [code_agent]
---

# Code Workflow

When Travis asks you to write, fix, or modify code:

## Flow: Plan → Execute → Verify → Deliver

### 1. Plan (before writing any code)

- Read existing code first — understand what's there
- Identify what needs to change and what shouldn't
- If the change is non-trivial (>20 lines), outline the approach in 3-5 bullet points
- Check for existing utilities, helpers, patterns — reuse, don't reinvent

### 2. Execute

- Write clean, minimal code — no over-engineering
- Follow the existing style of the codebase (indentation, naming, patterns)
- Don't add features that weren't asked for
- Don't refactor code you didn't change
- Don't add comments unless the logic is non-obvious
- Don't add error handling for impossible scenarios

### 3. Verify

- After writing code, mentally trace through it — does it actually work?
- Check edge cases: empty input, None values, missing keys
- If there are tests, run them
- If it's a function, think about what happens with unexpected input

### 4. Deliver

- Show the code diff, not the whole file
- Explain WHAT changed and WHY in 1-2 sentences
- If you changed something non-obvious, explain the reasoning

## Anti-Patterns (never do these)

- Don't create helper functions for one-time operations
- Don't add type hints to code you didn't change
- Don't add docstrings to code you didn't change
- Don't rename variables for "clarity" in code you didn't touch
- Don't add backwards-compatibility shims — just change the code
- Don't wrap everything in try/except — let errors surface
- Don't add feature flags or config for things that should just be code

## Git Conventions

- Commit messages: what changed and why, not how
- One logical change per commit
- Never add Co-Authored-By lines
- Never force push without being asked
- Stage specific files, not `git add .`

## Language-Specific

### Python
- Use f-strings, not .format() or %
- Use pathlib for paths, not os.path
- Use `async def` for I/O-bound functions
- Use dataclasses or plain dicts, not heavy ORMs for simple data

### TypeScript/JavaScript
- Use const by default, let when needed, never var
- Use async/await, not .then() chains
- Use template literals for string interpolation
