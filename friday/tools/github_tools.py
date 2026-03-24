"""GitHub tools — repo info, commits, issues via gh CLI.

No Python deps needed — uses gh CLI which is already authenticated.
"""

import asyncio
import json
import subprocess
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity


def _gh(args: list[str], timeout: int = 15) -> dict | list | str:
    """Run a gh CLI command and return parsed JSON output."""
    cmd = ["gh"] + args
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"gh command failed: {' '.join(args)}")

    text = result.stdout.strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


async def list_repos(limit: int = 30) -> ToolResult:
    """List all GitHub repos for the authenticated user."""
    try:
        data = await asyncio.to_thread(
            _gh,
            ["repo", "list", "--limit", str(limit),
             "--json", "name,description,url,primaryLanguage,updatedAt,isPrivate,stargazerCount"],
        )
        repos = []
        for r in data:
            repos.append({
                "name": r.get("name"),
                "description": r.get("description") or "",
                "url": r.get("url"),
                "language": (r.get("primaryLanguage") or {}).get("name", "unknown"),
                "private": r.get("isPrivate", False),
                "stars": r.get("stargazerCount", 0),
                "updated": r.get("updatedAt", ""),
            })
        return ToolResult(success=True, data={"repos": repos, "count": len(repos)})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Failed to list repos: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def get_repo_details(repo: str) -> ToolResult:
    """Get detailed info about a specific repo (README, languages, recent commits).

    Args:
        repo: Repo name (e.g. "Minning_detection") or full "owner/repo".
    """
    try:
        # Add owner if not provided
        if "/" not in repo:
            repo = f"angeloasante/{repo}"

        # Fetch repo metadata + README + recent commits in parallel
        async def _meta():
            return await asyncio.to_thread(
                _gh, ["repo", "view", repo, "--json",
                      "name,description,url,primaryLanguage,languages,defaultBranchRef,"
                      "createdAt,updatedAt,isPrivate,stargazerCount,forkCount,"
                      "issues,pullRequests,repositoryTopics"],
            )

        async def _readme():
            try:
                return await asyncio.to_thread(
                    _gh, ["api", f"repos/{repo}/readme",
                          "--jq", ".content", "-H", "Accept: application/vnd.github.raw+json"],
                    timeout=10,
                )
            except Exception:
                return ""

        async def _commits():
            try:
                return await asyncio.to_thread(
                    _gh, ["api", f"repos/{repo}/commits?per_page=5",
                          "--jq", '[.[] | {sha: .sha[0:7], message: .commit.message[0:100], date: .commit.author.date, author: .commit.author.name}]'],
                )
            except Exception:
                return []

        meta, readme, commits = await asyncio.gather(_meta(), _readme(), _commits())

        # Parse metadata
        langs = meta.get("languages", [])
        lang_list = [l.get("node", {}).get("name", "") for l in langs] if isinstance(langs, list) else []
        topics = meta.get("repositoryTopics", [])
        topic_list = [t.get("name", "") for t in topics] if isinstance(topics, list) else []

        # Truncate README
        if isinstance(readme, str) and len(readme) > 2000:
            readme = readme[:2000] + "\n... (truncated)"

        result = {
            "name": meta.get("name"),
            "description": meta.get("description") or "",
            "url": meta.get("url"),
            "language": (meta.get("primaryLanguage") or {}).get("name", "unknown"),
            "all_languages": lang_list,
            "topics": topic_list,
            "private": meta.get("isPrivate", False),
            "stars": meta.get("stargazerCount", 0),
            "forks": meta.get("forkCount", 0),
            "created": meta.get("createdAt", ""),
            "updated": meta.get("updatedAt", ""),
            "default_branch": (meta.get("defaultBranchRef") or {}).get("name", "main"),
            "open_issues": (meta.get("issues") or {}).get("totalCount", 0),
            "open_prs": (meta.get("pullRequests") or {}).get("totalCount", 0),
            "readme": readme if isinstance(readme, str) else "",
            "recent_commits": commits if isinstance(commits, list) else [],
        }

        return ToolResult(success=True, data=result)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Failed to get repo details: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def get_repo_issues(repo: str, state: str = "open", limit: int = 10) -> ToolResult:
    """Get issues for a repo.

    Args:
        repo: Repo name or "owner/repo".
        state: "open", "closed", or "all".
        limit: Max issues to return.
    """
    try:
        if "/" not in repo:
            repo = f"angeloasante/{repo}"

        data = await asyncio.to_thread(
            _gh, ["issue", "list", "--repo", repo, "--state", state,
                  "--limit", str(limit),
                  "--json", "number,title,state,createdAt,author,labels,comments"],
        )

        issues = []
        for i in data:
            issues.append({
                "number": i.get("number"),
                "title": i.get("title"),
                "state": i.get("state"),
                "created": i.get("createdAt"),
                "author": (i.get("author") or {}).get("login", ""),
                "labels": [l.get("name", "") for l in (i.get("labels") or [])],
                "comments": (i.get("comments") or {}).get("totalCount", len(i.get("comments", []))),
            })

        return ToolResult(success=True, data={"issues": issues, "count": len(issues)})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Failed to get issues: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def get_recent_activity(limit: int = 20) -> ToolResult:
    """Get recent GitHub activity across all repos (commits, PRs, issues)."""
    try:
        # Get recent events
        data = await asyncio.to_thread(
            _gh, ["api", "users/angeloasante/events?per_page=" + str(limit),
                  "--jq", '[.[] | {type: .type, repo: .repo.name, created: .created_at, payload_action: .payload.action, payload_ref: .payload.ref}]'],
        )

        events = []
        if isinstance(data, list):
            for e in data:
                events.append({
                    "type": e.get("type", ""),
                    "repo": (e.get("repo") or "").replace("angeloasante/", ""),
                    "action": e.get("payload_action", ""),
                    "ref": e.get("payload_ref", ""),
                    "date": e.get("created", ""),
                })

        return ToolResult(success=True, data={"events": events, "count": len(events)})
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Failed to get activity: {e}",
            severity=Severity.MEDIUM, recoverable=True))


