"""File system tools — read, write, list, search.

Enhanced with line ranges, append mode, depth control, and content search.
"""

import fnmatch
from datetime import datetime
from pathlib import Path

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity

# Directories to skip when searching
SKIP_DIRS = {
    "node_modules", ".git", ".venv", "__pycache__",
    ".next", "dist", "build", ".cache", ".tox",
    "venv", "env", ".mypy_cache", ".pytest_cache",
}


async def read_file(
    path: str,
    start_line: int = None,
    end_line: int = None,
    encoding: str = "utf-8",
) -> ToolResult:
    """Read a file. Optionally read a specific line range (1-indexed)."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"File not found: {path}",
                    severity=Severity.MEDIUM,
                    recoverable=False,
                ),
            )
        content = p.read_text(encoding=encoding, errors="replace")

        if start_line or end_line:
            lines = content.splitlines()
            s = max(0, (start_line or 1) - 1)
            e = min(len(lines), end_line or len(lines))
            content = "\n".join(lines[s:e])
            line_info = f"lines {s + 1}-{e} of {len(lines)}"
        else:
            line_info = f"{len(content.splitlines())} lines"

        return ToolResult(
            success=True,
            data=content,
            metadata={
                "path": str(p),
                "size": len(content),
                "lines": line_info,
                "extension": p.suffix,
            },
        )
    except PermissionError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.PERMISSION_DENIED,
                message=f"Permission denied: {path}",
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )
    except UnicodeDecodeError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.PARSE_ERROR,
                message=f"Cannot read {path} as {encoding} — binary file?",
                severity=Severity.LOW,
                recoverable=True,
                context={"suggested_fix": "Try encoding='latin-1'"},
            ),
        )


async def write_file(
    path: str,
    content: str,
    append: bool = False,
    create_parents: bool = True,
) -> ToolResult:
    """Write content to a file. Creates parent dirs if needed. Set append=True to add to existing file."""
    try:
        p = Path(path).expanduser().resolve()
        if create_parents:
            p.parent.mkdir(parents=True, exist_ok=True)

        mode = "a" if append else "w"
        with open(p, mode) as f:
            f.write(content)

        action = "appended" if append else "written"
        return ToolResult(
            success=True,
            data=f"{action.title()} {len(content)} chars to {p}",
            metadata={
                "path": str(p),
                "bytes_written": len(content.encode()),
                "mode": "append" if append else "overwrite",
            },
        )
    except PermissionError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.PERMISSION_DENIED,
                message=f"Permission denied: {path}",
                severity=Severity.HIGH,
                recoverable=False,
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


async def list_directory(
    path: str = ".",
    depth: int = 1,
    pattern: str = None,
    include_hidden: bool = False,
) -> ToolResult:
    """List contents of a directory. Supports depth, pattern filter, and hidden files."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"Not a directory: {path}",
                    severity=Severity.LOW,
                    recoverable=False,
                ),
            )

        entries = []
        _scan_dir(p, p, depth, 0, include_hidden, pattern, entries)

        return ToolResult(
            success=True,
            data=entries,
            metadata={"path": str(p), "count": len(entries)},
        )
    except PermissionError:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.PERMISSION_DENIED,
                message=f"Permission denied: {path}",
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )
    except Exception as e:
        return ToolResult(success=False, data=str(e))


def _scan_dir(root, current, max_depth, current_depth, include_hidden, pattern, items):
    """Recursively scan a directory up to max_depth."""
    if current_depth >= max_depth:
        return
    try:
        for item in sorted(current.iterdir()):
            if not include_hidden and item.name.startswith("."):
                continue
            if item.is_dir() and item.name in SKIP_DIRS:
                continue
            if pattern and not item.is_dir() and not fnmatch.fnmatch(item.name, pattern):
                continue

            relative = str(item.relative_to(root))
            entry = {
                "name": relative,
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size"] = item.stat().st_size

            items.append(entry)

            if item.is_dir():
                _scan_dir(root, item, max_depth, current_depth + 1,
                          include_hidden, pattern, items)
    except PermissionError:
        pass


async def search_files(
    directory: str,
    query: str,
    search_type: str = "name",
    file_types: list[str] = None,
    max_results: int = 20,
) -> ToolResult:
    """Search for files by name or content.

    search_type: 'name' (filename match), 'content' (grep-like), 'both'
    file_types: filter by extension e.g. ['.py', '.ts']
    """
    try:
        base = Path(directory).expanduser().resolve()
        if not base.exists():
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.FILE_NOT_FOUND,
                    message=f"Directory not found: {directory}",
                    severity=Severity.LOW,
                    recoverable=False,
                ),
            )

        extensions = set(file_types) if file_types else None
        results = []

        # Normalise query so spaces / underscores / dashes are equivalent
        # for filename matching — filenames in FRIDAY's output dirs are
        # slugged ("richard_asante_…") but the LLM usually searches with
        # spaces ("Richard Asante").
        def _norm(s: str) -> str:
            import re as _re
            return _re.sub(r"[\s_\-]+", "_", s.lower())
        q_norm = _norm(query)

        for fp in base.rglob("*"):
            if not fp.is_file():
                continue
            if any(skip in fp.parts for skip in SKIP_DIRS):
                continue
            if extensions and fp.suffix not in extensions:
                continue

            matched = False
            match_context = None

            # Name search — try raw + normalised forms
            if search_type in ("name", "both"):
                name_lower = fp.name.lower()
                if query.lower() in name_lower or q_norm in _norm(fp.name):
                    matched = True
                    match_context = "filename match"

            # Content search
            if search_type in ("content", "both") and not matched:
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                    if query.lower() in text.lower():
                        matched = True
                        for i, line in enumerate(text.splitlines(), 1):
                            if query.lower() in line.lower():
                                match_context = f"line {i}: {line.strip()[:100]}"
                                break
                except Exception:
                    pass

            if matched:
                results.append({
                    "path": str(fp.relative_to(base)),
                    "full_path": str(fp),
                    "size": fp.stat().st_size,
                    "match": match_context,
                })

            if len(results) >= max_results:
                break

        return ToolResult(
            success=True,
            data=results,
            metadata={"query": query, "search_type": search_type, "count": len(results)},
        )
    except Exception as e:
        return ToolResult(success=False, data=str(e))


