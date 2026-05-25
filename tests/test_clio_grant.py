"""Tests for client/donna/integrations/clio.py — D4(d) OAuth2 grant orchestrator.

Covers ``grant_oauth_tokens``, ``_emit_oauth_grant_idr``, and the
``token_grant_post`` public alias. Mutation-anchored per Rule 14 + Council R8
(every IDR emitter test fails if intent is renamed, outcome is mis-mapped,
or the predecessor chain breaks).

Hypothesis anchor: H-CLIO-2 (cross-pollination of OAuth-grant IDR pattern
into substrate reduces nexus↔donna duplication by ≥30% within 14 days
post-merge).

Origin: V>> CBC Optimal sprint 2026-05-24.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from donna.integrations import clio


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


class _StubLogger:
    """Records every log_decision invocation for assertion in tests."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._next_id = 0

    def log_decision(
        self,
        what: str,
        why: str,
        alternatives: Optional[list] = None,
        confidence: float = 0.8,
        ritual_id: str = "",
        step_id: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        self._next_id += 1
        decision_id = f"sha256:grant{self._next_id:04d}"
        self.calls.append({
            "what": what,
            "why": why,
            "confidence": confidence,
            "ritual_id": ritual_id,
            "step_id": step_id,
            "context": dict(context or {}),
            "decision_id": decision_id,
        })
        return decision_id


@pytest.fixture
def logger() -> _StubLogger:
    return _StubLogger()


# ---------------------------------------------------------------------------
# 1. Public alias — token_grant_post identical to private _token_grant_post
# ---------------------------------------------------------------------------


def test_token_grant_post_is_public_alias_of_private():
    """Mutation: break alias — consumers importing the public name lose access."""
    assert clio.token_grant_post is clio._token_grant_post


def test_token_grant_post_exported_in_public_all():
    """Mutation: forget __all__ entry — `from donna.integrations.clio import *` breaks."""
    assert "token_grant_post" in clio.__all__


# ---------------------------------------------------------------------------
# 2. IDR pair shape — intent then outcome
# ---------------------------------------------------------------------------


def test_grant_emits_intent_then_outcome_idr_pair_on_success(logger):
    """Mutation: emit only one IDR — chain loses the before/after pairing."""
    with patch.object(clio, "_token_grant_post",
                       return_value={"access_token": "x", "expires_in": 3600}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="auth-code-1", client_id="ci", client_secret="cs",
            logger=logger,
        )
    assert len(logger.calls) == 2
    assert logger.calls[0]["context"]["phase"] == "intent"
    assert logger.calls[1]["context"]["phase"] == "outcome"


def test_grant_emits_intent_then_outcome_idr_pair_on_failure(logger):
    """Mutation: skip outcome IDR on failure — chain hole at exactly the audited moment."""
    with patch.object(clio, "_token_grant_post", return_value=None):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="auth-code-1", client_id="ci", client_secret="cs",
            logger=logger,
        )
    assert len(logger.calls) == 2
    assert logger.calls[1]["context"]["outcome"] == "failure"


def test_outcome_idr_chains_to_intent_idr(logger):
    """Mutation: drop parent_decision_id on outcome — chain forest breaks."""
    with patch.object(clio, "_token_grant_post",
                       return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs",
            logger=logger,
        )
    intent_id = logger.calls[0]["decision_id"]
    assert logger.calls[1]["context"]["parent_decision_id"] == intent_id


def test_intent_idr_chains_to_orchestrator_parent(logger):
    """Mutation: drop parent_decision_id from intent — orchestrator → grant chain breaks."""
    with patch.object(clio, "_token_grant_post",
                       return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs",
            logger=logger,
            parent_decision_id="sha256:routing0001",
        )
    assert logger.calls[0]["context"]["parent_decision_id"] == "sha256:routing0001"


# ---------------------------------------------------------------------------
# 3. IDR intent labels — canonical strings
# ---------------------------------------------------------------------------


def test_intent_idr_uses_canonical_intent_label(logger):
    """Mutation: rename OAUTH_GRANT_INTENT_INTENT — replay tools filter on this string."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[0]["context"]["intent"] == "oauth_grant_intent"
    assert clio.OAUTH_GRANT_INTENT_INTENT == "oauth_grant_intent"


def test_outcome_idr_uses_canonical_intent_label(logger):
    """Mutation: rename OAUTH_GRANT_OUTCOME_INTENT — replay tools filter break."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[1]["context"]["intent"] == "oauth_grant_outcome"
    assert clio.OAUTH_GRANT_OUTCOME_INTENT == "oauth_grant_outcome"


# ---------------------------------------------------------------------------
# 4. Outcome classification — confidence + label
# ---------------------------------------------------------------------------


def test_success_outcome_idr_confidence_one(logger):
    """Mutation: mis-map success confidence — chain misrepresents grant outcome."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[1]["context"]["outcome"] == "success"
    assert logger.calls[1]["confidence"] == 1.0


def test_failure_outcome_idr_confidence_zero(logger):
    """Mutation: classify failure with non-zero confidence — chain lies."""
    with patch.object(clio, "_token_grant_post", return_value=None):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[1]["context"]["outcome"] == "failure"
    assert logger.calls[1]["confidence"] == 0.0


def test_intent_idr_confidence_one(logger):
    """Mutation: intent confidence <1 — implies uncertainty about the attempt itself."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[0]["confidence"] == 1.0


# ---------------------------------------------------------------------------
# 5. Grant-type dispatch — authorization_code + refresh_token
# ---------------------------------------------------------------------------