TOOL_SCHEMAS = {
    "list_repos": {
        "fn": list_repos,
        "schema": {"type": "function", "function": {
            "name": "list_repos",
            "description": "List all of Travis's GitHub repositories with descriptions, languages, and stats.",
            "parameters": {"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Max repos to return (default 30)"},
            }, "required": []},
        }},
    },
    "get_repo_details": {
        "fn": get_repo_details,
        "schema": {"type": "function", "function": {
            "name": "get_repo_details",
            "description": "Get detailed info about a GitHub repo: README, languages, recent commits, issues count.",
            "parameters": {"type": "object", "properties": {
                "repo": {"type": "string", "description": "Repo name (e.g. 'Minning_detection') or 'owner/repo'"},
            }, "required": ["repo"]},
        }},
    },
    "get_repo_issues": {
        "fn": get_repo_issues,
        "schema": {"type": "function", "function": {
            "name": "get_repo_issues",
            "description": "Get issues for a GitHub repo.",
            "parameters": {"type": "object", "properties": {
                "repo": {"type": "string", "description": "Repo name or 'owner/repo'"},
                "state": {"type": "string", "enum": ["open", "closed", "all"], "description": "Issue state filter (default: open)"},
                "limit": {"type": "integer", "description": "Max issues (default 10)"},
            }, "required": ["repo"]},
        }},
    },
    "get_recent_activity": {
        "fn": get_recent_activity,
        "schema": {"type": "function", "function": {
            "name": "get_recent_activity",
            "description": "Get Travis's recent GitHub activity across all repos (commits, PRs, issues).",
            "parameters": {"type": "object", "properties": {
                "limit": {"type": "integer", "description": "Max events (default 20)"},
            }, "required": []},
        }},
    },
}
