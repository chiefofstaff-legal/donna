"""
Review handler — routes to donna-mcp tool surface.

Input:
    document (str): Full document text to review.
    context (dict, optional): Review focus areas, comparison standard, jurisdiction.

Output:
    dict: {
        "comments": [
            {
                "clause": str,
                "text_span": str,
                "issue": str,
                "suggestion": str,
            }
        ]
    }

MCP boundary: calls donna-mcp::review — no review logic runs in-process.
"""
from __future__ import annotations

from typing import Any


def review(document: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Route document review to donna-mcp.

    Args:
        document: Full text of the legal document to review.
        context: Optional dict with focus areas, comparison standard, jurisdiction.

    Returns:
        Redline comments dict from donna-mcp, each anchored to a text span.

    Raises:
        NotImplementedError: W2b will wire this to donna-mcp.
    """
    raise NotImplementedError(
        "W2b will wire this to donna-mcp. "
        "Call donna-mcp::review with document and context."
    )
