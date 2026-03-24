# FRIDAY — Tools
### *"Agents are the brain. Skills are the wisdom. Tools are the hands that actually touch the world."*

---

## Table of Contents

1. [What A Tool Actually Is](#what-a-tool-actually-is)
2. [Tool Architecture](#tool-architecture)
3. [Tool Registration System](#tool-registration-system)
4. [Web Tools](#web-tools)
5. [File Tools](#file-tools)
6. [Terminal Tools](#terminal-tools)
7. [Git Tools](#git-tools)
8. [Email Tools](#email-tools)
9. [Calendar Tools](#calendar-tools)
10. [Memory Tools](#memory-tools)
11. [Deployment Tools](#deployment-tools)
12. [Database Tools](#database-tools)
13. [Mac Control Tools](#mac-control-tools)
14. [Browser Tools](#browser-tools)
15. [Screenpipe Tools](#screenpipe-tools)
16. [Notification Tools](#notification-tools)
17. [Agent Dispatch Tools](#agent-dispatch-tools)
18. [Utility Tools](#utility-tools)
19. [MCP Server Setup](#mcp-server-setup)
20. [Tool Testing](#tool-testing)

---

## What A Tool Actually Is

A tool is a Python async function that does exactly one thing,
returns a structured result, and never has opinions about
whether it should be called.

```python
# This is the entire concept of a tool:

async def search_web(query: str, num_results: int = 5) -> ToolResult:
    """Search the web. Return results. That's it."""
    response = await tavily_client.search(query=query, max_results=num_results)
    return ToolResult(
        success=True,
        data=response.results,
        metadata={"query": query, "result_count": len(response.results)}
    )
```

No guardrails. No hidden logic. No opinions baked in.
The tool does what it's told. The skill teaches the agent
what to tell it. The agent makes the decision.

This separation is what makes the system debuggable, testable,
and replaceable. If a tool breaks, you fix the tool.
If the agent uses the tool wrong, you update the skill.
These are different problems with different solutions.

---

## Tool Architecture

### Base Types

Every tool in FRIDAY returns one of these:

```python
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
from datetime import datetime


class ErrorCode(Enum):
    # Network
    RATE_LIMIT          = "rate_limit"
    NETWORK_ERROR       = "network_error"
    TIMEOUT             = "timeout"
    AUTH_FAILED         = "auth_failed"
    NOT_FOUND           = "not_found"

    # File system
    FILE_NOT_FOUND      = "file_not_found"
    PERMISSION_DENIED   = "permission_denied"
    DISK_FULL           = "disk_full"

    # Code / Process
    COMMAND_FAILED      = "command_failed"
    PROCESS_TIMEOUT     = "process_timeout"
    BUILD_FAILED        = "build_failed"
    TEST_FAILED         = "test_failed"

    # Data
    PARSE_ERROR         = "parse_error"
    VALIDATION_ERROR    = "validation_error"
    EMPTY_RESULT        = "empty_result"

    # Payment / Revenue Critical
    PAYMENT_FAILED      = "payment_failed"
    WEBHOOK_INVALID     = "webhook_invalid"
    SIGNATURE_FAILED    = "signature_failed"

    # General
    UNKNOWN             = "unknown"
    CONFIG_MISSING      = "config_missing"


class Severity(Enum):
    LOW      = "low"       # Log, move on
    MEDIUM   = "medium"    # Retry, report if persistent
    HIGH     = "high"      # Report before continuing
    CRITICAL = "critical"  # Interrupt everything


@dataclass
class ToolError:
    code: ErrorCode
    message: str
    severity: Severity
    recoverable: bool
    retry_after: Optional[int] = None   # seconds
    escalate: bool = False
    context: dict = field(default_factory=dict)

    @property
    def should_interrupt(self) -> bool:
        return self.severity == Severity.CRITICAL or self.escalate


@dataclass
class ToolResult:
    success: bool
    data: Optional[Any] = None
    error: Optional[ToolError] = None
    metadata: dict = field(default_factory=dict)
    duration_ms: Optional[int] = None
    called_at: datetime = field(default_factory=datetime.now)

    def unwrap(self) -> Any:
        """Get data or raise if failed."""
        if not self.success:
            raise ToolExecutionError(self.error)
        return self.data
```

### Base Tool Class

```python
import asyncio
import time
from functools import wraps


class BaseTool:
    """
    Base class for all FRIDAY tools.
    Handles timing, logging, retry logic, error wrapping.
    """

    name: str = "base_tool"
    description: str = ""

    async def execute(self, **kwargs) -> ToolResult:
        raise NotImplementedError

    async def __call__(self, **kwargs) -> ToolResult:
        start = time.monotonic()

        try:
            result = await self.execute(**kwargs)
            result.duration_ms = int((time.monotonic() - start) * 1000)
            await self._log_call(kwargs, result)
            return result

        except Exception as e:
            duration_ms = int((time.monotonic() - start) * 1000)
            error = self._wrap_exception(e)
            result = ToolResult(
                success=False,
                error=error,
                duration_ms=duration_ms
            )
            await self._log_call(kwargs, result)
            return result

    async def _log_call(self, args: dict, result: ToolResult):
        """Log every tool call to SQLite for debugging."""
        await sqlite.execute("""
            INSERT INTO agent_calls
            (agent, tool, args, result_summary, success, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
        """, [
            current_agent_name(),
            self.name,
            json.dumps(args, default=str),
            self._summarise_result(result),
            result.success,
            result.duration_ms
        ])

    def _wrap_exception(self, e: Exception) -> ToolError:
        """Map Python exceptions to ToolError types."""
        if isinstance(e, asyncio.TimeoutError):
            return ToolError(
                code=ErrorCode.TIMEOUT,
                message=f"Tool {self.name} timed out",
                severity=Severity.MEDIUM,
                recoverable=True,
                retry_after=30
            )
        # ... other mappings
        return ToolError(
            code=ErrorCode.UNKNOWN,
            message=str(e),
            severity=Severity.HIGH,
            recoverable=False,
            escalate=True,
            context={"exception_type": type(e).__name__}
        )

    def _summarise_result(self, result: ToolResult) -> str:
        if result.success:
            return f"success: {str(result.data)[:100]}"
        return f"failed: {result.error.code.value} — {result.error.message[:100]}"
```

---

## Tool Registration System

Tools are registered and scoped per agent.
An agent only sees tools it's allowed to use.

```python
from typing import Type


TOOL_REGISTRY: dict[str, Type[BaseTool]] = {}


def register_tool(tool_class: Type[BaseTool]):
    """Decorator to register a tool."""
    TOOL_REGISTRY[tool_class.name] = tool_class
    return tool_class


# Agent tool scopes — what each cluster can access
AGENT_TOOL_SCOPE: dict[str, list[str]] = {

    "friday_core": [
        "dispatch_agent", "get_memory", "store_memory",
        "create_reminder", "get_calendar_summary", "send_notification"
    ],

    "code_agent": [
        "read_file", "write_file", "list_directory", "search_files",
        "run_terminal", "run_python", "run_background_process",
        "git_status", "git_diff", "git_commit", "git_push",
        "git_pull", "git_log", "create_branch", "git_stash",
        "read_build_logs", "run_supabase_query", "get_supabase_schema",
        "search_web", "web_fetch", "get_memory", "store_memory",
        "check_deployment_health", "deploy_modal"
    ],

    "debug_agent": [
        "read_file", "write_file", "search_files", "search_codebase",
        "run_terminal", "read_build_logs", "read_error_logs",
        "search_web", "web_fetch", "get_memory", "store_memory",
        "get_supabase_schema", "run_supabase_query"
    ],

    "test_agent": [
        "read_file", "write_file", "list_directory",
        "run_terminal", "run_python", "get_memory"
    ],

    "git_agent": [
        "git_status", "git_diff", "git_commit", "git_push",
        "git_pull", "git_log", "create_branch", "git_stash",
        "git_tag", "check_github_actions", "get_git_blame",
        "read_file"
    ],

    "devops_agent": [
        "check_railway_status", "check_vercel_deployments",
        "check_modal_usage", "get_modal_billing",
        "get_runpod_instances", "check_runpod_status",
        "deploy_modal", "deploy_railway", "get_railway_logs",
        "check_railway_env", "check_github_actions",
        "read_error_logs", "check_deployment_health",
        "ping_endpoint", "run_terminal", "get_memory"
    ],

    "research_agent": [
        "search_web", "web_fetch", "academic_search",
        "get_memory", "store_memory", "extract_page_content"
    ],

    "email_agent": [
        "read_emails", "read_email_thread", "send_email",
        "draft_email", "archive_email", "search_emails",
        "reply_email", "forward_email", "label_email",
        "get_memory", "store_memory"
    ],

    "calendar_agent": [
        "get_calendar", "create_event", "update_event",
        "delete_event", "find_free_slots", "send_invite",
        "get_next_event", "get_memory"
    ],

    "memory_agent": [
        "store_letta_memory", "query_letta_memory",
        "store_chromadb", "query_chromadb",
        "get_sqlite_record", "update_sqlite_record",
        "add_project", "archive_project", "update_project",
        "add_person", "get_project_context",
        "add_incident", "resolve_incident"
    ],

    "screenpipe_agent": [
        "search_screenpipe", "query_screenpipe_browser",
        "query_screenpipe_audio", "query_screenpipe_screen",
        "get_screenpipe_summary", "store_memory"
    ],

    "mac_control_agent": [
        "run_applescript", "open_application", "close_application",
        "take_screenshot", "set_volume", "get_running_processes",
        "open_folder", "get_clipboard", "set_clipboard",
        "focus_window", "run_terminal"
    ],

    "browser_agent": [
        "browser_navigate", "browser_click", "browser_fill_form",
        "browser_screenshot", "browser_extract_content",
        "browser_scroll", "browser_wait_for", "browser_execute_js",
        "browser_get_cookies", "browser_close_tab",
        "web_fetch", "search_web"
    ],

    "notification_agent": [
        "create_reminder", "update_reminder", "delete_reminder",
        "send_desktop_notification", "send_voice_notification",
        "schedule_cron", "cancel_cron", "get_pending_reminders",
        "get_memory", "get_calendar"
    ],

    "monitoring_agent": [
        "check_deployment_health", "check_all_deployments",
        "read_error_logs", "get_supabase_metrics",
        "ping_endpoint", "get_process_status",
        "check_modal_usage", "check_railway_status",
        "add_incident", "resolve_incident",
        "send_notification", "store_memory"
    ],
}


def get_tools_for_agent(agent_name: str) -> list[BaseTool]:
    """Return instantiated tool objects for a given agent."""
    tool_names = AGENT_TOOL_SCOPE.get(agent_name, [])
    return [TOOL_REGISTRY[name]() for name in tool_names
            if name in TOOL_REGISTRY]
```

---

## Web Tools

```python
import httpx
from tavily import TavilyClient


@register_tool
class SearchWeb(BaseTool):
    """
    Search the internet using Tavily.
    Returns structured results with title, url, content, score.
    """
    name = "search_web"
    description = (
        "Search the internet for current information. "
        "Use for real-time data, recent events, documentation, "
        "anything that could have changed since training cutoff."
    )

    def __init__(self):
        self.client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])

    async def execute(
        self,
        query: str,
        num_results: int = 5,
        search_depth: str = "basic",  # "basic" or "advanced"
        include_domains: list[str] = None,
        exclude_domains: list[str] = None
    ) -> ToolResult:

        try:
            response = await asyncio.to_thread(
                self.client.search,
                query=query,
                max_results=num_results,
                search_depth=search_depth,
                include_domains=include_domains or [],
                exclude_domains=exclude_domains or []
            )

            results = [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "content": r.get("content"),
                    "score": r.get("score"),
                    "published_date": r.get("published_date")
                }
                for r in response.get("results", [])
            ]

            return ToolResult(
                success=True,
                data=results,
                metadata={
                    "query": query,
                    "result_count": len(results),
                    "search_depth": search_depth
                }
            )

        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.RATE_LIMIT,
                        message="Tavily rate limit hit",
                        severity=Severity.MEDIUM,
                        recoverable=True,
                        retry_after=60,
                        escalate=False
                    )
                )
            raise


@register_tool
class WebFetch(BaseTool):
    """
    Fetch the full content of a specific URL.
    Use when search snippets aren't enough — get the full page.
    Essential for reading documentation, articles, GitHub READMEs.
    """
    name = "web_fetch"
    description = (
        "Fetch full content from a URL. Use after search_web "
        "when you need complete article/doc content, not just snippets."
    )

    async def execute(
        self,
        url: str,
        timeout: int = 30,
        extract_mode: str = "text"  # "text", "markdown", "raw"
    ) -> ToolResult:

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.get(
                    url,
                    headers={"User-Agent": "FRIDAY/1.0"},
                    follow_redirects=True
                )
                response.raise_for_status()

                content = self._extract_content(response.text, extract_mode)

                return ToolResult(
                    success=True,
                    data={
                        "url": url,
                        "content": content,
                        "status_code": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "word_count": len(content.split())
                    }
                )

            except httpx.TimeoutException:
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.TIMEOUT,
                        message=f"Timeout fetching {url}",
                        severity=Severity.MEDIUM,
                        recoverable=True,
                        retry_after=10
                    )
                )
            except httpx.HTTPStatusError as e:
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.NOT_FOUND if e.response.status_code == 404
                             else ErrorCode.AUTH_FAILED if e.response.status_code in (401, 403)
                             else ErrorCode.NETWORK_ERROR,
                        message=f"HTTP {e.response.status_code} from {url}",
                        severity=Severity.LOW,
                        recoverable=False,
                        context={"status_code": e.response.status_code}
                    )
                )

    def _extract_content(self, html: str, mode: str) -> str:
        from bs4 import BeautifulSoup
        if mode == "raw":
            return html
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Clean up excessive whitespace
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        return "\n".join(lines)


@register_tool
class AcademicSearch(BaseTool):
    """
    Search academic papers via ArXiv API.
    Use for research papers, ML techniques, scientific claims.
    """
    name = "academic_search"
    description = (
        "Search academic papers on ArXiv. "
        "Use for ML research, scientific papers, technical proofs."
    )

    async def execute(
        self,
        query: str,
        max_results: int = 5,
        sort_by: str = "relevance",     # "relevance", "lastUpdatedDate"
        categories: list[str] = None    # e.g. ["cs.CL", "cs.AI"]
    ) -> ToolResult:

        import arxiv
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance if sort_by == "relevance"
                    else arxiv.SortCriterion.LastUpdatedDate,
            id_list=[]
        )

        results = []
        async for paper in asyncio.to_thread(lambda: list(search.results())):
            results.append({
                "title": paper.title,
                "authors": [a.name for a in paper.authors[:3]],
                "abstract": paper.summary[:500],
                "url": paper.entry_id,
                "pdf_url": paper.pdf_url,
                "published": str(paper.published.date()),
                "categories": paper.categories,
                "comment": paper.comment
            })

        return ToolResult(
            success=True,
            data=results,
            metadata={"query": query, "result_count": len(results)}
        )
```

---

## File Tools

```python
from pathlib import Path
import aiofiles
import fnmatch


@register_tool
class ReadFile(BaseTool):
    """
    Read a file from the filesystem.
    Supports line range selection for large files.
    Never reads files outside allowed directories.
    """
    name = "read_file"
    description = (
        "Read file contents. Specify line range for large files. "
        "Returns content as string."
    )

    ALLOWED_DIRS = [
        Path.home() / "projects",
        Path.home() / "datasets",
        Path.home() / "docs",
        Path.home() / "models",
        Path("/tmp/friday")
    ]

    async def execute(
        self,
        path: str,
        lines: tuple[int, int] = None,  # (start, end) — 1-indexed
        encoding: str = "utf-8"
    ) -> ToolResult:

        file_path = Path(path).expanduser().resolve()

        # Security: never read outside allowed dirs
        if not self._is_allowed(file_path):
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.PERMISSION_DENIED,
                    message=f"Path {path} is outside allowed directories",
                    severity=Severity.HIGH,
                    recoverable=False,
                    escalate=True
                )
            )

        if not file_path.exists():
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"File not found: {path}",
                    severity=Severity.LOW,
                    recoverable=False
                )
            )

        try:
            async with aiofiles.open(file_path, encoding=encoding) as f:
                content = await f.read()

            if lines:
                all_lines = content.splitlines()
                start = max(0, lines[0] - 1)
                end = min(len(all_lines), lines[1])
                content = "\n".join(all_lines[start:end])
                line_info = f"lines {lines[0]}-{lines[1]}"
            else:
                line_info = f"{len(content.splitlines())} lines"

            return ToolResult(
                success=True,
                data=content,
                metadata={
                    "path": str(file_path),
                    "size_bytes": file_path.stat().st_size,
                    "lines": line_info,
                    "extension": file_path.suffix
                }
            )

        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.PARSE_ERROR,
                    message=f"Cannot read {path} as {encoding} — binary file?",
                    severity=Severity.LOW,
                    recoverable=True,
                    context={"suggested_fix": "Try encoding='latin-1' or read as binary"}
                )
            )

    def _is_allowed(self, path: Path) -> bool:
        return any(
            str(path).startswith(str(allowed))
            for allowed in self.ALLOWED_DIRS
        )


@register_tool
class WriteFile(BaseTool):
    """
    Write content to a file.
    Creates parent directories if needed.
    Never overwrites without reading first (checked by caller via skill).
    Backs up before writing if file exists.
    """
    name = "write_file"
    description = (
        "Write content to a file. Creates parent dirs if needed. "
        "Set append=True to add to existing file."
    )

    async def execute(
        self,
        path: str,
        content: str,
        append: bool = False,
        encoding: str = "utf-8",
        backup: bool = True  # Backup existing file before overwrite
    ) -> ToolResult:

        file_path = Path(path).expanduser().resolve()

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Backup if file exists and we're overwriting
        backup_path = None
        if file_path.exists() and not append and backup:
            backup_path = file_path.with_suffix(
                f".backup_{int(datetime.now().timestamp())}{file_path.suffix}"
            )
            file_path.rename(backup_path)

        mode = "a" if append else "w"

        async with aiofiles.open(file_path, mode=mode, encoding=encoding) as f:
            await f.write(content)

        return ToolResult(
            success=True,
            data={
                "path": str(file_path),
                "bytes_written": len(content.encode(encoding)),
                "mode": "append" if append else "overwrite",
                "backup_created": str(backup_path) if backup_path else None
            }
        )


@register_tool
class ListDirectory(BaseTool):
    """List directory contents up to specified depth."""
    name = "list_directory"

    async def execute(
        self,
        path: str,
        depth: int = 1,
        include_hidden: bool = False,
        pattern: str = None  # e.g. "*.py", "*.ts"
    ) -> ToolResult:

        dir_path = Path(path).expanduser().resolve()

        if not dir_path.exists():
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"Directory not found: {path}",
                    severity=Severity.LOW,
                    recoverable=False
                )
            )

        items = []
        self._scan(dir_path, dir_path, depth, 0,
                   include_hidden, pattern, items)

        return ToolResult(
            success=True,
            data=items,
            metadata={"path": str(dir_path), "item_count": len(items)}
        )

    def _scan(self, root, current, max_depth, current_depth,
              include_hidden, pattern, items):
        if current_depth > max_depth:
            return
        try:
            for item in sorted(current.iterdir()):
                if not include_hidden and item.name.startswith("."):
                    continue
                if pattern and not fnmatch.fnmatch(item.name, pattern):
                    if not item.is_dir():
                        continue
                relative = str(item.relative_to(root))
                items.append({
                    "path": relative,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                    "modified": datetime.fromtimestamp(
                        item.stat().st_mtime
                    ).isoformat()
                })
                if item.is_dir():
                    self._scan(root, item, max_depth, current_depth + 1,
                               include_hidden, pattern, items)
        except PermissionError:
            pass


@register_tool
class SearchFiles(BaseTool):
    """
    Search for files by name pattern or content.
    Used when the agent doesn't know exact file paths.
    """
    name = "search_files"

    async def execute(
        self,
        query: str,
        directory: str = "~/projects",
        search_type: str = "name",   # "name", "content", "both"
        file_types: list[str] = None, # [".py", ".ts", ".md"]
        max_results: int = 20
    ) -> ToolResult:

        base_dir = Path(directory).expanduser().resolve()
        results = []

        extensions = set(file_types) if file_types else None

        for file_path in base_dir.rglob("*"):
            if not file_path.is_file():
                continue

            # Skip common noise
            skip_patterns = [
                "node_modules", ".git", ".venv", "__pycache__",
                ".next", "dist", "build", ".cache"
            ]
            if any(p in str(file_path) for p in skip_patterns):
                continue

            # Filter by extension
            if extensions and file_path.suffix not in extensions:
                continue

            matched = False
            match_context = None

            # Name search
            if search_type in ("name", "both"):
                if query.lower() in file_path.name.lower():
                    matched = True
                    match_context = f"filename match"

            # Content search
            if search_type in ("content", "both") and not matched:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    if query.lower() in content.lower():
                        matched = True
                        # Find the matching line for context
                        for i, line in enumerate(content.splitlines(), 1):
                            if query.lower() in line.lower():
                                match_context = f"line {i}: {line.strip()[:80]}"
                                break
                except Exception:
                    pass

            if matched:
                results.append({
                    "path": str(file_path.relative_to(base_dir)),
                    "full_path": str(file_path),
                    "size": file_path.stat().st_size,
                    "modified": datetime.fromtimestamp(
                        file_path.stat().st_mtime
                    ).isoformat(),
                    "match_context": match_context
                })

            if len(results) >= max_results:
                break

        return ToolResult(
            success=True,
            data=results,
            metadata={
                "query": query,
                "search_type": search_type,
                "result_count": len(results)
            }
        )
```

---

## Terminal Tools

```python
import asyncio
import subprocess
import signal
from typing import Optional


RUNNING_PROCESSES: dict[str, asyncio.subprocess.Process] = {}


@register_tool
class RunTerminal(BaseTool):
    """
    Execute a shell command.
    Captures both stdout and stderr.
    Enforces timeout.
    Never runs dangerous commands without explicit confirmation flag.
    """
    name = "run_terminal"

    DANGEROUS_PATTERNS = [
        "rm -rf", "sudo rm", "format", "fdisk",
        "dd if=/dev/zero", "mkfs", "> /dev/",
        ":(){ :|:& };:", "fork bomb"
    ]

    async def execute(
        self,
        command: str,
        cwd: str = None,
        timeout: int = 60,
        env_extra: dict = None,
        confirmed_dangerous: bool = False  # Must be explicit
    ) -> ToolResult:

        # Danger check
        for pattern in self.DANGEROUS_PATTERNS:
            if pattern in command.lower():
                if not confirmed_dangerous:
                    return ToolResult(
                        success=False,
                        error=ToolError(
                            code=ErrorCode.PERMISSION_DENIED,
                            message=f"Dangerous command detected: '{pattern}' in command. "
                                    f"Set confirmed_dangerous=True after Travis confirms.",
                            severity=Severity.HIGH,
                            recoverable=False,
                            escalate=True,
                            context={"command": command, "pattern": pattern}
                        )
                    )

        working_dir = Path(cwd).expanduser().resolve() if cwd else Path.home()

        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(working_dir),
                env=env
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.send_signal(signal.SIGTERM)
                await asyncio.sleep(2)
                process.kill()
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.PROCESS_TIMEOUT,
                        message=f"Command timed out after {timeout}s: {command[:80]}",
                        severity=Severity.MEDIUM,
                        recoverable=True,
                        retry_after=0,
                        context={"command": command, "timeout": timeout}
                    )
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            returncode = process.returncode

            success = returncode == 0

            return ToolResult(
                success=success,
                data={
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": returncode,
                    "command": command,
                    "cwd": str(working_dir)
                },
                error=None if success else ToolError(
                    code=ErrorCode.COMMAND_FAILED,
                    message=f"Command exited with code {returncode}",
                    severity=Severity.MEDIUM,
                    recoverable=False,
                    context={
                        "returncode": returncode,
                        "stderr": stderr[:500],
                        "command": command
                    }
                )
            )

        except FileNotFoundError:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Command not found. Is it installed and in PATH?",
                    severity=Severity.MEDIUM,
                    recoverable=False,
                    context={"command": command.split()[0]}
                )
            )


@register_tool
class RunBackgroundProcess(BaseTool):
    """
    Run a long-running process in background.
    Returns a process_id for monitoring.
    Process auto-terminates after max_runtime seconds.
    """
    name = "run_background_process"

    async def execute(
        self,
        command: str,
        cwd: str = None,
        max_runtime: int = 3600,  # 1 hour default max
        label: str = None
    ) -> ToolResult:

        process_id = label or f"proc_{int(datetime.now().timestamp())}"

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )

        RUNNING_PROCESSES[process_id] = process

        # Auto-kill after max_runtime
        async def auto_kill():
            await asyncio.sleep(max_runtime)
            if process_id in RUNNING_PROCESSES:
                process.kill()
                del RUNNING_PROCESSES[process_id]

        asyncio.create_task(auto_kill())

        return ToolResult(
            success=True,
            data={
                "process_id": process_id,
                "pid": process.pid,
                "command": command,
                "max_runtime": max_runtime
            }
        )


@register_tool
class GetProcessOutput(BaseTool):
    """Get stdout/stderr from a running background process."""
    name = "get_process_output"

    async def execute(self, process_id: str) -> ToolResult:
        process = RUNNING_PROCESSES.get(process_id)

        if not process:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Process {process_id} not found. "
                            f"It may have completed.",
                    severity=Severity.LOW,
                    recoverable=False
                )
            )

        still_running = process.returncode is None

        if not still_running:
            stdout, stderr = await process.communicate()
            del RUNNING_PROCESSES[process_id]
        else:
            # Read what's available without blocking
            stdout = b""
            stderr = b""

        return ToolResult(
            success=True,
            data={
                "process_id": process_id,
                "running": still_running,
                "returncode": process.returncode,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace")
            }
        )


@register_tool
class KillProcess(BaseTool):
    """Kill a running background process."""
    name = "kill_process"

    async def execute(self, process_id: str) -> ToolResult:
        process = RUNNING_PROCESSES.get(process_id)

        if not process:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Process {process_id} not found",
                    severity=Severity.LOW,
                    recoverable=False
                )
            )

        process.kill()
        del RUNNING_PROCESSES[process_id]

        return ToolResult(
            success=True,
            data={"process_id": process_id, "killed": True}
        )
```

---

## Git Tools

```python
@register_tool
class GitStatus(BaseTool):
    name = "git_status"

    async def execute(self, repo: str = ".") -> ToolResult:
        result = await RunTerminal().execute(
            "git status --porcelain --branch",
            cwd=repo
        )
        if not result.success:
            return result

        output = result.data["stdout"]
        lines = output.strip().splitlines()

        branch = ""
        staged = []
        unstaged = []
        untracked = []

        for line in lines:
            if line.startswith("##"):
                branch = line[3:].split("...")[0].strip()
            elif line.startswith("A ") or line.startswith("M "):
                staged.append(line[3:])
            elif line.startswith(" M") or line.startswith(" D"):
                unstaged.append(line[3:])
            elif line.startswith("??"):
                untracked.append(line[3:])

        return ToolResult(
            success=True,
            data={
                "branch": branch,
                "staged": staged,
                "unstaged": unstaged,
                "untracked": untracked,
                "is_clean": not (staged or unstaged or untracked),
                "raw": output
            }
        )


@register_tool
class GitCommit(BaseTool):
    name = "git_commit"

    # Patterns that should never be committed
    SECRET_PATTERNS = [
        "sk_live_", "sk_test_", "PRIVATE KEY",
        "password=", "secret=", "API_KEY=",
        "Bearer ", "token="
    ]

    async def execute(
        self,
        message: str,
        repo: str = ".",
        add_all: bool = False,
        files: list[str] = None  # Specific files if not add_all
    ) -> ToolResult:

        # Secret scan before committing
        diff_result = await RunTerminal().execute(
            "git diff --cached" if not add_all else "git diff HEAD",
            cwd=repo
        )
        if diff_result.success:
            diff_content = diff_result.data["stdout"]
            for pattern in self.SECRET_PATTERNS:
                if pattern in diff_content:
                    return ToolResult(
                        success=False,
                        error=ToolError(
                            code=ErrorCode.VALIDATION_ERROR,
                            message=f"Potential secret detected in diff: '{pattern}'. "
                                    f"Commit blocked. Remove the secret first.",
                            severity=Severity.CRITICAL,
                            recoverable=False,
                            escalate=True,
                            context={"pattern": pattern, "repo": repo}
                        )
                    )

        # Validate commit message format
        valid_prefixes = [
            "feat", "fix", "chore", "docs", "refactor",
            "test", "perf", "ci", "style", "build", "revert", "WIP"
        ]
        if not any(message.startswith(p) for p in valid_prefixes):
            # Warn but don't block
            message = f"chore: {message}"

        # Stage files
        if add_all:
            stage_result = await RunTerminal().execute("git add -A", cwd=repo)
        elif files:
            stage_result = await RunTerminal().execute(
                f"git add {' '.join(files)}", cwd=repo
            )
        else:
            stage_result = ToolResult(success=True, data={})

        if not stage_result.success:
            return stage_result

        # Commit
        commit_result = await RunTerminal().execute(
            f'git commit -m "{message}"',
            cwd=repo
        )

        if commit_result.success:
            # Get the commit hash
            hash_result = await RunTerminal().execute(
                "git rev-parse --short HEAD",
                cwd=repo
            )
            commit_hash = hash_result.data["stdout"].strip() if hash_result.success else "unknown"

            return ToolResult(
                success=True,
                data={
                    "message": message,
                    "hash": commit_hash,
                    "repo": repo
                }
            )

        return commit_result


@register_tool
class GitPush(BaseTool):
    name = "git_push"

    async def execute(
        self,
        repo: str = ".",
        branch: str = None,
        force: bool = False  # Never True without explicit confirmation
    ) -> ToolResult:

        if force:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.PERMISSION_DENIED,
                    message="Force push is disabled. Use --force-with-lease "
                            "on feature branches only, never on main.",
                    severity=Severity.HIGH,
                    recoverable=False,
                    escalate=True
                )
            )

        # Get current branch if not specified
        if not branch:
            branch_result = await RunTerminal().execute(
                "git branch --show-current", cwd=repo
            )
            if branch_result.success:
                branch = branch_result.data["stdout"].strip()

        result = await RunTerminal().execute(
            f"git push origin {branch}",
            cwd=repo,
            timeout=60
        )

        return result


@register_tool
class GitLog(BaseTool):
    name = "git_log"

    async def execute(
        self,
        repo: str = ".",
        limit: int = 10,
        since: str = None,   # e.g. "1 week ago", "2026-01-01"
        author: str = None,
        file_path: str = None
    ) -> ToolResult:

        cmd_parts = [
            "git log",
            f"--max-count={limit}",
            '--format={"hash":"%h","author":"%an","date":"%ai","message":"%s"}'
        ]

        if since:
            cmd_parts.append(f'--since="{since}"')
        if author:
            cmd_parts.append(f'--author="{author}"')
        if file_path:
            cmd_parts.append(f"-- {file_path}")

        result = await RunTerminal().execute(" ".join(cmd_parts), cwd=repo)

        if not result.success:
            return result

        commits = []
        for line in result.data["stdout"].strip().splitlines():
            try:
                commits.append(json.loads(line))
            except json.JSONDecodeError:
                pass

        return ToolResult(
            success=True,
            data=commits,
            metadata={"repo": repo, "commit_count": len(commits)}
        )


@register_tool
class CheckGithubActions(BaseTool):
    name = "check_github_actions"

    async def execute(self, repo: str) -> ToolResult:
        # Uses GitHub CLI (gh) — must be installed and authenticated
        result = await RunTerminal().execute(
            f"gh run list --repo {repo} --limit 5 --json "
            f"status,conclusion,name,createdAt,url",
        )

        if not result.success:
            return result

        try:
            runs = json.loads(result.data["stdout"])
            return ToolResult(
                success=True,
                data=runs,
                metadata={"repo": repo}
            )
        except json.JSONDecodeError:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.PARSE_ERROR,
                    message="Could not parse GitHub Actions output. "
                            "Is 'gh' CLI installed and authenticated?",
                    severity=Severity.LOW,
                    recoverable=False
                )
            )
```

---

## Email Tools

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import base64
from email.mime.text import MIMEText


class GmailBase:
    """Shared Gmail service setup for all email tools."""

    _service = None

    @classmethod
    def get_service(cls):
        if not cls._service:
            creds = Credentials.from_authorized_user_file(
                Path.home() / ".friday" / "gmail_token.json"
            )
            cls._service = build("gmail", "v1", credentials=creds)
        return cls._service


@register_tool
class ReadEmails(GmailBase, BaseTool):
    """
    Read emails from Gmail.
    Supports filtering by date, sender, label, read status.
    Never returns full raw email — always structured.
    """
    name = "read_emails"

    PRIORITY_SENDERS = {
        "paystack": Severity.CRITICAL,
        "stripe": Severity.CRITICAL,
        "railway": Severity.HIGH,
        "modal": Severity.HIGH,
    }

    async def execute(
        self,
        filter: str = "unread",  # "unread", "today", "from:name", custom query
        limit: int = 20,
        include_body: bool = False,
        label: str = "INBOX"
    ) -> ToolResult:

        query_map = {
            "unread": "is:unread",
            "today": "after:" + datetime.now().strftime("%Y/%m/%d"),
            "urgent": "is:unread is:important"
        }

        query = query_map.get(filter, filter)
        if label != "INBOX":
            query = f"in:{label} {query}"

        service = self.get_service()

        result = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me",
                q=query,
                maxResults=limit
            ).execute()
        )

        messages = result.get("messages", [])
        emails = []

        for msg in messages:
            email_data = await asyncio.to_thread(
                lambda m=msg: service.users().messages().get(
                    userId="me",
                    id=m["id"],
                    format="full" if include_body else "metadata"
                ).execute()
            )

            parsed = self._parse_email(email_data, include_body)

            # Tag priority level
            parsed["priority"] = self._get_priority(parsed)
            emails.append(parsed)

        # Sort by priority then date
        emails.sort(key=lambda e: (
            ["critical", "high", "normal", "low"].index(
                e.get("priority", "normal")
            ),
            e.get("date", "")
        ))

        return ToolResult(
            success=True,
            data=emails,
            metadata={
                "filter": filter,
                "count": len(emails),
                "critical_count": sum(1 for e in emails
                                      if e.get("priority") == "critical")
            }
        )

    def _parse_email(self, email_data: dict, include_body: bool) -> dict:
        headers = {
            h["name"].lower(): h["value"]
            for h in email_data.get("payload", {}).get("headers", [])
        }

        parsed = {
            "id": email_data["id"],
            "thread_id": email_data.get("threadId"),
            "subject": headers.get("subject", "(no subject)"),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "date": headers.get("date", ""),
            "snippet": email_data.get("snippet", ""),
            "labels": email_data.get("labelIds", []),
            "unread": "UNREAD" in email_data.get("labelIds", [])
        }

        if include_body:
            parsed["body"] = self._extract_body(email_data.get("payload", {}))

        return parsed

    def _get_priority(self, email: dict) -> str:
        sender_lower = email.get("from", "").lower()
        for keyword, severity in self.PRIORITY_SENDERS.items():
            if keyword in sender_lower:
                return severity.value
        if "IMPORTANT" in email.get("labels", []):
            return "high"
        return "normal"

    def _extract_body(self, payload: dict) -> str:
        body = ""
        if payload.get("body", {}).get("data"):
            body = base64.urlsafe_b64decode(
                payload["body"]["data"]
            ).decode("utf-8", errors="replace")
        elif payload.get("parts"):
            for part in payload["parts"]:
                if part.get("mimeType") == "text/plain":
                    if part.get("body", {}).get("data"):
                        body = base64.urlsafe_b64decode(
                            part["body"]["data"]
                        ).decode("utf-8", errors="replace")
                        break
        return body


@register_tool
class SendEmail(GmailBase, BaseTool):
    """
    Send an email via Gmail.
    Always creates a draft first — send requires explicit confirm=True.
    This prevents accidental sends.
    """
    name = "send_email"

    async def execute(
        self,
        to: str,
        subject: str,
        body: str,
        reply_to_thread_id: str = None,
        confirm: bool = False  # Must be explicit
    ) -> ToolResult:

        # Safety gate — always draft first unless explicitly confirmed
        if not confirm:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Email not sent. Call send_email with confirm=True "
                            "after Travis has reviewed the draft. "
                            "Use draft_email first to preview.",
                    severity=Severity.LOW,
                    recoverable=True,
                    context={"to": to, "subject": subject}
                )
            )

        message = MIMEText(body, "plain")
        message["to"] = to
        message["subject"] = subject

        raw = base64.urlsafe_b64encode(
            message.as_bytes()
        ).decode("utf-8")

        send_data = {"raw": raw}
        if reply_to_thread_id:
            send_data["threadId"] = reply_to_thread_id

        service = self.get_service()

        result = await asyncio.to_thread(
            lambda: service.users().messages().send(
                userId="me",
                body=send_data
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
                "to": to,
                "subject": subject
            }
        )


@register_tool
class DraftEmail(GmailBase, BaseTool):
    """
    Generate a draft email based on context.
    Does NOT send. Returns draft for Travis to review.
    """
    name = "draft_email"

    async def execute(
        self,
        to: str,
        context: str,           # What the email is about
        tone: str = "direct",   # "direct", "formal", "casual"
        reply_to_id: str = None # If replying to existing email
    ) -> ToolResult:

        # Get previous email thread for context if replying
        thread_context = ""
        if reply_to_id:
            email_result = await ReadEmails().execute(
                filter=f"rfc822msgid:{reply_to_id}",
                include_body=True,
                limit=1
            )
            if email_result.success and email_result.data:
                prev = email_result.data[0]
                thread_context = (
                    f"Replying to email from {prev['from']}: "
                    f"{prev['body'][:500]}"
                )

        # Use FRIDAY to generate the draft
        # (This calls the LLM to write the email)
        from friday.core import generate_draft
        draft = await generate_draft(
            to=to,
            context=context,
            tone=tone,
            thread_context=thread_context
        )

        return ToolResult(
            success=True,
            data={
                "to": to,
                "subject": draft["subject"],
                "body": draft["body"],
                "ready_to_send": False,  # Always needs review
                "note": "Review and call send_email with confirm=True to send"
            }
        )
```

---

## Calendar Tools

```python
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


@register_tool
class GetCalendar(BaseTool):
    name = "get_calendar"

    async def execute(
        self,
        date: str = "today",  # "today", "tomorrow", specific date, "next_event"
        view: str = "day",    # "day", "week", "first_event"
        calendar_id: str = "primary"
    ) -> ToolResult:

        creds = Credentials.from_authorized_user_file(
            Path.home() / ".friday" / "calendar_token.json"
        )
        service = build("calendar", "v3", credentials=creds)

        time_min, time_max = self._parse_date_range(date, view)

        events_result = await asyncio.to_thread(
            lambda: service.events().list(
                calendarId=calendar_id,
                timeMin=time_min.isoformat() + "Z",
                timeMax=time_max.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
                maxResults=20 if view == "week" else 10
            ).execute()
        )

        events = [
            self._parse_event(e)
            for e in events_result.get("items", [])
        ]

        # Flag events in Travis's coding hours (10pm-4am)
        for event in events:
            start_hour = self._get_hour(event.get("start_time", ""))
            if start_hour and (start_hour >= 22 or start_hour <= 4):
                event["warning"] = "Scheduled during coding hours (10pm-4am)"

        return ToolResult(
            success=True,
            data=events,
            metadata={
                "date": date,
                "view": view,
                "event_count": len(events)
            }
        )

    def _parse_event(self, event: dict) -> dict:
        start = event.get("start", {})
        end = event.get("end", {})

        return {
            "id": event.get("id"),
            "title": event.get("summary", "(no title)"),
            "start_time": start.get("dateTime", start.get("date", "")),
            "end_time": end.get("dateTime", end.get("date", "")),
            "location": event.get("location", ""),
            "video_link": self._extract_video_link(event),
            "attendees": [a.get("email") for a in event.get("attendees", [])],
            "description": event.get("description", "")[:200],
            "is_all_day": "date" in start and "dateTime" not in start
        }

    def _extract_video_link(self, event: dict) -> Optional[str]:
        # Check Google Meet
        conf_data = event.get("conferenceData", {})
        for entry in conf_data.get("entryPoints", []):
            if entry.get("entryPointType") == "video":
                return entry.get("uri")

        # Check description for Zoom/Teams links
        desc = event.get("description", "")
        for prefix in ["https://zoom.us", "https://teams.microsoft.com"]:
            if prefix in desc:
                start = desc.find(prefix)
                end = desc.find(" ", start)
                return desc[start:end if end > 0 else start + 100]

        return None

    def _parse_date_range(self, date: str, view: str):
        from datetime import date as date_type, timedelta
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        if date == "today":
            start = today
        elif date == "tomorrow":
            start = today + timedelta(days=1)
        elif date == "next_event":
            return datetime.now(), datetime.now() + timedelta(days=7)
        else:
            start = datetime.fromisoformat(date)

        if view == "week":
            return start, start + timedelta(days=7)
        elif view == "first_event":
            return datetime.now(), start + timedelta(days=1)
        else:
            return start, start + timedelta(days=1)

    def _get_hour(self, time_str: str) -> Optional[int]:
        try:
            return datetime.fromisoformat(time_str).hour
        except Exception:
            return None


@register_tool
class CreateEvent(BaseTool):
    name = "create_event"

    async def execute(
        self,
        title: str,
        date: str,          # "2026-01-15"
        start_time: str,    # "14:00"
        duration: int = 30, # minutes
        attendees: list[str] = None,
        description: str = None,
        add_video_link: bool = True,
        confirm: bool = False
    ) -> ToolResult:

        if not confirm:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Event not created. Review details and set confirm=True:\n"
                            f"Title: {title}\nDate: {date} at {start_time}\n"
                            f"Duration: {duration} mins\nAttendees: {attendees}",
                    severity=Severity.LOW,
                    recoverable=True
                )
            )

        creds = Credentials.from_authorized_user_file(
            Path.home() / ".friday" / "calendar_token.json"
        )
        service = build("calendar", "v3", credentials=creds)

        start_dt = datetime.fromisoformat(f"{date}T{start_time}:00")
        end_dt = start_dt + timedelta(minutes=duration)

        event_body = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/London"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/London"},
            "reminders": {
                "useDefault": False,
                "overrides": [
                    {"method": "popup", "minutes": 30},
                    {"method": "popup", "minutes": 10}
                ]
            }
        }

        if attendees:
            event_body["attendees"] = [{"email": a} for a in attendees]

        if add_video_link and attendees:
            event_body["conferenceData"] = {
                "createRequest": {
                    "requestId": f"friday_{int(datetime.now().timestamp())}",
                    "conferenceSolutionKey": {"type": "hangoutsMeet"}
                }
            }

        result = await asyncio.to_thread(
            lambda: service.events().insert(
                calendarId="primary",
                body=event_body,
                conferenceDataVersion=1 if add_video_link else 0
            ).execute()
        )

        return ToolResult(
            success=True,
            data={
                "event_id": result.get("id"),
                "title": title,
                "start": start_dt.isoformat(),
                "html_link": result.get("htmlLink"),
                "video_link": result.get("conferenceData", {})
                              .get("entryPoints", [{}])[0].get("uri")
            }
        )
```

---

## Memory Tools

```python
@register_tool
class StoreLettaMemory(BaseTool):
    name = "store_letta_memory"

    async def execute(
        self,
        content: str,
        memory_type: str,  # "archival" or "recall"
        tags: list[str] = None
    ) -> ToolResult:

        from letta import create_client
        client = create_client()

        if memory_type == "archival":
            result = await asyncio.to_thread(
                lambda: client.insert_archival_memory(
                    agent_id=os.environ["LETTA_AGENT_ID"],
                    memory=content
                )
            )
        else:
            # For recall memory — store in conversation history format
            result = await asyncio.to_thread(
                lambda: client.insert_archival_memory(
                    agent_id=os.environ["LETTA_AGENT_ID"],
                    memory=f"[RECALL][{datetime.now().isoformat()}] {content}"
                )
            )

        return ToolResult(
            success=True,
            data={
                "stored": True,
                "memory_type": memory_type,
                "content_length": len(content),
                "tags": tags
            }
        )


@register_tool
class QueryLettaMemory(BaseTool):
    name = "query_letta_memory"

    async def execute(
        self,
        query: str,
        memory_type: str = "all",  # "archival", "recall", "all"
        limit: int = 5
    ) -> ToolResult:

        from letta import create_client
        client = create_client()

        results = await asyncio.to_thread(
            lambda: client.get_archival_memory(
                agent_id=os.environ["LETTA_AGENT_ID"],
                query=query,
                limit=limit
            )
        )

        return ToolResult(
            success=True,
            data=[
                {
                    "content": r.text,
                    "created_at": str(r.created_at),
                    "score": getattr(r, "score", None)
                }
                for r in results
            ],
            metadata={"query": query, "result_count": len(results)}
        )


@register_tool
class AddProject(BaseTool):
    """
    Add a new project to the memory system.
    Immediately appears in FRIDAY's active context.
    This is how Travis tells FRIDAY about new work —
    not by editing the system prompt.
    """
    name = "add_project"

    async def execute(
        self,
        name: str,
        status: str = "active",
        phase: str = "building",
        tech_stack: str = None,
        open_issues: str = None,
        next_action: str = None,
        deadline: str = None
    ) -> ToolResult:

        await sqlite.execute("""
            INSERT OR REPLACE INTO projects
            (name, status, phase, tech_stack, open_issues,
             next_action, deadline, last_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            name, status, phase, tech_stack, open_issues,
            next_action, deadline,
            datetime.now().isoformat(),
            datetime.now().isoformat()
        ])

        return ToolResult(
            success=True,
            data={
                "project": name,
                "added": True,
                "note": "Project now active in FRIDAY's context. "
                        "No prompt editing needed."
            }
        )


@register_tool
class ArchiveProject(BaseTool):
    """
    Archive a project — removes from active context automatically.
    Preserves historical memory for future reference.
    """
    name = "archive_project"

    async def execute(self, name: str, reason: str = None) -> ToolResult:

        await sqlite.execute("""
            UPDATE projects
            SET status = 'archived',
                archived_at = ?,
                archive_reason = ?
            WHERE name = ?
        """, [datetime.now().isoformat(), reason, name])

        # Preserve in Letta archival memory
        await StoreLettaMemory().execute(
            content=(
                f"Project archived: {name} on {datetime.now().date()}. "
                f"Reason: {reason or 'not specified'}. "
                f"Historical context preserved in memory."
            ),
            memory_type="archival",
            tags=[name, "archived", "project_history"]
        )

        return ToolResult(
            success=True,
            data={
                "project": name,
                "archived": True,
                "note": "Removed from active context. "
                        "Historical memory preserved."
            }
        )
```

---

## Deployment Tools

```python
@register_tool
class CheckDeploymentHealth(BaseTool):
    name = "check_deployment_health"

    KNOWN_SERVICES = {
        "diaspora-ai": {
            "type": "railway",
            "health_endpoint": os.environ.get("DIASPORA_HEALTH_URL"),
            "critical": True  # Revenue-critical — always interrupt on failure
        },
        "kluxta": {
            "type": "modal",
            "health_endpoint": os.environ.get("KLUXTA_HEALTH_URL"),
            "critical": False
        },
        "ama": {
            "type": "modal",
            "health_endpoint": os.environ.get("AMA_HEALTH_URL"),
            "critical": False
        }
    }

    async def execute(
        self,
        service: str,
        timeout: int = 10
    ) -> ToolResult:

        service_config = self.KNOWN_SERVICES.get(service)

        if not service_config:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Unknown service: {service}. "
                            f"Known: {list(self.KNOWN_SERVICES.keys())}",
                    severity=Severity.LOW,
                    recoverable=False
                )
            )

        health_url = service_config.get("health_endpoint")

        if not health_url:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.CONFIG_MISSING,
                    message=f"No health endpoint configured for {service}. "
                            f"Set {service.upper().replace('-', '_')}_HEALTH_URL "
                            f"in environment.",
                    severity=Severity.MEDIUM,
                    recoverable=False
                )
            )

        start = time.monotonic()

        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                response = await client.get(health_url)
                latency_ms = int((time.monotonic() - start) * 1000)
                is_healthy = response.status_code == 200

                result = ToolResult(
                    success=is_healthy,
                    data={
                        "service": service,
                        "healthy": is_healthy,
                        "status_code": response.status_code,
                        "latency_ms": latency_ms,
                        "url": health_url
                    }
                )

                # Auto-create incident for revenue-critical service failures
                if not is_healthy and service_config.get("critical"):
                    await AddIncident().execute(
                        service=service,
                        description=f"Health check failed: HTTP {response.status_code}",
                        severity="critical"
                    )
                    result.error = ToolError(
                        code=ErrorCode.NETWORK_ERROR,
                        message=f"CRITICAL: {service} health check failed. "
                                f"HTTP {response.status_code}. "
                                f"Revenue may be impacted.",
                        severity=Severity.CRITICAL,
                        recoverable=False,
                        escalate=True
                    )

                return result

            except httpx.TimeoutException:
                if service_config.get("critical"):
                    await AddIncident().execute(
                        service=service,
                        description="Health check timed out",
                        severity="critical"
                    )

                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.TIMEOUT,
                        message=f"{service} health check timed out after {timeout}s",
                        severity=Severity.CRITICAL if service_config.get("critical")
                                 else Severity.HIGH,
                        recoverable=True,
                        retry_after=30,
                        escalate=service_config.get("critical", False)
                    )
                )


@register_tool
class GetModalBilling(BaseTool):
    name = "get_modal_billing"

    async def execute(self, period: str = "current_month") -> ToolResult:
        result = await RunTerminal().execute(
            "modal billing current",
            timeout=30
        )

        # Parse Modal CLI output
        # Format varies — this handles common cases
        output = result.data.get("stdout", "") if result.success else ""

        return ToolResult(
            success=result.success,
            data={
                "period": period,
                "raw_output": output,
                "note": "Check Modal dashboard for full breakdown: "
                        "https://modal.com/usage"
            }
        )


@register_tool
class GetRailwayLogs(BaseTool):
    name = "get_railway_logs"

    async def execute(
        self,
        service: str,
        limit: int = 100,
        filter: str = None  # Filter string to grep
    ) -> ToolResult:

        cmd = f"railway logs --service {service} --limit {limit}"

        result = await RunTerminal().execute(cmd, timeout=30)

        if not result.success:
            return result

        logs = result.data["stdout"]

        if filter:
            filtered_lines = [
                line for line in logs.splitlines()
                if filter.lower() in line.lower()
            ]
            logs = "\n".join(filtered_lines)

        # Detect error patterns
        error_lines = [
            line for line in logs.splitlines()
            if any(p in line.lower() for p in ["error", "exception", "500", "failed"])
        ]

        return ToolResult(
            success=True,
            data={
                "service": service,
                "logs": logs,
                "error_lines": error_lines,
                "error_count": len(error_lines)
            },
            metadata={
                "has_errors": len(error_lines) > 0,
                "filter_applied": filter
            }
        )
```

---

## Mac Control Tools

```python
@register_tool
class RunAppleScript(BaseTool):
    """
    Execute AppleScript for Mac control.
    macOS only. Used for app control, system settings, UI automation.
    """
    name = "run_applescript"

    async def execute(self, script: str) -> ToolResult:

        result = await RunTerminal().execute(
            f"osascript -e '{script.replace(chr(39), chr(34))}'",
            timeout=10
        )

        return result


@register_tool
class OpenApplication(BaseTool):
    name = "open_application"

    SAFE_APPS = [
        "cursor", "vscode", "code", "terminal", "iterm",
        "safari", "chrome", "firefox", "arc",
        "finder", "notes", "calendar", "mail",
        "spotify", "slack", "zoom", "notion"
    ]

    async def execute(
        self,
        app: str,
        path: str = None,  # Optional file/folder to open with the app
        new_window: bool = False
    ) -> ToolResult:

        app_lower = app.lower()

        if not any(safe in app_lower for safe in self.SAFE_APPS):
            # Unknown app — ask first
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"'{app}' is not in the known safe apps list. "
                            f"Confirm with Travis before opening unknown applications.",
                    severity=Severity.MEDIUM,
                    recoverable=True
                )
            )

        if path:
            cmd = f'open -a "{app}" "{Path(path).expanduser()}"'
        else:
            cmd = f'open -a "{app}"'

        if new_window:
            cmd += " --new"

        return await RunTerminal().execute(cmd, timeout=10)


@register_tool
class TakeScreenshot(BaseTool):
    """
    Take a screenshot of the current screen.
    Returns base64-encoded image for vision model analysis.
    """
    name = "take_screenshot"

    async def execute(
        self,
        region: dict = None,  # {"x": 0, "y": 0, "w": 1920, "h": 1080}
        save_path: str = None
    ) -> ToolResult:

        import tempfile

        if not save_path:
            save_path = tempfile.mktemp(suffix=".png", dir="/tmp/friday")

        if region:
            cmd = (
                f"screencapture -R {region['x']},{region['y']},"
                f"{region['w']},{region['h']} {save_path}"
            )
        else:
            cmd = f"screencapture -x {save_path}"

        result = await RunTerminal().execute(cmd, timeout=5)

        if not result.success:
            return result

        # Read and encode
        async with aiofiles.open(save_path, "rb") as f:
            image_bytes = await f.read()

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        return ToolResult(
            success=True,
            data={
                "image_base64": image_b64,
                "saved_path": save_path,
                "size_bytes": len(image_bytes)
            }
        )
```

---

## Browser Tools

```python
from playwright.async_api import async_playwright, Browser, Page

# Global browser instance — reused across calls
_browser: Optional[Browser] = None
_page: Optional[Page] = None


async def get_browser_page() -> Page:
    global _browser, _page

    if not _browser:
        playwright = await async_playwright().start()
        _browser = await playwright.chromium.launch(headless=False)

    if not _page or _page.is_closed():
        _page = await _browser.new_page()

    return _page


@register_tool
class BrowserNavigate(BaseTool):
    """
    Navigate to a URL in the controlled browser.
    Returns page title and URL after navigation.
    """
    name = "browser_navigate"

    async def execute(
        self,
        url: str,
        wait_for: str = "load",  # "load", "networkidle", "domcontentloaded"
        timeout: int = 30000    # milliseconds
    ) -> ToolResult:

        page = await get_browser_page()

        try:
            response = await page.goto(
                url,
                wait_until=wait_for,
                timeout=timeout
            )

            return ToolResult(
                success=True,
                data={
                    "url": page.url,
                    "title": await page.title(),
                    "status_code": response.status if response else None
                }
            )

        except Exception as e:
            if "timeout" in str(e).lower():
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.TIMEOUT,
                        message=f"Navigation timeout for {url}",
                        severity=Severity.MEDIUM,
                        recoverable=True,
                        retry_after=5,
                        context={"url": url}
                    )
                )
            raise


@register_tool
class BrowserScreenshot(BaseTool):
    """
    Take a screenshot of the current browser state.
    Use before clicking anything — always know what you're looking at.
    """
    name = "browser_screenshot"

    async def execute(
        self,
        full_page: bool = False,
        selector: str = None  # Screenshot specific element
    ) -> ToolResult:

        page = await get_browser_page()

        kwargs = {"full_page": full_page}
        if selector:
            element = await page.query_selector(selector)
            if element:
                screenshot_bytes = await element.screenshot()
            else:
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.NOT_FOUND,
                        message=f"Element not found: {selector}",
                        severity=Severity.LOW,
                        recoverable=False
                    )
                )
        else:
            screenshot_bytes = await page.screenshot(**kwargs)

        return ToolResult(
            success=True,
            data={
                "image_base64": base64.b64encode(screenshot_bytes).decode(),
                "current_url": page.url,
                "page_title": await page.title()
            }
        )


@register_tool
class BrowserFillForm(BaseTool):
    """
    Fill a form field in the browser.
    Always screenshot before filling to confirm correct field.
    """
    name = "browser_fill_form"

    async def execute(
        self,
        selector: str,
        value: str,
        clear_first: bool = True,
        confirm_selector_visible: bool = True  # Verify element exists first
    ) -> ToolResult:

        page = await get_browser_page()

        try:
            if confirm_selector_visible:
                await page.wait_for_selector(selector, timeout=5000)

            if clear_first:
                await page.fill(selector, "")

            await page.fill(selector, value)

            return ToolResult(
                success=True,
                data={
                    "selector": selector,
                    "value_length": len(value),
                    "filled": True
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Could not fill {selector}: {str(e)}",
                    severity=Severity.MEDIUM,
                    recoverable=False,
                    context={"selector": selector}
                )
            )


@register_tool
class BrowserClick(BaseTool):
    name = "browser_click"

    # Selectors that are dangerous to click without confirmation
    DANGEROUS_SELECTORS = [
        "submit", "pay", "confirm", "delete", "remove",
        "purchase", "buy", "checkout", "place order"
    ]

    async def execute(
        self,
        selector: str,
        confirm_if_dangerous: bool = False,
        wait_for_navigation: bool = False
    ) -> ToolResult:

        # Safety check for dangerous buttons
        selector_lower = selector.lower()
        is_dangerous = any(d in selector_lower for d in self.DANGEROUS_SELECTORS)

        if is_dangerous and not confirm_if_dangerous:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Dangerous click detected: '{selector}'. "
                            f"Set confirm_if_dangerous=True after Travis confirms.",
                    severity=Severity.HIGH,
                    recoverable=True,
                    escalate=True,
                    context={"selector": selector}
                )
            )

        page = await get_browser_page()

        try:
            if wait_for_navigation:
                async with page.expect_navigation():
                    await page.click(selector)
            else:
                await page.click(selector)

            return ToolResult(
                success=True,
                data={
                    "selector": selector,
                    "clicked": True,
                    "current_url": page.url
                }
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Could not click {selector}: {str(e)}",
                    severity=Severity.MEDIUM,
                    recoverable=False
                )
            )
```

---

## Screenpipe Tools

```python
@register_tool
class SearchScreenpipe(BaseTool):
    """
    Search Screenpipe's local index of Travis's Mac activity.
    This is passive context — everything Travis has done on his Mac
    is indexed and searchable without him manually documenting anything.
    """
    name = "search_screenpipe"

    SCREENPIPE_API = "http://localhost:3030"  # Screenpipe local API

    async def execute(
        self,
        query: str,
        content_type: str = "all",   # "screen", "audio", "browser_history", "all"
        timeframe: str = "today",    # "today", "this_week", "last_7_days", custom
        limit: int = 10
    ) -> ToolResult:

        start_time, end_time = self._parse_timeframe(timeframe)

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    f"{self.SCREENPIPE_API}/search",
                    params={
                        "q": query,
                        "content_type": content_type,
                        "start_time": start_time.isoformat(),
                        "end_time": end_time.isoformat(),
                        "limit": limit
                    },
                    timeout=15
                )
                response.raise_for_status()
                data = response.json()

                return ToolResult(
                    success=True,
                    data=data.get("data", []),
                    metadata={
                        "query": query,
                        "timeframe": timeframe,
                        "result_count": len(data.get("data", []))
                    }
                )

            except httpx.ConnectError:
                return ToolResult(
                    success=False,
                    error=ToolError(
                        code=ErrorCode.NETWORK_ERROR,
                        message="Screenpipe is not running. "
                                "Start it with: screenpipe",
                        severity=Severity.LOW,
                        recoverable=False,
                        context={"fix": "Run 'screenpipe' in terminal to start"}
                    )
                )

    def _parse_timeframe(self, timeframe: str) -> tuple[datetime, datetime]:
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        timeframes = {
            "today": (today_start, now),
            "this_week": (today_start - timedelta(days=7), now),
            "last_7_days": (now - timedelta(days=7), now),
            "last_hour": (now - timedelta(hours=1), now),
            "last_24h": (now - timedelta(hours=24), now),
        }

        return timeframes.get(timeframe, (today_start, now))
```

---

## Notification Tools

```python
@register_tool
class SendDesktopNotification(BaseTool):
    """
    Send a macOS desktop notification.
    Used for non-interrupting alerts.
    """
    name = "send_desktop_notification"

    async def execute(
        self,
        title: str,
        body: str,
        urgency: str = "normal",   # "low", "normal", "critical"
        sound: bool = True
    ) -> ToolResult:

        # Use osascript for macOS notifications
        sound_str = "with sound" if sound else ""
        script = (
            f'display notification "{body}" '
            f'with title "{title}" {sound_str}'
        )

        return await RunAppleScript().execute(script)


@register_tool
class CreateReminder(BaseTool):
    name = "create_reminder"

    async def execute(
        self,
        message: str,
        due_date: str,   # ISO format or natural language
        time: str = None,
        priority: str = "normal",  # "low", "normal", "high", "critical"
        repeat: str = None         # "daily", "weekly", None
    ) -> ToolResult:

        # Parse natural language dates
        if due_date in ("tomorrow", "today"):
            base = datetime.now()
            if due_date == "tomorrow":
                base += timedelta(days=1)
            due_dt = base.replace(hour=9, minute=0, second=0, microsecond=0)
        else:
            due_dt = datetime.fromisoformat(due_date)

        if time:
            hour, minute = map(int, time.split(":"))
            due_dt = due_dt.replace(hour=hour, minute=minute)

        await sqlite.execute("""
            INSERT INTO reminders
            (message, due_date, priority, delivered, resolved)
            VALUES (?, ?, ?, FALSE, FALSE)
        """, [message, due_dt.isoformat(), priority])

        return ToolResult(
            success=True,
            data={
                "message": message,
                "due": due_dt.isoformat(),
                "priority": priority
            }
        )
```

---

## Agent Dispatch Tools

```python
@register_tool
class DispatchAgent(BaseTool):
    """
    The most important tool in the system.
    FRIDAY Core uses this to delegate to specialist agents.
    This is the routing mechanism — everything flows through here.
    """
    name = "dispatch_agent"

    async def execute(
        self,
        agent: str,
        task: str,
        context: str = None,
        output_format: str = None,
        priority: str = "normal",       # "low", "normal", "high", "critical"
        depends_on: str = None,         # Wait for this task_id to complete first
        timeout: int = 300              # Max seconds for agent to complete
    ) -> ToolResult:

        from friday.agents import get_agent

        agent_instance = get_agent(agent)

        if not agent_instance:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Unknown agent: {agent}. "
                            f"Check AGENT_TOOL_SCOPE for valid agent names.",
                    severity=Severity.HIGH,
                    recoverable=False
                )
            )

        # Load skills for this agent
        skill_context = await skill_loader.load_for_agent(agent, task)

        full_task = task
        if context:
            full_task = f"{task}\n\nContext:\n{context}"
        if skill_context:
            full_task = f"SKILL KNOWLEDGE:\n{skill_context}\n\nTASK:\n{full_task}"
        if output_format:
            full_task += f"\n\nOutput format: {output_format}"

        try:
            result = await asyncio.wait_for(
                agent_instance.run(task=full_task),
                timeout=timeout
            )

            return ToolResult(
                success=result.success,
                data={
                    "agent": agent,
                    "task": task,
                    "output": result.output,
                    "tools_called": result.tools_called
                }
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.TIMEOUT,
                    message=f"Agent {agent} timed out after {timeout}s on task: {task[:80]}",
                    severity=Severity.MEDIUM,
                    recoverable=True,
                    retry_after=0,
                    context={"agent": agent, "task": task[:80]}
                )
            )
```

---

## Utility Tools

```python
@register_tool
class FormatForVoice(BaseTool):
    """
    Condense text output for voice delivery.
    Strips markdown, shortens aggressively, makes it speakable.
    """
    name = "format_for_voice"

    async def execute(
        self,
        text: str,
        max_sentences: int = 3,
        preserve_numbers: bool = True
    ) -> ToolResult:

        import re

        # Strip markdown
        clean = re.sub(r'```[\s\S]*?```', '[code block]', text)
        clean = re.sub(r'`[^`]+`', '', clean)
        clean = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean)
        clean = re.sub(r'\*([^*]+)\*', r'\1', clean)
        clean = re.sub(r'#+\s', '', clean)
        clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean)
        clean = re.sub(r'^[-*+]\s+', '', clean, flags=re.MULTILINE)

        # Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', clean.strip())

        # Take first N meaningful sentences
        meaningful = [s.strip() for s in sentences
                      if len(s.strip()) > 10][:max_sentences]

        voice_text = " ".join(meaningful)

        return ToolResult(
            success=True,
            data={
                "voice_text": voice_text,
                "word_count": len(voice_text.split()),
                "original_length": len(text),
                "compressed": len(voice_text) < len(text) * 0.5
            }
        )


@register_tool
class Wait(BaseTool):
    """
    Wait for a specified number of seconds.
    Used for rate limit recovery, retry delays.
    Max 300 seconds — longer waits should be async tasks.
    """
    name = "wait"

    async def execute(self, seconds: int) -> ToolResult:

        if seconds > 300:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message="Wait time > 300s not allowed in synchronous flow. "
                            "Use a scheduled task instead.",
                    severity=Severity.LOW,
                    recoverable=True
                )
            )

        await asyncio.sleep(seconds)

        return ToolResult(
            success=True,
            data={"waited_seconds": seconds}
        )
```

---

## MCP Server Setup

All tools are exposed as MCP servers so any model — Ollama,
Claude API, future models — can use the same tool layer
without rewriting a single tool.

```python
# friday/mcp/server.py

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
import json


app = Server("friday-tools")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Expose all registered tools as MCP tools."""
    tools = []

    for name, tool_class in TOOL_REGISTRY.items():
        tool_instance = tool_class()
        import inspect
        sig = inspect.signature(tool_instance.execute)

        # Build input schema from function signature
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue

            param_type = "string"
            if param.annotation in (int,):
                param_type = "integer"
            elif param.annotation in (bool,):
                param_type = "boolean"
            elif param.annotation in (list, list[str]):
                param_type = "array"

            properties[param_name] = {"type": param_type}

            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        tools.append(Tool(
            name=name,
            description=tool_instance.description or tool_class.__doc__ or "",
            inputSchema={
                "type": "object",
                "properties": properties,
                "required": required
            }
        ))

    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Execute a tool call from any MCP-compatible model."""

    tool_class = TOOL_REGISTRY.get(name)
    if not tool_class:
        return [TextContent(
            type="text",
            text=json.dumps({
                "success": False,
                "error": f"Tool not found: {name}"
            })
        )]

    tool_instance = tool_class()
    result = await tool_instance(**arguments)

    return [TextContent(
        type="text",
        text=json.dumps({
            "success": result.success,
            "data": result.data,
            "error": {
                "code": result.error.code.value,
                "message": result.error.message,
                "severity": result.error.severity.value,
                "recoverable": result.error.recoverable,
                "escalate": result.error.escalate
            } if result.error else None,
            "metadata": result.metadata,
            "duration_ms": result.duration_ms
        }, default=str)
    )]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Tool Testing

Every tool gets unit tested before it touches production.

```python
# friday/tests/test_tools.py

import pytest
import asyncio
from unittest.mock import patch, AsyncMock


class TestSearchWeb:

    @pytest.mark.asyncio
    async def test_successful_search(self):
        with patch("friday.tools.web.TavilyClient") as mock_client:
            mock_client.return_value.search.return_value = {
                "results": [
                    {"title": "Test", "url": "https://test.com",
                     "content": "Test content", "score": 0.9}
                ]
            }

            tool = SearchWeb()
            result = await tool.execute(query="test query")

            assert result.success is True
            assert len(result.data) == 1
            assert result.data[0]["title"] == "Test"

    @pytest.mark.asyncio
    async def test_rate_limit_returns_correct_error(self):
        with patch("friday.tools.web.TavilyClient") as mock_client:
            mock_client.return_value.search.side_effect = Exception("429 rate limit")

            tool = SearchWeb()
            result = await tool.execute(query="test")

            assert result.success is False
            assert result.error.code == ErrorCode.RATE_LIMIT
            assert result.error.recoverable is True
            assert result.error.retry_after == 60


class TestGitCommit:

    @pytest.mark.asyncio
    async def test_blocks_secret_in_diff(self):
        with patch("friday.tools.git.RunTerminal") as mock_terminal:
            mock_terminal.return_value.execute = AsyncMock(return_value=ToolResult(
                success=True,
                data={"stdout": "sk_live_xxxxxxxxxxxx"}
            ))

            tool = GitCommit()
            result = await tool.execute(
                message="feat: add payment",
                add_all=True
            )

            assert result.success is False
            assert result.error.code == ErrorCode.VALIDATION_ERROR
            assert result.error.escalate is True
            assert "secret" in result.error.message.lower()


class TestRunTerminal:

    @pytest.mark.asyncio
    async def test_blocks_dangerous_command(self):
        tool = RunTerminal()
        result = await tool.execute(
            command="rm -rf /important/stuff",
            confirmed_dangerous=False
        )

        assert result.success is False
        assert result.error.code == ErrorCode.PERMISSION_DENIED
        assert result.error.severity == Severity.HIGH

    @pytest.mark.asyncio
    async def test_successful_command(self):
        tool = RunTerminal()
        result = await tool.execute(command="echo hello")

        assert result.success is True
        assert "hello" in result.data["stdout"]


class TestPaystackWebhookVerification:
    """
    These are the tests that would have prevented
    the duplicate charge incident.
    """

    def test_valid_signature_passes(self):
        from friday.tools.payment import verify_paystack_signature
        import hmac
        import hashlib

        secret = "test_secret"
        payload = b'{"event": "charge.success"}'
        expected_sig = hmac.new(
            secret.encode(), payload, hashlib.sha512
        ).hexdigest()

        with patch.dict(os.environ, {"PAYSTACK_WEBHOOK_SECRET": secret}):
            assert verify_paystack_signature(payload, expected_sig) is True

    def test_invalid_signature_fails(self):
        from friday.tools.payment import verify_paystack_signature

        with patch.dict(os.environ, {"PAYSTACK_WEBHOOK_SECRET": "secret"}):
            assert verify_paystack_signature(b"payload", "wrong_sig") is False

    def test_missing_secret_raises_config_error(self):
        from friday.tools.payment import verify_paystack_signature

        with pytest.raises(Exception) as exc:
            verify_paystack_signature(b"payload", "sig")
        assert "PAYSTACK_WEBHOOK_SECRET" in str(exc.value)
```

---

*Tools are the hands. They should do exactly what they're told,
return structured results, and never have opinions.

The opinions live in the skills.
The decisions live in the agents.
The hands just do the work.*
