"""Core types for the FRIDAY system. Every tool returns ToolResult. Every agent returns AgentResponse."""

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
from datetime import datetime


class ErrorCode(Enum):
    RATE_LIMIT = "rate_limit"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    AUTH_FAILED = "auth_failed"
    NOT_FOUND = "not_found"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    COMMAND_FAILED = "command_failed"
    PROCESS_TIMEOUT = "process_timeout"
    PARSE_ERROR = "parse_error"
    VALIDATION_ERROR = "validation_error"
    EMPTY_RESULT = "empty_result"
    UNKNOWN = "unknown"
    CONFIG_MISSING = "config_missing"
    DATA_VALIDATION = "data_validation"


class Severity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ToolError:
    code: ErrorCode
    message: str
    severity: Severity
    recoverable: bool
    retry_after: Optional[int] = None
    context: dict = field(default_factory=dict)

    @property
    def should_interrupt(self) -> bool:
        return self.severity == Severity.CRITICAL


@dataclass
class ToolResult:
    success: bool
    data: Optional[Any] = None
    error: Optional[ToolError] = None
    metadata: dict = field(default_factory=dict)
    duration_ms: Optional[int] = None
    called_at: datetime = field(default_factory=datetime.now)

    def unwrap(self) -> Any:
        if not self.success:
            raise ToolExecutionError(self.error)
        return self.data


class ToolExecutionError(Exception):
    def __init__(self, error: Optional[ToolError]):
        self.tool_error = error
        super().__init__(error.message if error else "Unknown tool error")


@dataclass
class AgentResponse:
    agent_name: str
    success: bool
    result: str
    data: Optional[Any] = None
    error: Optional[str] = None
    tools_called: list[str] = field(default_factory=list)
    duration_ms: Optional[int] = None
