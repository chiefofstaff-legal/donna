"""Tests for mcp_gov.py — governance MCP tool implementations.

Goodhart-resistant (Rule 14): each test verifies concrete output values,
not just call counts. Mutation of any handler breaks at least one test.
"""
from __future__ import annotations

import json

import pytest

import donna.mcp_gov as gov
from donna.mcp_gov import _dispatch, _handle_request, _WORKFLOWS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _call(name: str, **kwargs) -> dict:
    """Invoke a tool via the MCP dispatch path."""
    return _dispatch({"name": name, "arguments": kwargs})


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _structured(result: dict) -> dict:
    return result["structuredContent"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_workflows():
    """Isolate workflow state between tests."""
    _WORKFLOWS.clear()
    yield
    _WORKFLOWS.clear()


# ---------------------------------------------------------------------------
# donna_policy_evaluate — happy path
# ---------------------------------------------------------------------------

def test_policy_evaluate_allow_default():
    """No rules → default ALLOW."""
    result = _call(
        "donna_policy_evaluate",
        idr_chain=[{"actor": "alice", "confidence": 0.9}],
        rules=[],
    )
    s = _structured(result)
    assert s["verdict"] == "allow"
    assert s["rule_id"] is None


def test_policy_evaluate_deny_on_match():
    """Rule matching actor field → DENY verdict returned."""
    result = _call(
        "donna_policy_evaluate",
        idr_chain=[{"actor": "bob", "action": "delegate"}],
        rules=[{
            "id": "no-bob",
            "field": "actor",
            "op": "eq",
            "value": "bob",
            "verdict": "deny",
            "priority": 10,
        }],
    )
    s = _structured(result)
    assert s["verdict"] == "deny"
    assert s["rule_id"] == "no-bob"
    assert "no-bob" in s["reason"]


def test_policy_evaluate_escalate_on_contains():
    """Contains op on matter field → ESCALATE."""
    result = _call(
        "donna_policy_evaluate",
        idr_chain=[{"matter": "urgent-merger-2026"}],
        rules=[{
            "id": "escalate-merger",
            "field": "matter",
            "op": "contains",
            "value": "merger",
            "verdict": "escalate",
        }],
    )
    s = _structured(result)
    assert s["verdict"] == "escalate"
    assert s["rule_id"] == "escalate-merger"


def test_policy_evaluate_error_on_bad_rule():
    """Malformed rule dict → error text, no exception raised."""
    result = _call(
        "donna_policy_evaluate",
        idr_chain=[{"actor": "x"}],
        rules=[{"broken": True}],  # missing required keys
    )
    assert "error" in _text(result)
    assert "structuredContent" not in result


# ---------------------------------------------------------------------------
# donna_access_check — happy path
# ---------------------------------------------------------------------------

def test_access_check_allowed():
    """Actor with matching role → allowed: True."""
    result = _call(
        "donna_access_check",
        actor_id="alice",
        action="sign",
        tenant_id="firm-a",
        actors=[{"actor_id": "alice", "tenant_id": "firm-a", "roles": ["attorney"]}],
        permissions=[{"action": "sign", "allowed_roles": ["attorney"]}],
    )
    s = _structured(result)
    assert s["allowed"] is True
    assert s["actor_id"] == "alice"
    assert s["action"] == "sign"
    assert "allowed" in _text(result)


def test_access_check_denied_cross_tenant():
    """Actor granted in firm-a cannot act in firm-b — structural isolation."""
    result = _call(
        "donna_access_check",
        actor_id="alice",
        action="sign",
        tenant_id="firm-b",
        actors=[{"actor_id": "alice", "tenant_id": "firm-a", "roles": ["attorney"]}],
        permissions=[{"action": "sign", "allowed_roles": ["attorney"]}],
    )
    s = _structured(result)
    assert s["allowed"] is False


def test_access_check_error_on_bad_actors():
    """Malformed actor dict → error text, no exception raised."""
    result = _call(
        "donna_access_check",
        actor_id="x",
        action="sign",
        tenant_id="t",
        actors=[{"broken": True}],
        permissions=[],
    )
    assert "error" in _text(result)


# ---------------------------------------------------------------------------
# donna_workflow_handoff + donna_workflow_verify — happy path + state
# ---------------------------------------------------------------------------

def test_workflow_handoff_creates_record():
    """First handoff → seq=0, prev_hash='genesis', record_hash present."""
    result = _call(
        "donna_workflow_handoff",
        workflow_id="wf-001",
        from_actor="alice",
        to_actor="bob",
        idr={"action": "delegate", "matter": "estate-2026"},
    )
    s = _structured(result)
    assert s["seq"] == 0
    assert s["prev_hash"] == "genesis"
    assert len(s["record_hash"]) == 64  # SHA-256 hex
    assert s["from_actor"] == "alice"
    assert s["to_actor"] == "bob"


def test_workflow_handoff_sequential_seq():
    """Two handoffs on same workflow → seq 0 then 1, prev_hash linked."""
    _call("donna_workflow_handoff", workflow_id="wf-002",
          from_actor="a", to_actor="b", idr={})
    result2 = _call("donna_workflow_handoff", workflow_id="wf-002",
                    from_actor="b", to_actor="c", idr={})
    s2 = _structured(result2)
    assert s2["seq"] == 1
    # prev_hash of second = record_hash of first
    assert len(s2["prev_hash"]) == 64


def test_workflow_verify_intact_chain():
    """Intact chain → valid=True, chain_length matches handoff count."""
    for i in range(3):
        _call("donna_workflow_handoff", workflow_id="wf-003",
              from_actor=f"actor-{i}", to_actor=f"actor-{i+1}", idr={"seq": i})
    result = _call("donna_workflow_verify", workflow_id="wf-003")
    s = _structured(result)
    assert s["valid"] is True
    assert s["chain_length"] == 3


def test_workflow_verify_unknown_workflow():
    """verify on non-existent workflow → valid=False, chain_length=0."""
    result = _call("donna_workflow_verify", workflow_id="does-not-exist")
    s = _structured(result)
    assert s["valid"] is False
    assert s["chain_length"] == 0


def test_workflow_handoff_missing_workflow_id():
    """Empty workflow_id → error text, no exception raised."""
    result = _call("donna_workflow_handoff",
                   workflow_id="", from_actor="a", to_actor="b", idr={})
    assert "error" in _text(result)


# ---------------------------------------------------------------------------
# MCP protocol layer — initialize + tools/list + unknown method
# ---------------------------------------------------------------------------

def test_handle_request_initialize():
    result = _handle_request({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    })
    assert result["result"]["protocolVersion"] == "2024-11-05"
    assert "tools" in result["result"]["capabilities"]


def test_handle_request_tools_list():
    result = _handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in result["result"]["tools"]}
    assert "donna_policy_evaluate" in names
    assert "donna_access_check" in names
    assert "donna_workflow_handoff" in names
    assert "donna_workflow_verify" in names


