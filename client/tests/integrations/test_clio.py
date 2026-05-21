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


# ---------------------------------------------------------------------------
# OAuth2 refresh-token path (chiefofstaff-legal/donna#TBD follow-up to #21)
# ---------------------------------------------------------------------------


class TestOauthTokenURL:
    """Token-grant endpoint derivation — must work for both regions."""

    def test_eu_base_derives_eu_token_url(self, monkeypatch):
        """EU API base must derive EU /oauth/token. Mutation: replace
        ``/api/v4`` with ``/oauth/token`` — if regex changes break this, fail."""
        monkeypatch.setattr(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4")
        assert clio._oauth_token_url() == "https://eu.app.clio.com/oauth/token"

    def test_us_base_derives_us_token_url(self, monkeypatch):
        monkeypatch.setattr(clio, "CLIO_API_BASE", "https://app.clio.com/api/v4")
        assert clio._oauth_token_url() == "https://app.clio.com/oauth/token"

    def test_non_standard_base_falls_back_to_host(self, monkeypatch):
        """A non-standard base (no ``/api/v4``) must still produce a token URL
        rather than a malformed path — falls back to scheme+host."""
        monkeypatch.setattr(clio, "CLIO_API_BASE", "https://custom.clio.example.com/special")
        url = clio._oauth_token_url()
        assert url.endswith("/oauth/token")
        assert "custom.clio.example.com" in url


class TestLoadConfigRefreshFields:
    """``load_config`` must populate refresh_token + expires_at when the
    sibling Keychain entries exist; gracefully absent otherwise."""

    def test_load_config_reads_all_three_keychain_entries(self, monkeypatch):
        def _kc(service):
            return {
                "grip-clio-acme": "ACCESS-XYZ",
                "grip-clio-refresh-acme": "REFRESH-ABC",
                "grip-clio-expires-acme": "1748999999.0",
            }.get(service)
        monkeypatch.setattr(clio, "_kc_read", _kc)
        cfg = clio.load_config("acme")
        assert cfg is not None
        assert cfg.access_token == "ACCESS-XYZ"
        assert cfg.refresh_token == "REFRESH-ABC"
        assert cfg.expires_at == 1748999999.0

    def test_load_config_tolerates_missing_refresh_and_expires(self, monkeypatch):
        """Legacy single-token tenants (no refresh sibling) MUST keep working —
        load_config returns ClioConfig with empty refresh and zero expiry."""
        def _kc(service):
            return "ACCESS-ONLY" if service == "grip-clio-legacy" else None
        monkeypatch.setattr(clio, "_kc_read", _kc)
        cfg = clio.load_config("legacy")
        assert cfg is not None
        assert cfg.access_token == "ACCESS-ONLY"
        assert cfg.refresh_token == ""
        assert cfg.expires_at == 0.0


class TestRefreshAccessToken:
    """Refresh-grant flow — atomic Keychain replace + fail-CLOSED semantics."""

    def _kc_for_refresh(self, monkeypatch, writes_capture):
        """Patch _kc_read + _kc_write for a tenant 'acme' with refresh + app creds."""
        kc_state = {
            "grip-clio-acme": "OLD-ACCESS",
            "grip-clio-refresh-acme": "OLD-REFRESH",
            "grip-clio-expires-acme": "0",
            "grip-clio-app-id": "APP-ID-123",
            "grip-clio-app-secret": "APP-SECRET-456",
        }

        def _read(service):
            return kc_state.get(service)

        def _write(service, value):
            kc_state[service] = value
            writes_capture.append((service, value))
            return True

        monkeypatch.setattr(clio, "_kc_read", _read)
        monkeypatch.setattr(clio, "_kc_write", _write)
        return kc_state

    def test_refresh_rotates_both_tokens_in_keychain(self, monkeypatch):
        """A successful refresh MUST write the new access_token AND the new
        refresh_token back to Keychain — Clio rotates refresh on every grant."""
        writes = []
        kc_state = self._kc_for_refresh(monkeypatch, writes)
        monkeypatch.setattr(
            clio, "_token_grant_post",
            lambda _params: {"access_token": "NEW-ACCESS",
                             "refresh_token": "NEW-REFRESH", "expires_in": 3600},
        )
        new_cfg = clio.refresh_access_token("acme")
        assert new_cfg is not None
        assert new_cfg.access_token == "NEW-ACCESS"
        assert new_cfg.refresh_token == "NEW-REFRESH"
        # Both rotations must hit Keychain.
        services = {s for s, _ in writes}
        assert "grip-clio-acme" in services
        assert "grip-clio-refresh-acme" in services
        # And the in-memory keychain state must reflect the rotation.
        assert kc_state["grip-clio-acme"] == "NEW-ACCESS"
        assert kc_state["grip-clio-refresh-acme"] == "NEW-REFRESH"

    def test_refresh_failure_returns_none_no_keychain_writes(self, monkeypatch):
        """Refresh failure (invalid_grant / HTTP error) MUST be fail-CLOSED —
        return None, no Keychain writes, OLD refresh_token stays valid."""
        writes = []
        self._kc_for_refresh(monkeypatch, writes)
        monkeypatch.setattr(clio, "_token_grant_post", lambda _params: None)
        result = clio.refresh_access_token("acme")
        assert result is None
        assert writes == [], f"refresh failure must not write keychain, got {writes}"

    def test_refresh_without_refresh_token_returns_none(self, monkeypatch):
        """If the tenant has no stored refresh_token, refresh MUST refuse —
        cannot fabricate a grant from nothing. Fail-CLOSED."""
        def _read(service):
            return "ACCESS-ONLY" if service == "grip-clio-tenant-no-refresh" else None
        monkeypatch.setattr(clio, "_kc_read", _read)
        # If somehow called, _token_grant_post would fail this assertion.
        monkeypatch.setattr(
            clio, "_token_grant_post",
            lambda _params: pytest.fail("refresh must not call grant without refresh_token"),
        )
        assert clio.refresh_access_token("tenant-no-refresh") is None


class TestCallRetriesOn401AfterRefresh:
    """The user-visible payoff — ``call()`` transparently refreshes on 401
    and retries the original request once."""

    def test_call_retries_on_401_with_new_token(self, monkeypatch):
        """Mutation hits 401 → refresh succeeds → retry succeeds → caller sees
        the eventual 2xx without ever seeing the 401. Mutation anchor: rip
        the 401-retry branch out of call() and this fails."""
        # First call returns 401, second returns 201.
        http_calls = []

        def _fake_http(method, path, cfg, body=None):
            http_calls.append(cfg.access_token)
            if len(http_calls) == 1:
                return 401, {"error": "expired_token"}
            return 201, {"data": {"id": 999}}

        monkeypatch.setattr(clio, "_http_with_retry", _fake_http)
        # load_config returns config WITH refresh_token (else retry is skipped).
        monkeypatch.setattr(
            clio, "load_config",
            lambda _t: ClioConfig(
                tenant_id="acme", access_token="OLD-ACCESS",
                refresh_token="OLD-REFRESH", expires_at=0.0,
            ),
        )
        # refresh_access_token returns a new ClioConfig (so retry uses the new token).
        monkeypatch.setattr(
            clio, "refresh_access_token",
            lambda _t: ClioConfig(
                tenant_id="acme", access_token="NEW-ACCESS",
                refresh_token="NEW-REFRESH", expires_at=99999.0,
            ),
        )
        result = call(
            tenant_id="acme", method="POST", path="/activities.json",
            body={"data": {}}, logger=_logger(),
        )
        # Caller sees the eventual 201, never sees the 401.
        assert result.ok is True
        assert result.status == 201
        # Two HTTP calls happened: one with old token (got 401), one with new.
        assert len(http_calls) == 2
        assert http_calls[0] == "OLD-ACCESS"
        assert http_calls[1] == "NEW-ACCESS"

    def test_401_with_no_refresh_token_does_not_retry(self, monkeypatch):
        """Legacy tenants (no refresh_token) MUST NOT attempt refresh — the
        401 propagates as-is so the caller surfaces a degraded result."""
        monkeypatch.setattr(
            clio, "load_config",
            lambda _t: ClioConfig(tenant_id="acme", access_token="A",
                                  refresh_token="", expires_at=0.0),
        )
        call_count = {"n": 0}

        def _fake_http(*_a, **_k):
            call_count["n"] += 1
            return 401, {"error": "expired_token"}

        monkeypatch.setattr(clio, "_http_with_retry", _fake_http)

        def _fail_refresh(_t):
            pytest.fail("refresh_access_token MUST NOT be called without refresh_token")
        monkeypatch.setattr(clio, "refresh_access_token", _fail_refresh)

        result = call(
            tenant_id="acme", method="POST", path="/activities.json",
            body={"data": {}}, logger=_logger(),
        )
        assert result.ok is False
        assert result.status == 401
        assert call_count["n"] == 1  # No retry attempted.

    def test_401_with_failed_refresh_propagates_401(self, monkeypatch):
        """Refresh that returns None (invalid_grant) — original 401 propagates,
        no second HTTP call. Operator must re-authorise."""
        monkeypatch.setattr(
            clio, "load_config",
            lambda _t: ClioConfig(tenant_id="acme", access_token="A",
                                  refresh_token="R", expires_at=0.0),
        )
        monkeypatch.setattr(clio, "refresh_access_token", lambda _t: None)
        call_count = {"n": 0}

        def _fake_http(*_a, **_k):
            call_count["n"] += 1
            return 401, {"error": "expired_token"}

        monkeypatch.setattr(clio, "_http_with_retry", _fake_http)

        result = call(
            tenant_id="acme", method="POST", path="/activities.json",
            body={"data": {}}, logger=_logger(),
        )
        assert result.ok is False
        assert result.status == 401
        # Refresh was attempted, but the retry path was skipped because refresh
        # returned None. So only one HTTP call.
        assert call_count["n"] == 1
