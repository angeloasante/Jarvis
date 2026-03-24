"""Terminal tools — run shell commands, background processes, process management.

Safety-checked: dangerous patterns are blocked. Timeout enforced.
"""

import asyncio
import signal
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

# Commands that should never be run without explicit confirmation
DANGEROUS_PATTERNS = [
    "rm -rf /", "rm -rf ~", "rm -rf .", "sudo rm",
    "mkfs", "dd if=/dev/", "> /dev/sd",
    ":(){ :|:& };:",  # fork bomb
    "format c:", "fdisk",
]

MAX_OUTPUT_CHARS = 10000
DEFAULT_TIMEOUT = 30

# Track background processes
_RUNNING_PROCESSES: dict[str, asyncio.subprocess.Process] = {}


async def run_command(
    command: str,
    cwd: str = None,
    timeout: int = DEFAULT_TIMEOUT,
    env: dict = None,
) -> ToolResult:
    """Run a shell command and return output. Supports cwd and extra env vars."""
    # Safety check
    cmd_lower = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.VALIDATION_ERROR,
                    message=f"Blocked dangerous command pattern: {pattern}",
                    severity=Severity.CRITICAL,
                    recoverable=False,
                ),
            )

    import os
    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=run_env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        stdout_str = stdout.decode(errors="replace")[:MAX_OUTPUT_CHARS]
        stderr_str = stderr.decode(errors="replace")[:MAX_OUTPUT_CHARS]

        success = proc.returncode == 0

        return ToolResult(
            success=success,
            data={
                "stdout": stdout_str,
                "stderr": stderr_str,
                "return_code": proc.returncode,
            },
            metadata={"command": command, "cwd": cwd or "."},
            error=None if success else ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=f"Command exited with code {proc.returncode}",
                severity=Severity.MEDIUM,
                recoverable=False,
                context={"stderr": stderr_str[:500]},
            ),
        )
    except asyncio.TimeoutError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.PROCESS_TIMEOUT,
                message=f"Command timed out after {timeout}s: {command[:80]}",
                severity=Severity.MEDIUM,
                recoverable=True,
                retry_after=5,
            ),
        )
    except FileNotFoundError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Command not found. Is it installed?",
                severity=Severity.MEDIUM,
                recoverable=False,
                context={"command": command.split()[0]},
            ),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=False,
            ),
        )


async def run_background(
    command: str,
    cwd: str = None,
    label: str = None,
    max_runtime: int = 3600,
) -> ToolResult:
    """Run a long-running process in the background. Returns a process_id for monitoring.

    Use for: dev servers, watch modes, long builds, etc.
    Auto-terminates after max_runtime seconds (default 1 hour).
    """
    from datetime import datetime

    process_id = label or f"proc_{int(datetime.now().timestamp())}"

    if process_id in _RUNNING_PROCESSES:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.VALIDATION_ERROR,
                message=f"Process '{process_id}' already running. Kill it first or use a different label.",
                severity=Severity.LOW,
                recoverable=True,
            ),
        )

    try:
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )

        _RUNNING_PROCESSES[process_id] = process

        # Auto-kill after max_runtime
        async def auto_kill():
            await asyncio.sleep(max_runtime)
            if process_id in _RUNNING_PROCESSES:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                _RUNNING_PROCESSES.pop(process_id, None)

        asyncio.create_task(auto_kill())

        return ToolResult(
            success=True,
            data={
                "process_id": process_id,
                "pid": process.pid,
                "command": command,
                "max_runtime": max_runtime,
            },
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.HIGH,
                recoverable=False,
            ),
        )


async def get_process(process_id: str) -> ToolResult:
    """Check status and get output from a background process."""
    process = _RUNNING_PROCESSES.get(process_id)

    if not process:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Process '{process_id}' not found. It may have completed or been killed.",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )

    still_running = process.returncode is None

    if not still_running:
        stdout, stderr = await process.communicate()
        _RUNNING_PROCESSES.pop(process_id, None)
        return ToolResult(
            success=True,
            data={
                "process_id": process_id,
                "running": False,
                "return_code": process.returncode,
                "stdout": stdout.decode(errors="replace")[:MAX_OUTPUT_CHARS],
                "stderr": stderr.decode(errors="replace")[:MAX_OUTPUT_CHARS],
            },
        )

    return ToolResult(
        success=True,
        data={
            "process_id": process_id,
            "running": True,
            "pid": process.pid,
        },
    )


async def kill_process(process_id: str) -> ToolResult:
    """Kill a running background process."""
    process = _RUNNING_PROCESSES.get(process_id)

    if not process:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.NOT_FOUND,
                message=f"Process '{process_id}' not found",
                severity=Severity.LOW,
                recoverable=False,
            ),
        )

    try:
        process.send_signal(signal.SIGTERM)
        await asyncio.sleep(2)
        if process.returncode is None:
            process.kill()
    except ProcessLookupError:
        pass

    _RUNNING_PROCESSES.pop(process_id, None)

    return ToolResult(
        success=True,
        data={"process_id": process_id, "killed": True},
    )


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "run_command": {
        "fn": run_command,
        "schema": {
            "type": "function",
            "function": {
                "name": "run_command",
                "description": "Run a shell command. Use for git, npm, python, system commands. Supports cwd and env vars.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to execute"},
                        "cwd": {"type": "string", "description": "Working directory (optional)"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                    },
                    "required": ["command"],
                },
            },
        },
    },
    "run_background": {
        "fn": run_background,
        "schema": {
            "type": "function",
            "function": {
                "name": "run_background",
                "description": "Run a long process in the background (dev servers, watch modes, builds). Returns process_id for monitoring.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Shell command to run"},
                        "cwd": {"type": "string", "description": "Working directory"},
                        "label": {"type": "string", "description": "Label for the process (e.g. 'dev_server')"},
                        "max_runtime": {"type": "integer", "description": "Auto-kill after N seconds (default 3600)"},
                    },
                    "required": ["command"],
                },
            },
        },
    },
    "get_process": {
        "fn": get_process,
        "schema": {
            "type": "function",
            "function": {
                "name": "get_process",
                "description": "Check status and get output from a background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "process_id": {"type": "string", "description": "Process ID or label from run_background"},
                    },
                    "required": ["process_id"],
                },
            },
        },
    },
    "kill_process": {
        "fn": kill_process,
        "schema": {
            "type": "function",
            "function": {
                "name": "kill_process",
                "description": "Kill a running background process.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "process_id": {"type": "string", "description": "Process ID or label to kill"},
                    },
                    "required": ["process_id"],
                },
            },
        },
    },
}
