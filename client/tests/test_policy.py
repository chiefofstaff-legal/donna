"""Goodhart-resistant tests for donna.policy.

Each test can fail if the implementation is wrong — no mocked internals,
no trivially-passable assertions.
"""
from __future__ import annotations

import pytest

from donna.policy import PolicyResult, PolicyRule, PolicyVerdict, evaluate

# ---------------------------------------------------------------------------
# Shared rule fixtures
# ---------------------------------------------------------------------------

DENY_RULE = PolicyRule(
    id="deny-unknown-actor",
    field="actor",
    op="eq",
    value="unknown",
    verdict=PolicyVerdict.DENY,
    priority=10,
)
ESCALATE_RULE = PolicyRule(
    id="escalate-sensitive-matter",
    field="matter",
    op="contains",
    value="litigation",
    verdict=PolicyVerdict.ESCALATE,
    priority=20,
)
REGEX_RULE = PolicyRule(
    id="deny-test-env",
    field="action",
    op="regex",
    value=r"test_.*",
    verdict=PolicyVerdict.DENY,
    priority=15,
)


def _idr(actor="alice", action="delegate", matter="contract", confidence=0.95) -> dict:
    return {"actor": actor, "action": action, "matter": matter, "confidence": confidence}


# ---------------------------------------------------------------------------
# 12 Goodhart-resistant test cases
# ---------------------------------------------------------------------------

def test_empty_chain_returns_allow():
    result = evaluate([], [DENY_RULE])
    assert result.verdict == PolicyVerdict.ALLOW
    assert result.rule_id is None


def test_empty_rules_returns_allow():
    result = evaluate([_idr()], [])
    assert result.verdict == PolicyVerdict.ALLOW


def test_deny_on_exact_actor_match():
    result = evaluate([_idr(actor="unknown")], [DENY_RULE])
    assert result.verdict == PolicyVerdict.DENY
    assert result.rule_id == "deny-unknown-actor"


def test_allow_when_no_rule_matches():
    result = evaluate([_idr(actor="alice")], [DENY_RULE])
    assert result.verdict == PolicyVerdict.ALLOW


def test_escalate_on_matter_contains():
    result = evaluate([_idr(matter="client-litigation-2024")], [ESCALATE_RULE])
    assert result.verdict == PolicyVerdict.ESCALATE
    assert result.rule_id == "escalate-sensitive-matter"


def test_priority_higher_wins_over_lower():
    """ESCALATE (priority=20) beats DENY (priority=10) when both match."""
    chain = [_idr(actor="unknown", matter="litigation-matter")]
    result = evaluate(chain, [DENY_RULE, ESCALATE_RULE])
    assert result.verdict == PolicyVerdict.ESCALATE
    assert result.rule_id == "escalate-sensitive-matter"


def test_deny_on_confidence_threshold():
    deny_low = PolicyRule(
        id="deny-low-confidence",
        field="confidence",
        op="lt",
        value=0.7,
        verdict=PolicyVerdict.DENY,
        priority=5,
    )
    result = evaluate([_idr(confidence=0.5)], [deny_low])
    assert result.verdict == PolicyVerdict.DENY


def test_allow_above_confidence_threshold():
    deny_low = PolicyRule(
        id="deny-low-confidence",
        field="confidence",
        op="lt",
        value=0.7,
        verdict=PolicyVerdict.DENY,
        priority=5,
    )
    result = evaluate([_idr(confidence=0.95)], [deny_low])
    assert result.verdict == PolicyVerdict.ALLOW


def test_regex_rule_matches_action():
    result = evaluate([_idr(action="test_delegate")], [REGEX_RULE])
    assert result.verdict == PolicyVerdict.DENY
    assert result.rule_id == "deny-test-env"


def test_regex_rule_no_match():
    result = evaluate([_idr(action="delegate")], [REGEX_RULE])
    assert result.verdict == PolicyVerdict.ALLOW


def test_missing_field_skips_gracefully():
    """IDR missing the rule's field should not raise — just skip."""
    chain = [{"actor": "alice"}]  # no 'confidence' field
    deny_low = PolicyRule(
        id="deny-low-confidence",
        field="confidence",
        op="lt",
        value=0.7,
        verdict=PolicyVerdict.DENY,
        priority=5,
    )
    result = evaluate(chain, [deny_low])
    assert result.verdict == PolicyVerdict.ALLOW


def test_multi_idr_chain_second_triggers_deny():
    """First IDR passes, second IDR triggers DENY — chain must evaluate all."""
    chain = [_idr(actor="alice"), _idr(actor="unknown")]
    result = evaluate(chain, [DENY_RULE])
    assert result.verdict == PolicyVerdict.DENY


def test_result_reason_contains_rule_id_on_match():
    result = evaluate([_idr(actor="unknown")], [DENY_RULE])
    assert result.reason
    assert "deny-unknown-actor" in result.reason
