"""PDF tools — read, merge, split, extract, create, encrypt, watermark.

Covers:
  - Read/extract text from PDFs (including tables)
  - Merge multiple PDFs into one
  - Split a PDF into individual pages
  - Rotate pages
  - Extract metadata
  - Encrypt/decrypt PDFs
  - Add watermarks
  - Extract images (via CLI poppler if available)
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from friday.core.types import ToolResult, ToolError, ErrorCode, Severity


# ═════════════════════════════════════════════════════════════════════════════
# READ / EXTRACT
# ═════════════════════════════════════════════════════════════════════════════


async def pdf_read(
    file_path: str,
    pages: str = "all",
    extract_tables: bool = False,
) -> ToolResult:
    """Extract text (and optionally tables) from a PDF.

    Args:
        file_path: Path to the PDF file.
        pages: "all", a single page "3", or a range "1-5".
        extract_tables: If True, also extract tables as lists of rows.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))

    def _extract():
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            total_pages = len(pdf.pages)

            # Parse page range
            if pages == "all":
                page_indices = list(range(total_pages))
            elif "-" in pages:
                start, end = pages.split("-", 1)
                start = max(0, int(start) - 1)
                end = min(total_pages, int(end))
                page_indices = list(range(start, end))
            else:
                idx = int(pages) - 1
                if 0 <= idx < total_pages:
                    page_indices = [idx]
                else:
                    return {"error": f"Page {pages} out of range (1-{total_pages})"}

            result = {"total_pages": total_pages, "pages_read": len(page_indices), "text": ""}
            tables_data = []

            for i in page_indices:
                page = pdf.pages[i]
                text = page.extract_text() or ""
                result["text"] += f"\n--- Page {i + 1} ---\n{text}"

                if extract_tables:
                    page_tables = page.extract_tables()
                    for j, table in enumerate(page_tables):
                        tables_data.append({
                            "page": i + 1,
                            "table_index": j + 1,
                            "rows": table,
                        })

            result["text"] = result["text"].strip()
            if extract_tables:
                result["tables"] = tables_data
                result["table_count"] = len(tables_data)

            # Truncate if too long for the model
            if len(result["text"]) > 15000:
                result["text"] = result["text"][:15000] + "\n\n[... truncated — use page ranges to read more]"
                result["truncated"] = True

            return result

    try:
        data = await asyncio.to_thread(_extract)
        if "error" in data:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.DATA_VALIDATION, message=data["error"],
                severity=Severity.LOW, recoverable=True))
        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"PDF read failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def pdf_metadata(file_path: str) -> ToolResult:
    """Get PDF metadata — title, author, subject, page count, etc."""
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))

    def _meta():
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        meta = reader.metadata or {}
        return {
            "pages": len(reader.pages),
            "title": getattr(meta, "title", None),
            "author": getattr(meta, "author", None),
            "subject": getattr(meta, "subject", None),
            "creator": getattr(meta, "creator", None),
            "producer": getattr(meta, "producer", None),
            "encrypted": reader.is_encrypted,
            "file_size_kb": round(path.stat().st_size / 1024, 1),
        }

    try:
        data = await asyncio.to_thread(_meta)
        return ToolResult(success=True, data=data)
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Metadata read failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# MERGE
# ═════════════════════════════════════════════════════════════════════════════


