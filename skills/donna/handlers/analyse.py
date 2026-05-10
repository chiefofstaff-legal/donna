"""
Analyse handler — routes to donna-mcp tool surface.

Input:
    document (str): Full document text to analyse.
    context (dict, optional): Additional context (jurisdiction, document_type).

Output:
    dict: {
        "clauses": [{"name": str, "text_span": str, "risk": str, "rationale": str}],
        "risks": [{"level": str, "description": str}],
        "summary": str,
    }

MCP boundary: calls donna-mcp::analyse — no analysis logic runs in-process.
"""
from __future__ import annotations

from typing import Any


def analyse(document: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Route document analysis to donna-mcp.

    Args:
        document: Full text of the legal document to analyse.
        context: Optional dict with keys like 'jurisdiction', 'document_type'.

    Returns:
        Structured clause report from donna-mcp.

    Raises:
        NotImplementedError: W2b will wire this to donna-mcp.
    """
    raise NotImplementedError(
        "W2b will wire this to donna-mcp. "
        "Call donna-mcp::analyse with document and context."
    )