def test_authorization_code_grant_sends_code_param(logger):
    """Mutation: drop code from params — Clio would 400."""
    captured: Dict[str, Any] = {}

    def _capture(params):
        captured.update(params)
        return {"access_token": "x"}

    with patch.object(clio, "_token_grant_post", side_effect=_capture):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="THE-CODE", client_id="ci", client_secret="cs",
            redirect_uri="https://x.test/cb", logger=logger,
        )
    assert captured["code"] == "THE-CODE"
    assert captured["grant_type"] == "authorization_code"
    assert captured["redirect_uri"] == "https://x.test/cb"


def test_refresh_token_grant_sends_refresh_token_param(logger):
    """Mutation: drop refresh_token from params — refresh would 400."""
    captured: Dict[str, Any] = {}

    def _capture(params):
        captured.update(params)
        return {"access_token": "x"}

    with patch.object(clio, "_token_grant_post", side_effect=_capture):
        clio.grant_oauth_tokens(
            "acme", grant_type="refresh_token",
            refresh_token="OLD-REFRESH", client_id="ci", client_secret="cs",
            logger=logger,
        )
    assert captured["refresh_token"] == "OLD-REFRESH"
    assert captured["grant_type"] == "refresh_token"


def test_authorization_code_grant_without_code_fails_closed(logger):
    """Mutation: skip code-required check — would POST with empty code, Clio 400."""
    with patch.object(clio, "_token_grant_post") as mock_post:
        payload, decision_id = clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            client_id="ci", client_secret="cs", logger=logger,
        )
    assert payload is None
    assert not mock_post.called
    assert len(logger.calls) == 2
    assert logger.calls[1]["context"]["outcome"] == "failure"


def test_refresh_token_grant_without_refresh_fails_closed(logger):
    """Mutation: skip refresh-required check — empty refresh would POST."""
    with patch.object(clio, "_token_grant_post") as mock_post:
        payload, _ = clio.grant_oauth_tokens(
            "acme", grant_type="refresh_token",
            client_id="ci", client_secret="cs", logger=logger,
        )
    assert payload is None
    assert not mock_post.called


def test_unknown_grant_type_fails_closed(logger):
    """Mutation: accept unknown grant_type — substrate would forward garbage to Clio."""
    with patch.object(clio, "_token_grant_post") as mock_post:
        payload, _ = clio.grant_oauth_tokens(
            "acme", grant_type="totally_made_up",
            logger=logger,
        )
    assert payload is None
    assert not mock_post.called
    assert logger.calls[-1]["context"]["outcome"] == "failure"


# ---------------------------------------------------------------------------
# 6. Logger optionality — substrate works without injected logger
# ---------------------------------------------------------------------------


def test_grant_without_logger_emits_no_idr_returns_payload():
    """Mutation: NPE when logger=None — substrate must tolerate logger-less callers."""
    with patch.object(clio, "_token_grant_post",
                       return_value={"access_token": "x", "expires_in": 60}):
        payload, decision_id = clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs",
        )
    assert payload == {"access_token": "x", "expires_in": 60}
    assert decision_id is None


def test_grant_without_logger_on_failure():
    """Mutation: NPE when logger=None and grant fails — must still return None payload."""
    with patch.object(clio, "_token_grant_post", return_value=None):
        payload, decision_id = clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs",
        )
    assert payload is None
    assert decision_id is None


# ---------------------------------------------------------------------------
# 7. Return shape — (payload, outcome_decision_id)
# ---------------------------------------------------------------------------


def test_grant_returns_tuple_payload_and_outcome_decision_id(logger):
    """Mutation: return outcome IDR's parent (intent IDR) — caller can't chain follow-ons."""
    with patch.object(clio, "_token_grant_post",
                       return_value={"access_token": "x"}):
        payload, decision_id = clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert decision_id == logger.calls[1]["decision_id"]
    assert payload == {"access_token": "x"}


# ---------------------------------------------------------------------------
# 8. Context fields — tenant_id, grant_type, status preserved
# ---------------------------------------------------------------------------


def test_idr_context_carries_tenant_id(logger):
    """Mutation: hardcode tenant_id in context — cross-tenant privacy break."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "tenant-42", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[0]["context"]["tenant_id"] == "tenant-42"
    assert logger.calls[1]["context"]["tenant_id"] == "tenant-42"


def test_idr_context_carries_grant_type(logger):
    """Mutation: hardcode grant_type — chain misrepresents which flow ran."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="refresh_token",
            refresh_token="r", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[0]["context"]["grant_type"] == "refresh_token"
    assert logger.calls[1]["context"]["grant_type"] == "refresh_token"


def test_outcome_idr_carries_status_hint_on_success(logger):
    """Mutation: drop status — operator can't distinguish HTTP outcomes in chain."""
    with patch.object(clio, "_token_grant_post", return_value={"access_token": "x"}):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[1]["context"]["status"] == 200


def test_outcome_idr_carries_status_zero_on_failure(logger):
    """Mutation: pretend failure had HTTP 200 — chain lies about transport state."""
    with patch.object(clio, "_token_grant_post", return_value=None):
        clio.grant_oauth_tokens(
            "acme", grant_type="authorization_code",
            code="c", client_id="ci", client_secret="cs", logger=logger,
        )
    assert logger.calls[1]["context"]["status"] == 0


# ---------------------------------------------------------------------------
# 9. Module-level invariants
# ---------------------------------------------------------------------------


def test_grant_oauth_tokens_in_public_all():
    """Mutation: forget __all__ entry — `from donna.integrations.clio import *` breaks."""
    assert "grant_oauth_tokens" in clio.__all__


def test_existing_public_surface_preserved():
    """Mutation: D4(d) accidentally removes existing exports — backward-compat regression."""
    required = {"call", "load_config", "refresh_access_token",
                "ClioConfig", "ClioResult", "DecisionLoggerProtocol",
                "CLIO_API_BASE"}
    assert required.issubset(set(clio.__all__))