async def convert_file_format(
    path: str,
    target_format: str,
) -> ToolResult:
    """Convert a file to another format (docx, md, txt, pdf)."""
    try:
        from friday.agents.deep_research_agent import convert_file, SUPPORTED_FORMATS
        target_format = target_format.lower().strip(".")
        if target_format not in SUPPORTED_FORMATS:
            return ToolResult(
                success=False,
                error=ToolError(
                    code=ErrorCode.INVALID_INPUT,
                    message=f"Unsupported format: {target_format}. Supported: {', '.join(SUPPORTED_FORMATS)}",
                    severity=Severity.LOW,
                    recoverable=True,
                ),
            )
        dest = convert_file(path, target_format)
        return ToolResult(
            success=True,
            data=f"Converted to {dest}",
            metadata={"source": path, "destination": str(dest), "format": target_format},
        )
    except FileNotFoundError as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.FILE_NOT_FOUND,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )
    except Exception as e:
        return ToolResult(
            success=False,
            error=ToolError(
                code=ErrorCode.COMMAND_FAILED,
                message=str(e),
                severity=Severity.MEDIUM,
                recoverable=False,
            ),
        )


# ── Tool Schemas ─────────────────────────────────────────────────────────────

TOOL_SCHEMAS = {
    "read_file": {
        "fn": read_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file's contents. Use start_line/end_line for large files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the file"},
                        "start_line": {"type": "integer", "description": "Start line (1-indexed, optional)"},
                        "end_line": {"type": "integer", "description": "End line (1-indexed, optional)"},
                    },
                    "required": ["path"],
                },
            },
        },
    },
    "write_file": {
        "fn": write_file,
        "schema": {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file. Set append=True to add to existing file instead of overwriting.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to write to"},
                        "content": {"type": "string", "description": "Content to write"},
                        "append": {"type": "boolean", "description": "Append instead of overwrite (default false)"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
    },
    "list_directory": {
        "fn": list_directory,
        "schema": {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List files and folders in a directory. Supports depth, pattern filter, hidden files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path (default: current dir)"},
                        "depth": {"type": "integer", "description": "How deep to scan (default 1)"},
                        "pattern": {"type": "string", "description": "Filename pattern filter e.g. '*.py'"},
                        "include_hidden": {"type": "boolean", "description": "Include dotfiles (default false)"},
                    },
                    "required": [],
                },
            },
        },
    },
    "search_files": {
        "fn": search_files,
        "schema": {
            "type": "function",
            "function": {
                "name": "search_files",
                "description": "Search for files by name or content in a directory tree.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {"type": "string", "description": "Root directory to search"},
                        "query": {"type": "string", "description": "Search query (filename or content text)"},
                        "search_type": {
                            "type": "string",
                            "enum": ["name", "content", "both"],
                            "description": "Search by filename, file content, or both (default: name)",
                        },
                        "file_types": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Filter by extensions e.g. ['.py', '.ts']",
                        },
                        "max_results": {"type": "integer", "description": "Max results (default 20)"},
                    },
                    "required": ["directory", "query"],
                },
            },
        },
    },
    "convert_file": {
        "fn": convert_file_format,
        "schema": {
            "type": "function",
            "function": {
                "name": "convert_file",
                "description": "Convert a file to another format. Supports: docx, md, txt, pdf.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to the source file"},
                        "target_format": {
                            "type": "string",
                            "enum": ["docx", "md", "txt", "pdf"],
                            "description": "Target format to convert to",
                        },
                    },
                    "required": ["path", "target_format"],
                },
            },
        },
    },
}
