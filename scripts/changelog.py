#!/usr/bin/env python3
"""Auto-update CHANGELOG.md from git commits.

No more hand-writing the changelog. This collects every commit since the last
time it ran, sorts them into Added / Changed / Fixed / Docs / Removed by the
commit-message wording, and rewrites the `## [Unreleased]` section at the top
of CHANGELOG.md.

Usage:
    python scripts/changelog.py            # update [Unreleased] from new commits
    python scripts/changelog.py --release "Phase 7 — Coordination"   # cut a release

The last-processed commit is remembered via an HTML comment marker in the file:
    <!-- changelog-marker: <full-sha> -->
so re-running only picks up commits made since.

Wire it to run automatically with:  bash scripts/install-hooks.sh
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
MARKER_RE = re.compile(r"<!--\s*changelog-marker:\s*([0-9a-f]{7,40})\s*-->")

# Commit-subject → section. First match wins; order matters.
RULES = [
    ("Removed", re.compile(r"^\s*(remove|delete|drop|deprecate|rip out|strip)\b", re.I)),
    ("Fixed",   re.compile(r"^\s*(fix|bugfix|hotfix|patch|repair|resolve|correct)\b", re.I)),
    ("Docs",    re.compile(r"^\s*(docs?|readme|changelog|comment|document)\b", re.I)),
    ("Changed", re.compile(r"^\s*(change|refactor|rewrite|update|tune|improve|rework|tweak|bump|rename|move|reorganis|reorganiz)\b", re.I)),
    ("Added",   re.compile(r"^\s*(add|new|introduce|implement|create|build|wire|support|enable|ship)\b", re.I)),
]
SECTION_ORDER = ["Added", "Changed", "Fixed", "Docs", "Removed"]


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()


def _commits_since(marker: str | None) -> list[tuple[str, str]]:
    """Return [(sha, subject)] for commits after the marker (newest last)."""
    rng = f"{marker}..HEAD" if marker else "HEAD"
    try:
        out = _git("log", "--no-merges", "--reverse", "--pretty=format:%H%x09%s", rng)
    except subprocess.CalledProcessError:
        out = _git("log", "--no-merges", "--reverse", "--pretty=format:%H%x09%s", "-30")
    rows = []
    for line in out.splitlines():
        if "\t" not in line:
            continue
        sha, subject = line.split("\t", 1)
        # Skip the changelog's own bookkeeping commits.
        if re.match(r"^\s*(changelog|chore:?\s*changelog)\b", subject, re.I):
            continue
        rows.append((sha, subject.strip()))
    return rows


def _classify(subject: str) -> str:
    for section, pat in RULES:
        if pat.search(subject):
            return section
    return "Changed"  # safe default


def _render_unreleased(buckets: dict[str, list[str]]) -> str:
    lines = ["## [Unreleased]", ""]
    any_entry = False
    for section in SECTION_ORDER:
        items = buckets.get(section) or []
        if not items:
            continue
        any_entry = True
        lines.append(f"### {section}")
        for it in items:
            lines.append(f"- {it}")
        lines.append("")
    if not any_entry:
        lines.append("_No unreleased changes._")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _read() -> str:
    return CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else "# Changelog\n"


def _splice_unreleased(text: str, block: str) -> str:
    """Replace an existing ## [Unreleased] section, or insert one after the
    file's intro (before the first ## heading)."""
    has = re.search(r"^## \[Unreleased\].*?(?=^## |\Z)", text, re.S | re.M)
    if has:
        return text[:has.start()] + block + "\n" + text[has.end():]
    # Insert before the first '## ' heading; else append.
    first = re.search(r"^## ", text, re.M)
    if first:
        return text[:first.start()] + block + "\n---\n\n" + text[first.start():]
    return text.rstrip() + "\n\n" + block


def _set_marker(text: str, sha: str) -> str:
    if MARKER_RE.search(text):
        return MARKER_RE.sub(f"<!-- changelog-marker: {sha} -->", text)
    # Put the marker right after the top H1.
    h1 = re.search(r"^# .*\n", text, re.M)
    if h1:
        return text[:h1.end()] + f"\n<!-- changelog-marker: {sha} -->\n" + text[h1.end():]
    return f"<!-- changelog-marker: {sha} -->\n" + text


def main() -> int:
    text = _read()
    m = MARKER_RE.search(text)
    marker = m.group(1) if m else None

    commits = _commits_since(marker)
    head = _git("rev-parse", "HEAD")

    if "--release" in sys.argv:
        # Promote current [Unreleased] to a dated phase heading.
        idx = sys.argv.index("--release")
        title = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "Release"
        block = re.search(r"^## \[Unreleased\].*?(?=^## |\Z)", text, re.S | re.M)
        if not block or "_No unreleased changes_" in block.group(0):
            print("Nothing in [Unreleased] to release.")
            return 0
        body = block.group(0).split("\n", 1)[1] if "\n" in block.group(0) else ""
        dated = f"## {title}  *({date.today().isoformat()})*\n{body}"
        empty = "## [Unreleased]\n\n_No unreleased changes._\n"
        text = text[:block.start()] + empty + "\n" + dated + text[block.end():]
        CHANGELOG.write_text(text, encoding="utf-8")
        print(f"Released: {title}")
        return 0

    if not commits:
        print("No new commits since last changelog update.")
        return 0

    buckets: dict[str, list[str]] = {}
    for _sha, subject in commits:
        buckets.setdefault(_classify(subject), []).append(subject)

    block = _render_unreleased(buckets)
    text = _splice_unreleased(text, block)
    text = _set_marker(text, head)
    CHANGELOG.write_text(text, encoding="utf-8")
    print(f"Updated CHANGELOG [Unreleased] from {len(commits)} commit(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
