"""Per-actor RBAC bound to per-tenant signing keys.

Tenant isolation is structural: actor roles are keyed by (actor_id, tenant_id)
so a grant in tenant A cannot leak into tenant B even if the actor_id collides.

Usage::

    from donna.access import AccessControl, ActorRole, Permission

    ac = AccessControl([
        Permission(action="delegate", allowed_roles=frozenset({"attorney"})),
        Permission(action="review",   allowed_roles=frozenset({"attorney", "paralegal"})),
    ])
    ac.grant(ActorRole(actor_id="alice", tenant_id="firm-1", roles=frozenset({"attorney"})))

    ac.check("alice", "delegate", "firm-1")   # True
    ac.check("alice", "delegate", "firm-2")   # False — cross-tenant
    ac.require("alice", "sign", "firm-1")     # raises AccessDeniedError
"""

from __future__ import annotations

from dataclasses import dataclass


class AccessDeniedError(PermissionError):
    """Raised by AccessControl.require when access is denied."""


@dataclass(frozen=True)
class ActorRole:
    actor_id: str
    tenant_id: str
    roles: frozenset[str]


@dataclass(frozen=True)
class Permission:
    action: str
    allowed_roles: frozenset[str]


class AccessControl:
    """Role-based access control with structural tenant isolation."""

    def __init__(self, permissions: list[Permission]) -> None:
        # action → allowed_roles lookup; O(1) check after init
        self._perms: dict[str, frozenset[str]] = {
            p.action: p.allowed_roles for p in permissions
        }
        # (actor_id, tenant_id) → roles; cross-tenant access structurally impossible
        self._actors: dict[tuple[str, str], frozenset[str]] = {}

    def grant(self, actor: ActorRole) -> None:
        """Register or replace an actor's roles for a specific tenant."""
        self._actors[(actor.actor_id, actor.tenant_id)] = actor.roles

    def check(self, actor_id: str, action: str, tenant_id: str) -> bool:
        """Return True iff the actor has a role permitted to perform action in tenant."""
        actor_roles = self._actors.get((actor_id, tenant_id))
        if not actor_roles:
            return False
        allowed = self._perms.get(action)
        if allowed is None:
            return False
        return bool(actor_roles & allowed)

    def require(self, actor_id: str, action: str, tenant_id: str) -> None:
        """Raise AccessDeniedError if the actor cannot perform action in tenant."""
        if not self.check(actor_id, action, tenant_id):
            raise AccessDeniedError(
                f"actor {actor_id!r} denied action {action!r} in tenant {tenant_id!r}"
            )
