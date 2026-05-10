"""donna-mcp: MCP server exposing the DONNA voice surface for delegation orchestration.

Drop into Claude Desktop or Claude Code via:

    {
      "mcpServers": {
        "donna": {
          "command": "python",
          "args": ["-m", "donna.mcp_server"],
          "cwd": "/path/to/donna-legal/client"
        }
      }
    }

Or run as a script: python -m donna.mcp_server (stdio transport).

The skill at donna-legal/donna-skill/SKILL.md teaches Claude when to invoke
these tools.

Tool surface mirrors the existing CLI in main.py — same intent-extractor
pipeline (with PII Shield), same SQLite store, same Clio-compatible exports.

This is a syscall-doctrine shim: stable typed API independent of which LLM
provider sits behind the extractor.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any

from donna.config import load_config
from donna.export import export_csv, export_json
from donna.models import ClarifyRequest, Task, TimeEntry
from donna.router import Router

VERSION = "0.8.0-mcp"

PROTOCOL_VERSION = "2024-11-05"

SERVER_INFO = {"name": "donna", "version": VERSION}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "donna_log_time",
        "description": (
            "Log a billable time entry from a natural-language transcript. "
            "Example transcripts: 'just spent 90 minutes on the Smith motion', "
            "'one hour reviewing the Acme contract'. PII Shield anonymises "
            "client names before LLM call; entry de-anonymised before storage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "Natural-language description of the time spent",
                },
            },
            "required": ["transcript"],
        },
    },
    {
        "name": "donna_delegate_task",
        "description": (
            "Delegate a task from a natural-language transcript. Example: "
            "'Mike, draft the response brief by Friday'. Extracts assignee, "
            "task, deadline, optional matter."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript": {
                    "type": "string",
                    "description": "Natural-language delegation",
                },
            },
            "required": ["transcript"],
        },
    },
    {
        "name": "donna_query_today",
        "description": "Return today's logged time entries with totals.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "donna_summary",
        "description": (
            "Plain-language daily summary like 'You've logged 6.5 hours "
            "across 3 matters today'."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "donna_export",
        "description": (
            "Export time entries as CSV (Clio-compatible) or JSON. "
            "Optional date_from / date_to filter (ISO YYYY-MM-DD)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["csv", "json"],
                    "default": "csv",
                },
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
            },
        },
    },
]


def _serialise_intent(result: Any) -> dict[str, Any]:
    """Normalise router output into a JSON-safe dict."""
    if isinstance(result, TimeEntry):
        return {"kind": "time_entry", **result.to_dict()}
    if isinstance(result, Task):
        return {"kind": "task", **result.to_dict()}
    if isinstance(result, ClarifyRequest):
        return {"kind": "clarify", **result.to_dict()}
    return {"kind": "unknown", "value": str(result)}


def _tool_result(text: str, structured: dict | None = None) -> dict[str, Any]:
    """Wrap a result into MCP tool-call response shape."""
    content = [{"type": "text", "text": text}]
    out: dict[str, Any] = {"content": content}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _handle_log_time(router: Router, args: dict) -> dict:
    transcript = args.get("transcript", "")
    if not transcript:
        return _tool_result("error: transcript required")
    parsed = router.route(transcript)
    structured = _serialise_intent(parsed)
    summary = (
        f"Logged: {parsed.duration_hours}h on {parsed.matter or 'unknown matter'}"
        if isinstance(parsed, TimeEntry)
        else f"Routed as {structured['kind']}: {structured}"
    )
    return _tool_result(summary, structured)


def _handle_delegate_task(router: Router, args: dict) -> dict:
    transcript = args.get("transcript", "")
    if not transcript:
        return _tool_result("error: transcript required")
    parsed = router.route(transcript)
    structured = _serialise_intent(parsed)
    summary = (
        f"Delegated to {parsed.assignee}: {parsed.task} (by {parsed.deadline or 'unspecified'})"
        if isinstance(parsed, Task)
        else f"Routed as {structured['kind']}: {structured}"
    )
    return _tool_result(summary, structured)


def _handle_query_today(router: Router, _args: dict) -> dict:
    entries = router.time_entry_store.list_today()
    rows = [asdict(e) if hasattr(e, "__dataclass_fields__") else dict(e) for e in entries]
    total = sum(getattr(e, "duration_hours", None) or 0 for e in entries)
    return _tool_result(
        f"{len(entries)} entries today, total {total}h",
        {"entries": rows, "total_hours": total},
    )


def _handle_summary(router: Router, _args: dict) -> dict:
    summary = router.time_entry_store.daily_summary()
    return _tool_result(summary, {"summary": summary})


def _handle_export(router: Router, args: dict) -> dict:
    fmt = args.get("format", "csv")
    df = args.get("date_from")
    dt = args.get("date_to")
    entries = router.time_entry_store.query(date_from=df, date_to=dt)
    payload = export_csv(entries) if fmt == "csv" else export_json(entries)
    return _tool_result(payload, {"format": fmt, "count": len(entries)})


HANDLERS = {
    "donna_log_time": _handle_log_time,
    "donna_delegate_task": _handle_delegate_task,
    "donna_query_today": _handle_query_today,
    "donna_summary": _handle_summary,
    "donna_export": _handle_export,
}


def _dispatch_tool_call(router: Router, params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    handler = HANDLERS.get(name)
    if not handler:
        return _tool_result(f"error: unknown tool {name!r}")
    try:
        return handler(router, args)
    except Exception as exc:
        return _tool_result(f"error: {type(exc).__name__}: {exc}")


def _handle_request(router: Router, req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        result = _dispatch_tool_call(router, req.get("params", {}) or {})
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    if method.startswith("notifications/"):
        return None
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> None:
    config = load_config()
    router = Router(config)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle_request(router, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
