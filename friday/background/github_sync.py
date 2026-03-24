"""Background GitHub sync — pulls all repos into the projects DB.

Runs on startup and periodically (every 6 hours).
Extracts project summaries from READMEs using a fast LLM call.
"""

import asyncio
import json
import logging
import threading
from datetime import datetime

from friday.memory.store import get_memory_store
from friday.tools.github_tools import list_repos, get_repo_details

log = logging.getLogger(__name__)


async def _sync_repos():
    """Pull all repos and store structured project data."""
    store = get_memory_store()

    # Step 1: List all repos
    result = await list_repos(limit=30)
    if not result.success:
        log.warning(f"GitHub sync failed: could not list repos")
        return 0

    repos = result.data.get("repos", [])
    synced = 0

    for repo in repos:
        name = repo["name"]
        try:
            # Step 2: Get detailed info for each repo
            detail_result = await get_repo_details(name)
            if not detail_result.success:
                # Store basic info without details
                store.upsert_project({
                    "name": name,
                    "description": repo.get("description", ""),
                    "url": repo.get("url", ""),
                    "language": repo.get("language", ""),
                    "private": repo.get("private", False),
                    "stars": repo.get("stars", 0),
                    "updated_at": repo.get("updated", ""),
                })
                synced += 1
                continue

            detail = detail_result.data

            # Extract tech stack from languages
            all_langs = detail.get("all_languages", [])
            tech_stack = ", ".join(all_langs[:5]) if all_langs else detail.get("language", "")

            # Extract a short summary from README (first meaningful paragraph)
            readme = detail.get("readme", "")
            readme_summary = _extract_readme_summary(readme)

            store.upsert_project({
                "name": name,
                "description": detail.get("description", ""),
                "url": detail.get("url", ""),
                "language": detail.get("language", ""),
                "all_languages": all_langs,
                "topics": detail.get("topics", []),
                "private": detail.get("private", False),
                "stars": detail.get("stars", 0),
                "forks": detail.get("forks", 0),
                "open_issues": detail.get("open_issues", 0),
                "open_prs": detail.get("open_prs", 0),
                "default_branch": detail.get("default_branch", "main"),
                "readme_summary": readme_summary,
                "tech_stack": tech_stack,
                "status": "active",
                "created_at": detail.get("created", ""),
                "updated_at": detail.get("updated", ""),
            })
            synced += 1

        except Exception as e:
            log.debug(f"Failed to sync {name}: {e}")
            continue

    log.info(f"GitHub sync complete: {synced}/{len(repos)} repos synced")
    return synced


def _extract_readme_summary(readme: str) -> str:
    """Extract a concise summary from README text (no LLM, just parsing)."""
    if not readme:
        return ""

    lines = readme.strip().split("\n")
    summary_lines = []
    skip_badges = True

    for line in lines:
        stripped = line.strip()
        # Skip empty lines, badges, images, HTML
        if not stripped:
            if summary_lines:
                break  # Stop at first blank line after content
            continue
        if stripped.startswith(("![", "<", "[![", "---", "===", "```")):
            continue
        if stripped.startswith("#"):
            if skip_badges:
                skip_badges = False
                continue  # Skip title header
            break  # Stop at next header

        skip_badges = False
        summary_lines.append(stripped)

        if len(" ".join(summary_lines)) > 200:
            break

    summary = " ".join(summary_lines)
    if len(summary) > 250:
        summary = summary[:250] + "..."
    return summary


def sync_github_background():
    """Run GitHub sync in a background thread."""
    def _worker():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            count = loop.run_until_complete(_sync_repos())
            log.info(f"Background GitHub sync done: {count} repos")
        except Exception as e:
            log.debug(f"Background GitHub sync failed: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=_worker, daemon=True, name="friday-github-sync")
    t.start()
    return t
