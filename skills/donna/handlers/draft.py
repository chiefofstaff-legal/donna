"""
Draft handler — routes to donna-mcp tool surface.

Input:
    document_type (str): Type of document to draft (e.g. 'nda', 'service-agreement',
        'ip-assignment', 'settlement-letter').
    context (dict, optional): Parties, jurisdiction, key terms, governing law.

Output:
    str: Full document text in markdown with labelled clauses.

MCP boundary: calls donna-mcp::draft — no drafting logic runs in-process.
"""
from __future__ import annotations

from typing import Any


def draft(document_type: str, context: dict[str, Any] | None = None) -> str:
    """Route document drafting to donna-mcp.

    Args:
        document_type: Type identifier for the document to draft.
        context: Optional dict with parties, jurisdiction, governing_law, key_terms.

    Returns:
        Full document text as markdown string from donna-mcp.

    Raises:
        NotImplementedError: W2b will wire this to donna-mcp.
    """
    raise NotImplementedError(
        "W2b will wire this to donna-mcp. "
        "Call donna-mcp::draft with document_type and context."
    )