async def pdf_merge(file_paths: list[str], output_path: str) -> ToolResult:
    """Merge multiple PDFs into one.

    Args:
        file_paths: List of PDF file paths to merge (in order).
        output_path: Where to save the merged PDF.
    """
    paths = [Path(f).expanduser().resolve() for f in file_paths]
    for p in paths:
        if not p.exists():
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {p}",
                severity=Severity.MEDIUM, recoverable=False))

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    def _merge():
        from pypdf import PdfWriter, PdfReader
        writer = PdfWriter()
        total = 0
        for p in paths:
            reader = PdfReader(str(p))
            for page in reader.pages:
                writer.add_page(page)
                total += 1
        with open(str(out), "wb") as f:
            writer.write(f)
        return total

    try:
        total = await asyncio.to_thread(_merge)
        return ToolResult(success=True, data={
            "output": str(out),
            "total_pages": total,
            "files_merged": len(paths),
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Merge failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# SPLIT
# ═════════════════════════════════════════════════════════════════════════════


async def pdf_split(
    file_path: str,
    output_dir: str,
    pages: str = "all",
) -> ToolResult:
    """Split a PDF into individual page files.

    Args:
        file_path: Path to the PDF to split.
        output_dir: Directory to save individual page PDFs.
        pages: "all", or a range like "1-5" to split only those pages.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    def _split():
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(str(path))
        total = len(reader.pages)

        if pages == "all":
            indices = list(range(total))
        elif "-" in pages:
            start, end = pages.split("-", 1)
            indices = list(range(max(0, int(start) - 1), min(total, int(end))))
        else:
            indices = [int(pages) - 1]

        outputs = []
        stem = path.stem
        for i in indices:
            writer = PdfWriter()
            writer.add_page(reader.pages[i])
            out_path = out_dir / f"{stem}_page_{i + 1}.pdf"
            with open(str(out_path), "wb") as f:
                writer.write(f)
            outputs.append(str(out_path))

        return outputs

    try:
        outputs = await asyncio.to_thread(_split)
        return ToolResult(success=True, data={
            "files_created": len(outputs),
            "output_dir": str(out_dir),
            "files": outputs,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Split failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# ROTATE
# ═════════════════════════════════════════════════════════════════════════════


async def pdf_rotate(
    file_path: str,
    degrees: int,
    pages: str = "all",
    output_path: Optional[str] = None,
) -> ToolResult:
    """Rotate pages in a PDF.

    Args:
        file_path: Path to the PDF.
        degrees: Rotation angle (90, 180, 270).
        pages: "all" or specific page like "1" or range "1-3".
        output_path: Where to save (default: overwrites input).
    """
    if degrees not in (90, 180, 270):
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.DATA_VALIDATION, message="Degrees must be 90, 180, or 270.",
            severity=Severity.LOW, recoverable=True))

    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))

    out = Path(output_path).expanduser().resolve() if output_path else path

    def _rotate():
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(str(path))
        writer = PdfWriter()
        total = len(reader.pages)

        if pages == "all":
            indices = set(range(total))
        elif "-" in pages:
            start, end = pages.split("-", 1)
            indices = set(range(max(0, int(start) - 1), min(total, int(end))))
        else:
            indices = {int(pages) - 1}

        rotated_count = 0
        for i, page in enumerate(reader.pages):
            if i in indices:
                page.rotate(degrees)
                rotated_count += 1
            writer.add_page(page)

        with open(str(out), "wb") as f:
            writer.write(f)
        return rotated_count

    try:
        count = await asyncio.to_thread(_rotate)
        return ToolResult(success=True, data={
            "output": str(out),
            "pages_rotated": count,
            "degrees": degrees,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Rotate failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# ENCRYPT / DECRYPT
# ═════════════════════════════════════════════════════════════════════════════


async def pdf_encrypt(
    file_path: str,
    password: str,
    output_path: Optional[str] = None,
) -> ToolResult:
    """Encrypt a PDF with a password.

    Args:
        file_path: Path to the PDF.
        password: Password to set.
        output_path: Where to save (default: overwrites input).
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))

    out = Path(output_path).expanduser().resolve() if output_path else path

    def _encrypt():
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(str(path))
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        writer.encrypt(password)
        with open(str(out), "wb") as f:
            writer.write(f)
        return len(reader.pages)

    try:
        page_count = await asyncio.to_thread(_encrypt)
        return ToolResult(success=True, data={
            "output": str(out),
            "pages": page_count,
            "encrypted": True,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Encrypt failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


async def pdf_decrypt(
    file_path: str,
    password: str,
    output_path: Optional[str] = None,
) -> ToolResult:
    """Decrypt a password-protected PDF.

    Args:
        file_path: Path to the encrypted PDF.
        password: Password to decrypt with.
        output_path: Where to save the decrypted version.
    """
    path = Path(file_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))

    out = Path(output_path).expanduser().resolve() if output_path else path

    def _decrypt():
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            if not reader.decrypt(password):
                return None
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        with open(str(out), "wb") as f:
            writer.write(f)
        return len(reader.pages)

    try:
        result = await asyncio.to_thread(_decrypt)
        if result is None:
            return ToolResult(success=False, error=ToolError(
                code=ErrorCode.PERMISSION_DENIED, message="Wrong password.",
                severity=Severity.MEDIUM, recoverable=True))
        return ToolResult(success=True, data={
            "output": str(out),
            "pages": result,
            "decrypted": True,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Decrypt failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# WATERMARK
# ═════════════════════════════════════════════════════════════════════════════


async def pdf_watermark(
    file_path: str,
    watermark_path: str,
    output_path: Optional[str] = None,
) -> ToolResult:
    """Add a watermark (from another PDF) to every page.

    Args:
        file_path: Path to the PDF to watermark.
        watermark_path: Path to the watermark PDF (first page is used).
        output_path: Where to save (default: overwrites input).
    """
    path = Path(file_path).expanduser().resolve()
    wm_path = Path(watermark_path).expanduser().resolve()
    if not path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"File not found: {path}",
            severity=Severity.MEDIUM, recoverable=False))
    if not wm_path.exists():
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.FILE_NOT_FOUND, message=f"Watermark not found: {wm_path}",
            severity=Severity.MEDIUM, recoverable=False))

    out = Path(output_path).expanduser().resolve() if output_path else path

    def _watermark():
        from pypdf import PdfReader, PdfWriter
        watermark_page = PdfReader(str(wm_path)).pages[0]
        reader = PdfReader(str(path))
        writer = PdfWriter()
        for page in reader.pages:
            page.merge_page(watermark_page)
            writer.add_page(page)
        with open(str(out), "wb") as f:
            writer.write(f)
        return len(reader.pages)

    try:
        count = await asyncio.to_thread(_watermark)
        return ToolResult(success=True, data={
            "output": str(out),
            "pages_watermarked": count,
        })
    except Exception as e:
        return ToolResult(success=False, error=ToolError(
            code=ErrorCode.COMMAND_FAILED, message=f"Watermark failed: {e}",
            severity=Severity.MEDIUM, recoverable=True))


