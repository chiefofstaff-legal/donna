"""donna-gov-mcp: MCP server exposing IDR + governance tools.

Separate from mcp_server.py (voice/delegation surface) — this server
exposes policy evaluation, RBAC access checks, and workflow chain management.

Run as a script or via MCP server config::

    {
      "mcpServers": {
        "donna-gov": {
          "command": "python",
          "args": ["-m", "donna.mcp_gov"],
          "cwd": "/path/to/donna/client"
        }
      }
    }

Tools:
  donna_policy_evaluate  — evaluate IDR chain against policy rules
  donna_access_check     — check actor/action/tenant RBAC
  donna_workflow_handoff — append a handoff record to a named workflow
  donna_workflow_verify  — verify a named workflow's hash chain integrity
"""
from __future__ import annotations

import json
import sys
from typing import Any

from donna.access import AccessControl, AccessDeniedError, ActorRole, Permission
from donna.policy import PolicyRule, PolicyVerdict, evaluate as policy_evaluate
from donna.workflow import Workflow

VERSION = "0.1.0-gov"
PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "donna-gov", "version": VERSION}

# In-process workflow registry — keyed by workflow_id; ephemeral per MCP session
_WORKFLOWS: dict[str, Workflow] = {}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "donna_policy_evaluate",
        "description": (
            "Evaluate a list of IDR records against policy rules. "
            "Returns ALLOW / DENY / ESCALATE with the triggering rule id."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "idr_chain": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of IDR dicts to evaluate",
                },
                "rules": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "List of rule dicts: {id, field, op, value, verdict, priority?}"
                    ),
                },
            },
            "required": ["idr_chain", "rules"],
        },
    },
    {
        "name": "donna_access_check",
        "description": (
            "Check whether an actor can perform an action within a tenant. "
            "Returns {allowed: bool}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "actor_id":  {"type": "string"},
                "action":    {"type": "string"},
                "tenant_id": {"type": "string"},
                "actors": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "List of actor dicts: {actor_id, tenant_id, roles: [str]}"
                    ),
                },
                "permissions": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "List of permission dicts: {action, allowed_roles: [str]}",
                },
            },
            "required": ["actor_id", "action", "tenant_id", "actors", "permissions"],
        },
    },
    {
        "name": "donna_workflow_handoff",
        "description": (
            "Append a handoff record to a named workflow. Creates the workflow "
            "if it does not exist. Returns the new HandoffRecord."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
                "from_actor":  {"type": "string"},
                "to_actor":    {"type": "string"},
                "idr":         {"type": "object"},
            },
            "required": ["workflow_id", "from_actor", "to_actor", "idr"],
        },
    },
    {
        "name": "donna_workflow_verify",
        "description": (
            "Verify the hash-chain integrity of a named workflow. "
            "Returns {valid: bool, chain_length: int}."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "string"},
            },
            "required": ["workflow_id"],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _tool_result(text: str, structured: dict | None = None) -> dict[str, Any]:
    content = [{"type": "text", "text": text}]
    out: dict[str, Any] = {"content": content}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _parse_rules(raw: list[dict]) -> list[PolicyRule]:
    return [
        PolicyRule(
            id=r["id"],
            field=r["field"],
            op=r["op"],
            value=r["value"],
            verdict=PolicyVerdict(r["verdict"]),
            priority=int(r.get("priority", 0)),
        )
        for r in raw
    ]


def _handle_policy_evaluate(_: Any, args: dict) -> dict:
    idr_chain = args.get("idr_chain") or []
    raw_rules = args.get("rules") or []
    try:
        rules = _parse_rules(raw_rules)
    except (KeyError, ValueError) as exc:
        return _tool_result(f"error: invalid rule format: {exc}")
    result = policy_evaluate(idr_chain, rules)
    return _tool_result(
        f"verdict={result.verdict.value} rule={result.rule_id or 'none'}",
        {"verdict": result.verdict.value, "rule_id": result.rule_id, "reason": result.reason},
    )


def _handle_access_check(_: Any, args: dict) -> dict:
    try:
        perms = [
            Permission(action=p["action"], allowed_roles=frozenset(p["allowed_roles"]))
            for p in (args.get("permissions") or [])
        ]
        ac = AccessControl(perms)
        for a in (args.get("actors") or []):
            ac.grant(ActorRole(
                actor_id=a["actor_id"],
                tenant_id=a["tenant_id"],
                roles=frozenset(a["roles"]),
            ))
    except (KeyError, TypeError) as exc:
        return _tool_result(f"error: invalid actor/permission format: {exc}")
    allowed = ac.check(args["actor_id"], args["action"], args["tenant_id"])
    return _tool_result(
        f"access={'allowed' if allowed else 'denied'}",
        {"allowed": allowed, "actor_id": args["actor_id"], "action": args["action"]},
    )


def _handle_workflow_handoff(_: Any, args: dict) -> dict:
    wid = args.get("workflow_id", "")
    if not wid:
        return _tool_result("error: workflow_id required")
    if wid not in _WORKFLOWS:
        _WORKFLOWS[wid] = Workflow(workflow_id=wid)
    wf = _WORKFLOWS[wid]
    record = wf.handoff(
        from_actor=args.get("from_actor", ""),
        to_actor=args.get("to_actor", ""),
        idr=args.get("idr") or {},
    )
    return _tool_result(
        f"handoff seq={record.seq} from={record.from_actor} to={record.to_actor}",
        {
            "seq": record.seq,
            "from_actor": record.from_actor,
            "to_actor": record.to_actor,
            "record_hash": record.record_hash,
            "prev_hash": record.prev_hash,
            "timestamp": record.timestamp,
        },
    )


def _handle_workflow_verify(_: Any, args: dict) -> dict:
    wid = args.get("workflow_id", "")
    if wid not in _WORKFLOWS:
        return _tool_result(
            f"workflow {wid!r} not found",
            {"valid": False, "chain_length": 0},
        )
    wf = _WORKFLOWS[wid]
    valid = wf.verify()
    length = len(wf.chain())
    return _tool_result(
        f"workflow {wid!r}: valid={valid} chain_length={length}",
        {"valid": valid, "chain_length": length},
    )


HANDLERS: dict[str, Any] = {
    "donna_policy_evaluate": _handle_policy_evaluate,
    "donna_access_check": _handle_access_check,
    "donna_workflow_handoff": _handle_workflow_handoff,
    "donna_workflow_verify": _handle_workflow_verify,
}


# ---------------------------------------------------------------------------
# MCP stdio loop (mirrors mcp_server.py structure)
# ---------------------------------------------------------------------------

def _dispatch(params: dict) -> dict:
    name = params.get("name", "")
    args = params.get("arguments", {}) or {}
    handler = HANDLERS.get(name)
    if not handler:
        return _tool_result(f"error: unknown tool {name!r}")
    try:
        return handler(None, args)
    except Exception as exc:
        return _tool_result(f"error: {type(exc).__name__}: {exc}")


def _handle_request(req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        return {"jsonrpc": "2.0", "id": req_id,
                "result": _dispatch(req.get("params", {}) or {})}
    if method.startswith("notifications/"):
        return None
    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"method not found: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
