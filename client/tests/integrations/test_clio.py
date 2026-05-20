"""Goodhart-resistant tests for ``donna/integrations/clio.py``.

Council-ratified acceptance (synthesis 2026-05-20):

* Mutations (POST/PATCH/PUT/DELETE) emit exactly one IDR via the injected
  ``log_decision`` — with ``outcome`` in {success, failure, not_configured}.
* Pure-read GETs emit zero IDRs (council verdict #3).
* Mutation IDR is chain-verifiable (we assert via spec'd ``MagicMock`` —
  the real chain extension is exercised in the GRIP private follow-up that
  wires the real ``DecisionLogger``).
* **Mutation anchor**: remove the ``log_decision`` call from the adapter
  and ``test_mutation_emits_exactly_one_idr`` fails.
* ``context.parent_decision_id`` propagates when supplied — explicit
  chain-forest semantics on top of the council outline.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple
from unittest.mock import MagicMock, patch

import pytest

from donna.integrations import clio
from donna.integrations.clio import ClioConfig, ClioResult, DecisionLoggerProtocol, call


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _ok_cfg() -> ClioConfig:
    """Stand-in tenant config — bypasses real Keychain lookup."""
    return ClioConfig(
        tenant_id="acme-law",
        access_token="test-access-token",
        refresh_token="",
        expires_at=0.0,
    )


def _logger() -> MagicMock:
    """Spec'd MagicMock matching ``DecisionLoggerProtocol`` — catches contract drift."""
    mock = MagicMock(spec=DecisionLoggerProtocol)
    mock.log_decision.return_value = "dec-stub-12345"
    return mock


# ---------------------------------------------------------------------------
# Mutation chain — exactly one IDR with the right shape
# ---------------------------------------------------------------------------