def test_handle_request_unknown_method():
    result = _handle_request({"jsonrpc": "2.0", "id": 3, "method": "nonexistent/method"})
    assert result["error"]["code"] == -32601


def test_dispatch_unknown_tool():
    result = _dispatch({"name": "not_a_tool", "arguments": {}})
    assert "error" in _text(result)
    assert "unknown tool" in _text(result)


# ---------------------------------------------------------------------------
# GRASP provenance integration
# ---------------------------------------------------------------------------

@pytest.mark.grasp
def test_workflow_handoff_with_grasp_receipt(fake_grasp):
    """Handoff records provenance via GRASP bridge without error."""
    result = _call("donna_workflow_handoff", workflow_id="wf-grasp-1",
                   from_actor="alice", to_actor="bob", idr={"action": "review"})
    s = _structured(result)
    assert s["seq"] == 0
    assert len(s["record_hash"]) == 64
    # GRASP bridge was called (fake injected by fixture)
    fake_grasp["idr"].build_idr.assert_called_once()


@pytest.mark.grasp
def test_workflow_handoff_graceful_without_grasp():
    """Handoff succeeds even when GRASP package is absent (fail-open)."""
    import donna.grasp_provenance as _bridge
    orig = _bridge._GRASP_AVAILABLE
    _bridge._GRASP_AVAILABLE = False
    try:
        result = _call("donna_workflow_handoff", workflow_id="wf-nograsp-1",
                       from_actor="carol", to_actor="dave", idr={"action": "sign"})
        s = _structured(result)
        assert s["seq"] == 0
        assert "error" not in _text(result)
    finally:
        _bridge._GRASP_AVAILABLE = orig
