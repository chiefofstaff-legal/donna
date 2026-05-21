"""Goodhart-resistant tests for donna.access.

Each assertion targets observable behaviour — the tests fail if roles leak
across tenants, unknown actors are granted access, or require() silently passes.
"""
from __future__ import annotations

import pytest

from donna.access import AccessControl, AccessDeniedError, ActorRole, Permission

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

DELEGATE_PERM = Permission(action="delegate", allowed_roles=frozenset({"attorney"}))
REVIEW_PERM = Permission(
    action="review", allowed_roles=frozenset({"attorney", "paralegal"})
)
SIGN_PERM = Permission(action="sign", allowed_roles=frozenset({"attorney"}))

ALICE = ActorRole(actor_id="alice", tenant_id="firm-1", roles=frozenset({"attorney"}))
BOB = ActorRole(actor_id="bob", tenant_id="firm-1", roles=frozenset({"paralegal"}))
CAROL_FIRM2 = ActorRole(
    actor_id="alice", tenant_id="firm-2", roles=frozenset({"paralegal"})
)


def _ac(*extra_perms: Permission) -> AccessControl:
    return AccessControl([DELEGATE_PERM, REVIEW_PERM, SIGN_PERM, *extra_perms])


# ---------------------------------------------------------------------------
# 15 Goodhart-resistant test cases
# ---------------------------------------------------------------------------

def test_basic_allow():
    ac = _ac()
    ac.grant(ALICE)
    assert ac.check("alice", "delegate", "firm-1") is True


def test_basic_deny_wrong_role():
    ac = _ac()
    ac.grant(BOB)
    assert ac.check("bob", "delegate", "firm-1") is False


def test_cross_tenant_isolation():
    """alice@firm-1 (attorney) must not gain access in firm-2."""
    ac = _ac()
    ac.grant(ALICE)  # firm-1 only
    assert ac.check("alice", "delegate", "firm-2") is False


def test_cross_tenant_different_role():
    """alice@firm-2 (paralegal) cannot delegate even if alice@firm-1 (attorney) can."""
    ac = _ac()
    ac.grant(ALICE)
    ac.grant(CAROL_FIRM2)
    assert ac.check("alice", "delegate", "firm-2") is False
    assert ac.check("alice", "delegate", "firm-1") is True


def test_multi_role_any_match_grants():
    """paralegal can review — multi-role intersection."""
    ac = _ac()
    ac.grant(BOB)
    assert ac.check("bob", "review", "firm-1") is True


def test_unknown_actor_denied():
    ac = _ac()
    assert ac.check("nobody", "delegate", "firm-1") is False


def test_unknown_action_denied():
    ac = _ac()
    ac.grant(ALICE)
    assert ac.check("alice", "nonexistent_action", "firm-1") is False


def test_require_raises_on_deny():
    ac = _ac()
    ac.grant(BOB)
    with pytest.raises(AccessDeniedError, match="delegate"):
        ac.require("bob", "delegate", "firm-1")


def test_require_passes_on_allow():
    ac = _ac()
    ac.grant(ALICE)
    ac.require("alice", "delegate", "firm-1")  # must not raise


def test_grant_override_replaces_roles():
    """Re-granting an actor replaces their roles."""
    ac = _ac()
    ac.grant(BOB)
    assert ac.check("bob", "delegate", "firm-1") is False
    ac.grant(ActorRole(actor_id="bob", tenant_id="firm-1", roles=frozenset({"attorney"})))
    assert ac.check("bob", "delegate", "firm-1") is True


def test_empty_permission_list_denies_all():
    ac = AccessControl([])
    ac.grant(ALICE)
    assert ac.check("alice", "delegate", "firm-1") is False


def test_actor_with_no_roles_denied():
    ac = _ac()
    ac.grant(ActorRole(actor_id="ghost", tenant_id="firm-1", roles=frozenset()))
    assert ac.check("ghost", "delegate", "firm-1") is False


def test_sign_attorney_only():
    ac = _ac()
    ac.grant(ALICE)
    ac.grant(BOB)
    assert ac.check("alice", "sign", "firm-1") is True
    assert ac.check("bob", "sign", "firm-1") is False


def test_error_message_includes_actor_and_action():
    ac = _ac()
    ac.grant(BOB)
    with pytest.raises(AccessDeniedError) as exc_info:
        ac.require("bob", "sign", "firm-1")
    msg = str(exc_info.value)
    assert "bob" in msg
    assert "sign" in msg


def test_multiple_tenants_independent():
    """Grants in firm-1 and firm-2 are fully independent."""
    ac = _ac()
    ac.grant(ALICE)       # attorney in firm-1
    ac.grant(CAROL_FIRM2)  # paralegal in firm-2 (same actor_id "alice")
    assert ac.check("alice", "sign", "firm-1") is True
    assert ac.check("alice", "sign", "firm-2") is False  # paralegal can't sign