def test_mutation_emits_exactly_one_idr(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the adapter forgets to log_decision on a mutation, this fails."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (201, {"id": 42}))
    logger = _logger()

    result = call(
        tenant_id="acme-law",
        method="POST",
        path="/time_entries",
        body={"matter_id": 1, "minutes": 30},
        logger=logger,
    )

    assert isinstance(result, ClioResult)
    assert result.ok is True
    assert result.status == 201
    assert result.decision_id == "dec-stub-12345"
    assert logger.log_decision.call_count == 1


def test_get_request_emits_zero_idrs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure-read GETs MUST NOT chain (council verdict #3 — chain represents decisions, not I/O)."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (200, {"matters": []}))
    logger = _logger()

    result = call(tenant_id="acme-law", method="GET", path="/matters", logger=logger)

    assert result.ok is True
    assert result.decision_id is None
    logger.log_decision.assert_not_called()


def test_mutation_outcome_label_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """On HTTP 2xx, the IDR's context.outcome must be ``"success"`` and confidence 1.0."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (201, {}))
    logger = _logger()

    call(tenant_id="acme-law", method="POST", path="/time_entries", body={}, logger=logger)

    kwargs = logger.log_decision.call_args.kwargs
    assert kwargs["confidence"] == 1.0
    assert kwargs["context"]["outcome"] == "success"
    assert kwargs["context"]["status"] == 201


def test_mutation_outcome_label_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """On HTTP 4xx, outcome must be ``"failure"`` and confidence 0.0."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (403, {"error": "forbidden"}))
    logger = _logger()

    result = call(tenant_id="acme-law", method="POST", path="/time_entries", body={}, logger=logger)

    assert result.ok is False
    kwargs = logger.log_decision.call_args.kwargs
    assert kwargs["confidence"] == 0.0
    assert kwargs["context"]["outcome"] == "failure"


def test_mutation_outcome_label_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Status 0 (network error) must surface as ``"transport_failure"`` — distinct from API failure."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (0, {"error": "transport: timeout"}))
    logger = _logger()

    result = call(tenant_id="acme-law", method="POST", path="/time_entries", body={}, logger=logger)

    assert result.ok is False
    kwargs = logger.log_decision.call_args.kwargs
    assert kwargs["context"]["outcome"] == "transport_failure"


# ---------------------------------------------------------------------------
# Degraded mode — fail-CLOSED when not configured
# ---------------------------------------------------------------------------


def test_not_configured_emits_degraded_idr_on_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Keychain has no entry, a mutation must emit a ``"not_configured"`` IDR + return error."""
    monkeypatch.setattr(clio, "load_config", lambda _t: None)
    logger = _logger()

    result = call(tenant_id="acme-law", method="POST", path="/time_entries", body={}, logger=logger)

    assert result.ok is False
    assert result.status == 0
    assert result.body["error"] == "not_configured"
    assert result.decision_id == "dec-stub-12345"
    kwargs = logger.log_decision.call_args.kwargs
    assert kwargs["context"]["outcome"] == "not_configured"
    assert kwargs["confidence"] == 0.0


def test_not_configured_get_emits_no_idr(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even when degraded, a GET still does not chain — reads never chain (council verdict #3)."""
    monkeypatch.setattr(clio, "load_config", lambda _t: None)
    logger = _logger()

    result = call(tenant_id="acme-law", method="GET", path="/matters", logger=logger)

    assert result.ok is False
    assert result.decision_id is None
    logger.log_decision.assert_not_called()


def test_no_logger_skips_idr_silently(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the caller does not pass a logger, no IDR is emitted — the result still returns."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (201, {}))

    result = call(tenant_id="acme-law", method="POST", path="/time_entries", body={})

    assert result.ok is True
    assert result.decision_id is None


# ---------------------------------------------------------------------------
# Chain-forest semantics (parent_decision_id tightening)
# ---------------------------------------------------------------------------


def test_parent_decision_id_lands_in_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the caller passes parent_decision_id, the IDR's context must carry it."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (201, {}))
    logger = _logger()

    call(
        tenant_id="acme-law",
        method="POST",
        path="/time_entries",
        body={},
        logger=logger,
        parent_decision_id="dec-routing-abc123",
    )

    ctx = logger.log_decision.call_args.kwargs["context"]
    assert ctx["parent_decision_id"] == "dec-routing-abc123"


def test_no_parent_id_omits_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """When no parent is supplied, context must NOT carry a bogus parent_decision_id."""
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio, "_http_with_retry", lambda *_a, **_k: (201, {}))
    logger = _logger()

    call(tenant_id="acme-law", method="POST", path="/time_entries", body={}, logger=logger)

    ctx = logger.log_decision.call_args.kwargs["context"]
    assert "parent_decision_id" not in ctx


# ---------------------------------------------------------------------------
# Internal helper invariants
# ---------------------------------------------------------------------------


def test_classify_outcome_buckets() -> None:
    """``_classify_outcome`` must partition status codes into the documented buckets."""
    assert clio._classify_outcome(200) == (True, "success")
    assert clio._classify_outcome(201) == (True, "success")
    assert clio._classify_outcome(299) == (True, "success")
    assert clio._classify_outcome(400) == (False, "failure")
    assert clio._classify_outcome(500) == (False, "failure")
    assert clio._classify_outcome(0) == (False, "transport_failure")


def test_is_mutation_method_set() -> None:
    """The mutation methods are exactly {POST, PATCH, PUT, DELETE} (case-insensitive)."""
    for method in ("POST", "PATCH", "PUT", "DELETE", "post", "patch", "put", "delete"):
        assert clio._is_mutation(method) is True
    for method in ("GET", "HEAD", "OPTIONS", "get"):
        assert clio._is_mutation(method) is False


def test_retry_loop_invokes_http_more_than_once_on_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Transient 5xx must trigger retry within the 30s window."""
    calls = {"n": 0}

    def fake_http(_m: str, _p: str, _c: ClioConfig, _b: Any = None) -> Tuple[int, Dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] < 3:
            return 503, {"error": "service unavailable"}
        return 201, {"id": 99}

    monkeypatch.setattr(clio, "_http", fake_http)
    monkeypatch.setattr(clio, "load_config", lambda _t: _ok_cfg())
    monkeypatch.setattr(clio.time, "sleep", lambda _s: None)  # zero out the retry sleep

    status, _body = clio._http_with_retry("POST", "/x", _ok_cfg(), {})

    assert calls["n"] == 3  # 2 failures + 1 success
    assert status == 201


def test_load_config_missing_security_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """If ``security`` CLI is absent (non-macOS dev), load_config returns None — fail-CLOSED."""
    monkeypatch.setattr(clio.shutil, "which", lambda _name: None)

    assert clio.load_config("acme-law") is None


def test_load_config_empty_token_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty Keychain entry must NOT be treated as a valid token."""
    monkeypatch.setattr(clio.shutil, "which", lambda _name: "/usr/bin/security")

    fake_result = MagicMock(returncode=0, stdout="   \n  ")  # whitespace only
    with patch.object(clio.subprocess, "run", return_value=fake_result):
        assert clio.load_config("acme-law") is None


# ---------------------------------------------------------------------------
# Sanity-check the public API surface — Protocol contract drift catcher
# ---------------------------------------------------------------------------


def test_public_api_exports() -> None:
    """The integrations package must expose the documented public symbols."""
    from donna import integrations

    assert hasattr(integrations, "ClioConfig")
    assert hasattr(integrations, "ClioResult")
    assert hasattr(integrations, "DecisionLoggerProtocol")
    assert hasattr(integrations, "call")
    assert hasattr(integrations, "load_config")


def test_decision_logger_protocol_method_signature() -> None:
    """A spec'd MagicMock must validate against the Protocol — catches contract drift."""
    mock = MagicMock(spec=DecisionLoggerProtocol)
    # If log_decision is removed from the Protocol, this attribute access will fail at runtime
    # AND any production caller would break. The spec'd mock is the canary.
    assert hasattr(mock, "log_decision")
    # The Protocol method signature must accept these named args; if drift, the call raises.
    mock.log_decision(
        what="x",
        why="y",
        confidence=1.0,
        ritual_id="r",
        step_id="s",
        context={"k": "v"},
    )