# ═════════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS
# ═════════════════════════════════════════════════════════════════════════════

TOOL_SCHEMAS = {
    "pdf_read": {
        "fn": pdf_read,
        "schema": {"type": "function", "function": {
            "name": "pdf_read",
            "description": "Extract text and optionally tables from a PDF. Supports page ranges.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF file"},
                "pages": {"type": "string", "description": "'all', a page number '3', or range '1-5' (default: all)"},
                "extract_tables": {"type": "boolean", "description": "Also extract tables (default: false)"},
            }, "required": ["file_path"]},
        }},
    },
    "pdf_metadata": {
        "fn": pdf_metadata,
        "schema": {"type": "function", "function": {
            "name": "pdf_metadata",
            "description": "Get PDF metadata — title, author, page count, file size, encryption status.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF file"},
            }, "required": ["file_path"]},
        }},
    },
    "pdf_merge": {
        "fn": pdf_merge,
        "schema": {"type": "function", "function": {
            "name": "pdf_merge",
            "description": "Merge multiple PDFs into one file.",
            "parameters": {"type": "object", "properties": {
                "file_paths": {"type": "array", "items": {"type": "string"}, "description": "List of PDF paths to merge (in order)"},
                "output_path": {"type": "string", "description": "Where to save the merged PDF"},
            }, "required": ["file_paths", "output_path"]},
        }},
    },
    "pdf_split": {
        "fn": pdf_split,
        "schema": {"type": "function", "function": {
            "name": "pdf_split",
            "description": "Split a PDF into individual page files.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF to split"},
                "output_dir": {"type": "string", "description": "Directory to save individual page PDFs"},
                "pages": {"type": "string", "description": "'all' or range like '1-5' (default: all)"},
            }, "required": ["file_path", "output_dir"]},
        }},
    },
    "pdf_rotate": {
        "fn": pdf_rotate,
        "schema": {"type": "function", "function": {
            "name": "pdf_rotate",
            "description": "Rotate pages in a PDF by 90, 180, or 270 degrees.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF"},
                "degrees": {"type": "integer", "description": "Rotation: 90, 180, or 270"},
                "pages": {"type": "string", "description": "'all', page number, or range (default: all)"},
                "output_path": {"type": "string", "description": "Output path (default: overwrites input)"},
            }, "required": ["file_path", "degrees"]},
        }},
    },
    "pdf_encrypt": {
        "fn": pdf_encrypt,
        "schema": {"type": "function", "function": {
            "name": "pdf_encrypt",
            "description": "Encrypt a PDF with a password.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF"},
                "password": {"type": "string", "description": "Password to set"},
                "output_path": {"type": "string", "description": "Output path (default: overwrites input)"},
            }, "required": ["file_path", "password"]},
        }},
    },
    "pdf_decrypt": {
        "fn": pdf_decrypt,
        "schema": {"type": "function", "function": {
            "name": "pdf_decrypt",
            "description": "Decrypt a password-protected PDF.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the encrypted PDF"},
                "password": {"type": "string", "description": "Password to decrypt"},
                "output_path": {"type": "string", "description": "Output path (default: overwrites input)"},
            }, "required": ["file_path", "password"]},
        }},
    },
    "pdf_watermark": {
        "fn": pdf_watermark,
        "schema": {"type": "function", "function": {
            "name": "pdf_watermark",
            "description": "Add a watermark (from another PDF's first page) to every page.",
            "parameters": {"type": "object", "properties": {
                "file_path": {"type": "string", "description": "Path to the PDF to watermark"},
                "watermark_path": {"type": "string", "description": "Path to the watermark PDF"},
                "output_path": {"type": "string", "description": "Output path (default: overwrites input)"},
            }, "required": ["file_path", "watermark_path"]},
        }},
    },
}
