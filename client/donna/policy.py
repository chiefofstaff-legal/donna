"""Rule-based policy engine over IDR chains.

Evaluates a list of PolicyRules against every IDR record in a chain and
returns the first matching verdict (highest priority wins).  Pure function —
no I/O, no external deps.

Usage::

    from donna.policy import PolicyRule, PolicyVerdict, evaluate

    rules = [
        PolicyRule(
            id="block-high-value",
            field="confidence",
            op="lt",
            value=0.8,
            verdict=PolicyVerdict.ESCALATE,
            priority=10,
        ),
    ]
    result = evaluate(idr_chain, rules)
    assert result.verdict in (PolicyVerdict.ALLOW, PolicyVerdict.DENY, PolicyVerdict.ESCALATE)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PolicyVerdict(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


@dataclass
class PolicyRule:
    id: str
    field: str          # IDR field key
    op: str             # "eq" | "neq" | "lt" | "gt" | "lte" | "gte" | "contains" | "regex"
    value: Any
    verdict: PolicyVerdict
    priority: int = 0   # higher number evaluated first


@dataclass
class PolicyResult:
    verdict: PolicyVerdict
    rule_id: str | None
    reason: str


_OPS = {
    "eq":       lambda a, b: a == b,
    "neq":      lambda a, b: a != b,
    "lt":       lambda a, b: float(a) < float(b),
    "gt":       lambda a, b: float(a) > float(b),
    "lte":      lambda a, b: float(a) <= float(b),
    "gte":      lambda a, b: float(a) >= float(b),
    "contains": lambda a, b: str(b).lower() in str(a).lower(),
    "regex":    lambda a, b: bool(re.search(str(b), str(a), re.IGNORECASE)),
}

_DEFAULT = PolicyResult(
    verdict=PolicyVerdict.ALLOW,
    rule_id=None,
    reason="no matching rule — default allow",
)


def _match(idr: dict, rule: PolicyRule) -> bool:
    """Return True if *rule* matches *idr*; skip gracefully on missing/malformed fields."""
    raw = idr.get(rule.field)
    if raw is None:
        return False
    op_fn = _OPS.get(rule.op)
    if op_fn is None:
        return False
    try:
        return op_fn(raw, rule.value)
    except (TypeError, ValueError):
        return False


def _first_match(idr_chain: list[dict], rule: PolicyRule) -> PolicyResult | None:
    """Return a PolicyResult if *rule* matches any IDR in the chain, else None."""
    matched = next((idr for idr in idr_chain if _match(idr, rule)), None)
    if matched is None:
        return None
    return PolicyResult(
        verdict=rule.verdict,
        rule_id=rule.id,
        reason=f"rule {rule.id!r}: {rule.field} {rule.op} {rule.value!r}",
    )


def evaluate(idr_chain: list[dict], rules: list[PolicyRule]) -> PolicyResult:
    """Evaluate *rules* against every IDR in *idr_chain*.

    Rules are sorted by descending priority; the first rule that matches any
    IDR in the chain wins.  An empty chain or empty ruleset returns ALLOW.

    Complexity: O(R × N) where R = |rules|, N = |chain| — both bounded to
    small values in legal workflows (< 100 each), effectively O(1).
    """
    if not idr_chain or not rules:
        return _DEFAULT
    sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)
    results = (
        result for rule in sorted_rules
        if (result := _first_match(idr_chain, rule)) is not None
    )
    return next(results, _DEFAULT)
