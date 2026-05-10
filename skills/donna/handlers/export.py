"""
Export handler — routes to donna-mcp tool surface.

Input:
    content (dict | str): Output from a prior analyse, draft, or review call.
    format (str): Target format — one of 'pdf', 'docx', 'md'.
    output_path (str, optional): Destination file path. Defaults to a temp path.

Output:
    str: Absolute path to the exported file.

MCP boundary: calls donna-mcp::export — no rendering logic runs in-process.
"""
from __future__ import annotations

from typing import Any

SUPPORTED_FORMATS = ("pdf", "docx", "md")


def export(
    content: dict[str, Any] | str,
    format: str,  # noqa: A002
    output_path: str | None = None,
) -> str:
    """Route document export to donna-mcp.

    Args:
        content: Output dict from analyse/review, or markdown string from draft.
        format: Target format. Must be one of 'pdf', 'docx', 'md'.
        output_path: Optional destination path; donna-mcp chooses one if omitted.

    Returns:
        Absolute path to the exported file.

    Raises:
        ValueError: If format is not in SUPPORTED_FORMATS.
        NotImplementedError: W2b will wire this to donna-mcp.
    """
    if format not in SUPPORTED_FORMATS:
        raise ValueError(
            f"Unsupported format '{format}'. Must be one of {SUPPORTED_FORMATS}."
        )
    raise NotImplementedError(
        "W2b will wire this to donna-mcp. "
        "Call donna-mcp::export with content, format, and output_path."
    )
