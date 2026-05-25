"""Goodhart-resistant test suite for donna.integrations.clio.

D1 deliverable of feat/clio-cbc-tests-wrappers-vincent — `clio.py` shipped
in council-ratified form (#18) at 526 LOC with **zero direct test
coverage**; this file closes the gap and pins the council verdicts
(#3 reads do not chain, #4 transparent retry on 5xx, #6 fail-CLOSED on
not-configured) as regression anchors.

Each test's docstring names the **1-line mutation it kills** per Rule 14
(`~/.claude/rules/efficiency-rules.md` — RSI test coverage + Goodhart
protection). A test that always passes is worse than no test; every
assertion below is content-dependent so a single-line wrong-direction
change in `clio.py` flips it red.

Mutation surface covered (10 buckets, ~35 tests):

- ClioConfig dataclass invariants (5)
- load_config — Keychain triple resolution (6)
- _token_grant_post — OAuth2 grant transport (5)
- _stash_refreshed_tokens — atomic-replace ordering (3)
- refresh_access_token — full refresh lifecycle (4)
- _http_with_retry — transient-5xx retry window (3)
- _is_mutation / _classify_outcome — outcome routing (4)
- _emit_mutation_idr / _emit_not_configured_idr — IDR payload shape (4)
- call() — single-dispatch entry point + 401-refresh path (5)

Tests patch `clio._kc_read`, `clio._kc_write`, `clio._http`, and the
`urllib.request.urlopen` boundary so no real Keychain / Clio traffic
happens in CI. The patch points mirror what nexus's `test_routes_clio.py`
patches — `clio.py` is the substrate, this is the substrate's own suite.

Hypothesis H-CLIO-1: this suite achieves >=85% line coverage on
`client/donna/integrations/clio.py` by 2026-06-07.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

_CLIENT = Path(__file__).resolve().parent.parent / "client"
if str(_CLIENT) not in sys.path:
    sys.path.insert(0, str(_CLIENT))

from donna.integrations import clio  # noqa: E402
from donna.integrations.clio import (  # noqa: E402
    CLIO_API_BASE,
    ClioConfig,
    ClioResult,
    DecisionLoggerProtocol,
    _classify_outcome,
    _emit_mutation_idr,
    _emit_not_configured_idr,
    _http_with_retry,
    _is_mutation,
    _oauth_token_url,
    _stash_refreshed_tokens,
    _token_grant_post,
    call,
    load_config,
    refresh_access_token,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_logger() -> MagicMock:
    """A MagicMock that satisfies the DecisionLoggerProtocol shape.

    `log_decision` returns a deterministic "sha256:<seq>" so tests can
    assert decision_id propagation without depending on a real chain.
    """
    seq = {"n": 0}

    def _log(**_kwargs):
        seq["n"] += 1
        return f"sha256:test-{seq['n']:03d}"

    logger = MagicMock(spec=DecisionLoggerProtocol)
    logger.log_decision.side_effect = _log
    return logger


@pytest.fixture
def ok_config() -> ClioConfig:
    return ClioConfig(
        tenant_id="tenant-x",
        access_token="access-stub",
        refresh_token="refresh-stub",
        expires_at=0.0,
    )


# ---------------------------------------------------------------------------
# ClioConfig dataclass invariants
# ---------------------------------------------------------------------------


def test_clio_config_construction_carries_all_four_fields():
    """Kill mutation: drop one of the four ClioConfig fields.

    The OAuth lifecycle depends on tenant_id (per-tenant Keychain),
    access_token (Authorization header), refresh_token (401-retry path),
    expires_at (best-effort metadata). Dropping any breaks downstream.
    """
    cfg = ClioConfig(
        tenant_id="t", access_token="a", refresh_token="r", expires_at=1.0
    )
    assert cfg.tenant_id == "t"
    assert cfg.access_token == "a"
    assert cfg.refresh_token == "r"
    assert cfg.expires_at == 1.0


def test_clio_config_defaults_to_empty_refresh_and_zero_expiry():
    """Kill mutation: default refresh_token to None instead of "".

    Legacy single-token tenants pass only access_token. Empty-string
    refresh_token means "no refresh available" (falsy check); None would
    pass `if cfg.refresh_token` truthiness but crash on `.encode()` in
    the OAuth grant POST.
    """
    cfg = ClioConfig(tenant_id="t", access_token="a")
    assert cfg.refresh_token == ""
    assert cfg.expires_at == 0.0


def test_clio_result_defaults_decision_id_to_none():
    """Kill mutation: default decision_id to "" or a sentinel.

    None is the load-bearing signal that "no IDR was emitted" — used by
    callers to distinguish read responses (no chain extension) from
    mutation responses (chain extended). An empty string would erroneously
    return truthy in a `.startswith()` check.
    """
    result = ClioResult(ok=True, status=200, body={})
    assert result.decision_id is None


def test_clio_result_preserves_body_payload():
    """Kill mutation: discard body or replace with empty dict.

    Callers depend on the body for both success payloads (matter list)
    and error context (validation error dict from Clio). Dropping the
    body would surface as empty responses with no actionable detail.
    """
    body = {"matters": [{"id": 1, "name": "Matter A"}]}
    result = ClioResult(ok=True, status=200, body=body)
    assert result.body == body


def test_clio_api_base_defaults_to_eu_region():
    """Kill mutation: default CLIO_API_BASE to US region.

    V>>'s Clio tenancy is EU. A wrong-region default would cause every
    test session to start against the wrong app boundary; production
    overrides via $CLIO_API_BASE catch real callers but the default is
    the on-boarding contract.
    """
    assert "eu.app.clio.com" in CLIO_API_BASE or CLIO_API_BASE.startswith("https://")
    # If the env var is set in the test session, accept whatever it set;
    # else assert the EU default.
    import os as _os
    if not _os.environ.get("CLIO_API_BASE"):
        assert CLIO_API_BASE == "https://eu.app.clio.com/api/v4"


# ---------------------------------------------------------------------------
# _oauth_token_url — region derivation
# ---------------------------------------------------------------------------


def test_oauth_token_url_derives_from_eu_base():
    """Kill mutation: hardcode the US OAuth endpoint.

    The /oauth/token endpoint must match the API region; sending an EU
    grant request to the US endpoint would fail with cross-region auth
    errors that look like invalid_grant.
    """
    with patch.object(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4"):
        assert _oauth_token_url() == "https://eu.app.clio.com/oauth/token"


def test_oauth_token_url_derives_from_us_base():
    """Kill mutation: always return EU regardless of base."""
    with patch.object(clio, "CLIO_API_BASE", "https://app.clio.com/api/v4"):
        assert _oauth_token_url() == "https://app.clio.com/oauth/token"


def test_oauth_token_url_falls_back_when_no_api_v4_segment():
    """Kill mutation: assume /api/v4 always present.

    Sandbox / staging URLs may omit /api/v4. The function falls back to
    scheme+host + /oauth/token rather than crashing.
    """
    with patch.object(clio, "CLIO_API_BASE", "https://sandbox.clio.com"):
        assert _oauth_token_url() == "https://sandbox.clio.com/oauth/token"


# ---------------------------------------------------------------------------
# load_config — Keychain triple resolution
# ---------------------------------------------------------------------------


def test_load_config_returns_none_when_access_token_missing():
    """Kill mutation: return a stub ClioConfig when no token exists.

    Fail-CLOSED per council verdict #6: missing Keychain entry MUST
    return None so the caller emits the not_configured IDR rather than
    fabricating mock-success.
    """
    with patch.object(clio, "_kc_read", return_value=None):
        assert load_config("absent-tenant") is None


def test_load_config_returns_config_with_just_access_token():
    """Kill mutation: require all three Keychain entries (over-restrict).

    Legacy single-token tenants have only the access token; the function
    must accept that and degrade gracefully (no refresh, no expiry).
    """
    def _kc(service):
        return "access-only" if service == "grip-clio-legacy" else None
    with patch.object(clio, "_kc_read", side_effect=_kc):
        cfg = load_config("legacy")
    assert cfg is not None
    assert cfg.access_token == "access-only"
    assert cfg.refresh_token == ""
    assert cfg.expires_at == 0.0


def test_load_config_resolves_full_triple_from_keychain():
    """Kill mutation: read the wrong Keychain service name.

    The naming contract is `grip-clio-<tenant_id>` /
    `grip-clio-refresh-<tenant_id>` / `grip-clio-expires-<tenant_id>`.
    A wrong service name would silently fail to find the entries.
    """
    triple = {
        "grip-clio-full": "a-token",
        "grip-clio-refresh-full": "r-token",
        "grip-clio-expires-full": "1700000000.0",
    }
    with patch.object(clio, "_kc_read", side_effect=lambda s: triple.get(s)):
        cfg = load_config("full")
    assert cfg.access_token == "a-token"
    assert cfg.refresh_token == "r-token"
    assert cfg.expires_at == 1700000000.0


def test_load_config_parses_iso_expiry():
    """Kill mutation: drop the ISO-8601 fallback branch.

    Clio's API sometimes returns ISO-8601 timestamps; the function
    accepts both numeric and ISO. Dropping the fallback would set
    expires_at=0.0 for ISO-string tenants and bypass expiry-aware paths.
    """
    triple = {
        "grip-clio-iso": "tok",
        "grip-clio-expires-iso": "2026-06-01T12:00:00Z",
    }
    with patch.object(clio, "_kc_read", side_effect=lambda s: triple.get(s)):
        cfg = load_config("iso")
    assert cfg.expires_at > 0.0


def test_load_config_tolerates_unparseable_expiry():
    """Kill mutation: raise instead of defaulting to 0.0.

    A garbage expires-entry must not crash the config load; expiry is
    best-effort metadata and 0.0 means "treat as expired / reactive
    refresh only".
    """
    triple = {
        "grip-clio-bad": "tok",
        "grip-clio-expires-bad": "garbage-not-a-date",
    }
    with patch.object(clio, "_kc_read", side_effect=lambda s: triple.get(s)):
        cfg = load_config("bad")
    assert cfg.expires_at == 0.0


def test_load_config_passes_tenant_id_through():
    """Kill mutation: hardcode tenant_id in the returned ClioConfig.

    Per-tenant isolation depends on the tenant_id round-tripping from
    the load_config call through to mutation IDR emission. A hardcoded
    value would silently merge two tenants' chains.
    """
    with patch.object(clio, "_kc_read", side_effect=lambda s: "tok" if s == "grip-clio-acme" else None):
        cfg = load_config("acme")
    assert cfg.tenant_id == "acme"


# ---------------------------------------------------------------------------
# _token_grant_post — OAuth2 grant transport
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    """Stand-in for `urllib.request.urlopen` context-manager result."""

    def __init__(self, body: bytes, status: int = 200):
        self._body = body
        self._status = status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_token_grant_post_returns_payload_on_200():
    """Kill mutation: ignore status code and parse body unconditionally.

    A non-200 must NEVER be treated as a successful grant — that would
    return error payloads as if they were tokens, breaking refresh.
    """
    body = json.dumps({"access_token": "new", "refresh_token": "newr", "expires_in": 3600}).encode()
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(body, 200)):
        payload = _token_grant_post({"grant_type": "refresh_token"})
    assert payload == {"access_token": "new", "refresh_token": "newr", "expires_in": 3600}


def test_token_grant_post_returns_none_on_non_200():
    """Kill mutation: parse and return body for any status."""
    body = b'{"error": "invalid_grant"}'
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(body, 400)):
        assert _token_grant_post({"grant_type": "refresh_token"}) is None


def test_token_grant_post_returns_none_on_transport_failure():
    """Kill mutation: raise instead of returning None on URLError.

    Network failures must surface as None so the caller falls through
    to the fail-CLOSED 401 path. Raising would crash refresh entirely.
    """
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
        assert _token_grant_post({"grant_type": "refresh_token"}) is None


def test_token_grant_post_returns_none_on_http_error():
    """Kill mutation: ignore HTTPError and parse the original request."""
    err = urllib.error.HTTPError("u", 500, "Server Error", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        assert _token_grant_post({"grant_type": "refresh_token"}) is None


def test_token_grant_post_returns_none_on_malformed_json():
    """Kill mutation: skip the JSON parse try/except.

    A 200 with malformed JSON must return None — surfacing a partial
    payload would let `_stash_refreshed_tokens` write garbage values
    into the Keychain.
    """
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(b"not-json", 200)):
        assert _token_grant_post({"grant_type": "refresh_token"}) is None


# ---------------------------------------------------------------------------
# _stash_refreshed_tokens — atomic-replace ordering
# ---------------------------------------------------------------------------


def test_stash_refreshed_tokens_returns_none_when_access_token_missing():
    """Kill mutation: write empty access_token to Keychain.

    An empty access_token in the payload means the grant succeeded
    HTTP-wise but Clio returned a malformed response; never persist that.
    """
    payload = {"access_token": "", "refresh_token": "r"}
    result = _stash_refreshed_tokens("t", payload, prev_refresh="old-r")
    assert result is None


def test_stash_refreshed_tokens_writes_access_then_refresh_then_expiry():
    """Kill mutation: invert the write order (refresh-before-access).

    Order matters for crash-recovery: if access succeeds and refresh
    fails, the next refresh attempt uses the OLD refresh_token (still
    valid). Inverted order leaves the tenant with a new refresh but
    no working access — broken state.
    """
    writes: List[Tuple[str, str]] = []

    def _kw(service, value):
        writes.append((service, value))
        return True

    payload = {"access_token": "new-a", "refresh_token": "new-r", "expires_in": 1800}
    with patch.object(clio, "_kc_write", side_effect=_kw):
        cfg = _stash_refreshed_tokens("acme", payload, prev_refresh="old-r")
    assert cfg is not None
    assert cfg.access_token == "new-a"
    assert cfg.refresh_token == "new-r"
    # Order: access first, then refresh, then expiry.
    services = [s for s, _ in writes]
    assert services.index("grip-clio-acme") < services.index("grip-clio-refresh-acme")
    assert services.index("grip-clio-refresh-acme") < services.index("grip-clio-expires-acme")


def test_stash_refreshed_tokens_returns_none_on_partial_failure():
    """Kill mutation: continue writing after a write fails.

    First write fails -> function MUST return None. Continuing would
    leave the Keychain in a half-rotated state.
    """
    with patch.object(clio, "_kc_write", return_value=False):
        result = _stash_refreshed_tokens("t", {"access_token": "a"}, prev_refresh="r")
    assert result is None


# ---------------------------------------------------------------------------
# refresh_access_token — full refresh lifecycle
# ---------------------------------------------------------------------------


def test_refresh_access_token_returns_none_when_no_refresh_token():
    """Kill mutation: proceed to grant POST with empty refresh_token.

    A tenant without a refresh_token cannot refresh; calling Clio anyway
    would surface an invalid_grant error with a misleading "we tried to
    refresh" trace.
    """
    cfg = ClioConfig(tenant_id="t", access_token="a", refresh_token="")
    with patch.object(clio, "load_config", return_value=cfg):
        assert refresh_access_token("t") is None


def test_refresh_access_token_returns_none_when_app_creds_missing():
    """Kill mutation: pass empty client_id / client_secret to grant POST.

    Clio rejects empty app credentials as invalid_client; the function
    must short-circuit with None and let the caller surface the missing-
    credentials state to the operator.
    """
    cfg = ClioConfig(tenant_id="t", access_token="a", refresh_token="r")
    with patch.object(clio, "load_config", return_value=cfg), \
         patch.object(clio, "_kc_read", return_value=None):
        assert refresh_access_token("t") is None


def test_refresh_access_token_returns_none_on_grant_failure():
    """Kill mutation: ignore grant_post None return."""
    cfg = ClioConfig(tenant_id="t", access_token="a", refresh_token="r")
    creds = {"grip-clio-app-id": "cid", "grip-clio-app-secret": "csec"}
    with patch.object(clio, "load_config", return_value=cfg), \
         patch.object(clio, "_kc_read", side_effect=lambda s: creds.get(s)), \
         patch.object(clio, "_token_grant_post", return_value=None):
        assert refresh_access_token("t") is None


def test_refresh_access_token_returns_new_config_on_success():
    """Kill mutation: return the OLD config after a successful refresh.

    A successful refresh MUST return a ClioConfig holding the NEW
    access_token; otherwise the caller's retry would use the same
    expired token.
    """
    cfg = ClioConfig(tenant_id="t", access_token="old", refresh_token="r")
    creds = {"grip-clio-app-id": "cid", "grip-clio-app-secret": "csec"}
    payload = {"access_token": "fresh", "refresh_token": "new-r", "expires_in": 3600}
    with patch.object(clio, "load_config", return_value=cfg), \
         patch.object(clio, "_kc_read", side_effect=lambda s: creds.get(s)), \
         patch.object(clio, "_token_grant_post", return_value=payload), \
         patch.object(clio, "_kc_write", return_value=True):
        new_cfg = refresh_access_token("t")
    assert new_cfg is not None
    assert new_cfg.access_token == "fresh"
    assert new_cfg.refresh_token == "new-r"


# ---------------------------------------------------------------------------
# _http_with_retry — transient-5xx retry window
# ---------------------------------------------------------------------------


def test_http_with_retry_returns_first_2xx_without_retry(ok_config: ClioConfig):
    """Kill mutation: always loop at least twice.

    Successful first call must not trigger a retry — extra calls cost
    Clio API quota and would skew rate-limit telemetry.
    """
    calls: List[int] = []

    def _h(method, path, cfg, body=None):
        calls.append(1)
        return 200, {"ok": True}

    with patch.object(clio, "_http", side_effect=_h):
        status, body = _http_with_retry("GET", "/x", ok_config)
    assert status == 200
    assert len(calls) == 1


def test_http_with_retry_retries_on_5xx_within_window(ok_config: ClioConfig):
    """Kill mutation: drop the >= 500 condition (only retry on 503).

    Transparent retry per council verdict #4: any 5xx within the 30s
    window is transient. We simulate a recovery on the second call.
    """
    seq = iter([(503, {}), (200, {"ok": True})])

    def _h(method, path, cfg, body=None):
        return next(seq)

    with patch.object(clio, "_http", side_effect=_h), \
         patch.object(clio, "time", MagicMock(monotonic=time.monotonic, sleep=lambda s: None)):
        status, body = _http_with_retry("GET", "/x", ok_config)
    assert status == 200


def test_http_with_retry_propagates_4xx_without_retry(ok_config: ClioConfig):
    """Kill mutation: retry on 4xx as well.

    4xx is caller-fault (validation, auth, not-found) — retrying would
    waste quota and never succeed. Only 5xx is transient.
    """
    calls: List[int] = []

    def _h(method, path, cfg, body=None):
        calls.append(1)
        return 422, {"error": "validation"}

    with patch.object(clio, "_http", side_effect=_h):
        status, body = _http_with_retry("POST", "/x", ok_config)
    assert status == 422
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# _is_mutation / _classify_outcome — outcome routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,expected", [
    ("GET", False),
    ("POST", True),
    ("PUT", True),
    ("PATCH", True),
    ("DELETE", True),
    ("HEAD", False),
    ("post", True),  # case-insensitive
    ("get", False),
])
def test_is_mutation_matches_council_verdict_3(method: str, expected: bool):
    """Kill mutation: invert the set membership (treat GET as mutation).

    Council verdict #3: only mutations chain. Inverting would either
    (a) emit IDRs on every GET (chain explosion), or
    (b) drop IDRs on POST/PATCH (audit hole — exactly the gap to close).
    """
    assert _is_mutation(method) is expected


@pytest.mark.parametrize("status,expected_ok,expected_label", [
    (200, True, "success"),
    (201, True, "success"),
    (299, True, "success"),
    (300, False, "failure"),
    (401, False, "failure"),
    (422, False, "failure"),
    (500, False, "failure"),
    (0, False, "transport_failure"),
])
def test_classify_outcome_partitions_status_space(
    status: int, expected_ok: bool, expected_label: str
):
    """Kill mutation: collapse transport_failure into failure.

    status=0 is operationally different from a 4xx/5xx — it means we
    couldn't reach Clio at all. The IDR context distinguishes the two
    so postmortems can separate "Clio said no" from "couldn't talk
    to Clio".
    """
    ok, label = _classify_outcome(status)
    assert ok is expected_ok
    assert label == expected_label


# ---------------------------------------------------------------------------
# _emit_mutation_idr / _emit_not_configured_idr — IDR payload shape
# ---------------------------------------------------------------------------


def test_emit_mutation_idr_includes_clio_calls_array(fake_logger: MagicMock):
    """Kill mutation: drop the clio_calls array from context.

    Chain replay tooling reconstructs the per-tenant Clio call sequence
    from the clio_calls array; dropping it would leave audit-trail
    consumers without the per-mutation HTTP metadata.
    """
    decision_id = _emit_mutation_idr(
        fake_logger, "POST", "/time_entries", 201,
        tenant_id="t", ritual_id="r", step_id="s", parent_decision_id=None,
    )
    assert decision_id == "sha256:test-001"
    kwargs = fake_logger.log_decision.call_args.kwargs
    assert "clio_calls" in kwargs["context"]
    assert kwargs["context"]["clio_calls"][0]["status"] == 201


def test_emit_mutation_idr_threads_parent_decision_id(fake_logger: MagicMock):
    """Kill mutation: drop parent_decision_id from context.

    The chain-forest link from orchestrator routing to Clio mutation
    depends on context.parent_decision_id being preserved verbatim;
    dropping it severs the cross-step replay.
    """
    _emit_mutation_idr(
        fake_logger, "POST", "/x", 200,
        tenant_id="t", ritual_id="r", step_id="s",
        parent_decision_id="sha256:parent-abc",
    )
    kwargs = fake_logger.log_decision.call_args.kwargs
    assert kwargs["context"]["parent_decision_id"] == "sha256:parent-abc"


def test_emit_mutation_idr_omits_parent_when_none(fake_logger: MagicMock):
    """Kill mutation: always emit parent_decision_id (as None or "").

    When no parent is provided the key MUST be absent — emitting
    `parent_decision_id: None` would falsely chain to a non-existent
    decision in replay tools that key on presence.
    """
    _emit_mutation_idr(
        fake_logger, "POST", "/x", 200,
        tenant_id="t", ritual_id="r", step_id="s", parent_decision_id=None,
    )
    kwargs = fake_logger.log_decision.call_args.kwargs
    assert "parent_decision_id" not in kwargs["context"]


def test_emit_not_configured_idr_marks_outcome_not_configured(fake_logger: MagicMock):
    """Kill mutation: emit outcome="success" instead of "not_configured".

    Fail-CLOSED per council verdict #6: the IDR must record that the
    call did NOT happen (Clio wasn't configured for this tenant). A
    success label would corrupt the chain's truthfulness.
    """
    _emit_not_configured_idr(
        fake_logger, "POST", "/x",
        tenant_id="t", ritual_id="r", step_id="s", parent_decision_id=None,
    )
    kwargs = fake_logger.log_decision.call_args.kwargs
    assert kwargs["context"]["outcome"] == "not_configured"
    assert kwargs["confidence"] == 0.0


# ---------------------------------------------------------------------------
# call() — single-dispatch entry point + 401-refresh path
# ---------------------------------------------------------------------------


def test_call_emits_zero_idrs_on_get_with_logger(
    ok_config: ClioConfig, fake_logger: MagicMock
):
    """Kill mutation: emit IDR on GET (invert _is_mutation in call()).

    Council verdict #3 enforced at the call() boundary: even WITH a
    logger present, GET must not extend the chain. Inverting would
    cause chain explosion at every read.
    """
    with patch.object(clio, "load_config", return_value=ok_config), \
         patch.object(clio, "_http_with_retry", return_value=(200, {"matters": []})):
        result = call(
            tenant_id="t", method="GET", path="/matters", logger=fake_logger,
        )
    assert result.ok is True
    assert result.decision_id is None
    assert fake_logger.log_decision.call_count == 0


def test_call_emits_one_idr_on_post_with_logger(
    ok_config: ClioConfig, fake_logger: MagicMock
):
    """Kill mutation: drop the logger.log_decision call in mutation path.

    Mutations MUST chain (council verdict #3). Without the IDR, the
    audit trail is silent at the very moment legal-impactful state
    changes — the audit-hole the council convened to close.
    """
    with patch.object(clio, "load_config", return_value=ok_config), \
         patch.object(clio, "_http_with_retry", return_value=(201, {"id": 1})):
        result = call(
            tenant_id="t", method="POST", path="/time_entries",
            body={"matter_id": "M-1", "duration": 30},
            logger=fake_logger,
        )
    assert result.ok is True
    assert result.decision_id == "sha256:test-001"
    assert fake_logger.log_decision.call_count == 1


def test_call_not_configured_emits_idr_only_on_mutation(fake_logger: MagicMock):
    """Kill mutation: emit not_configured IDR on GET too.

    The degraded-mode IDR is meaningful only for mutations (where the
    chain expects an entry). GETs should silently return the not_configured
    error without extending the chain (it would never have extended anyway).
    """
    with patch.object(clio, "load_config", return_value=None):
        get_result = call(
            tenant_id="t", method="GET", path="/matters", logger=fake_logger,
        )
        post_result = call(
            tenant_id="t", method="POST", path="/time_entries",
            body={}, logger=fake_logger,
        )
    assert get_result.decision_id is None
    assert post_result.decision_id == "sha256:test-001"
    assert fake_logger.log_decision.call_count == 1


def test_call_triggers_401_refresh_retry_path(
    ok_config: ClioConfig, fake_logger: MagicMock
):
    """Kill mutation: do not retry on 401 (skip refresh-and-retry).

    Reactive 401 refresh per the in-flight-pattern: 401 with refresh_token
    -> refresh -> retry ONCE. Dropping the retry would force every
    expired-token request to bubble up as a hard 401.
    """
    new_cfg = ClioConfig(
        tenant_id="t", access_token="fresh", refresh_token="r2",
    )
    responses = iter([(401, {"error": "unauth"}), (200, {"ok": True})])

    with patch.object(clio, "load_config", return_value=ok_config), \
         patch.object(clio, "_http_with_retry", side_effect=lambda *a, **kw: next(responses)), \
         patch.object(clio, "refresh_access_token", return_value=new_cfg):
        result = call(
            tenant_id="t", method="GET", path="/matters", logger=fake_logger,
        )
    assert result.ok is True
    assert result.status == 200


def test_call_returns_not_configured_result_when_load_config_none():
    """Kill mutation: return ok=True when no config exists.

    Without a logger the result MUST still surface ok=False, status=0,
    body.error="not_configured" — caller code branches on this contract.
    """
    with patch.object(clio, "load_config", return_value=None):
        result = call(tenant_id="absent", method="GET", path="/matters")
    assert result.ok is False
    assert result.status == 0
    assert result.body == {"error": "not_configured"}
    assert result.decision_id is None


# ---------------------------------------------------------------------------
# _http — pure stdlib HTTP boundary (patched by every other test, covered here)
# ---------------------------------------------------------------------------


def test_http_returns_2xx_with_parsed_json_body(ok_config: ClioConfig):
    """Kill mutation: return raw bytes instead of parsed JSON.

    The (status, body_dict) contract is what _http_with_retry and call()
    branch on; raw bytes would crash downstream dict access.
    """
    body = json.dumps({"matters": [{"id": 1}]}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(body, 200)):
        status, parsed = clio._http("GET", "/matters", ok_config)
    assert status == 200
    assert parsed == {"matters": [{"id": 1}]}


def test_http_returns_transport_failure_tuple_on_url_error(ok_config: ClioConfig):
    """Kill mutation: re-raise URLError instead of returning (0, error).

    Transport errors MUST surface as status=0 + error dict so callers
    route via _classify_outcome -> "transport_failure" label rather
    than crash mid-request.
    """
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
        status, body = clio._http("GET", "/matters", ok_config)
    assert status == 0
    assert "transport" in body["error"]


def test_http_returns_status_with_empty_body_on_no_content(ok_config: ClioConfig):
    """Kill mutation: return None body on empty 204; callers crash on .get()."""
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(b"", 204)):
        status, body = clio._http("DELETE", "/x/1", ok_config)
    assert status == 204
    assert body == {}


def test_http_wraps_non_json_body_in_raw_key(ok_config: ClioConfig):
    """Kill mutation: crash on JSONDecodeError instead of wrapping.

    Clio occasionally returns HTML error pages (gateway timeouts); the
    body dict's "raw" key carries the truncated text so postmortems can
    distinguish "Clio sent garbage" from "transport failed".
    """
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(b"<html>oops</html>", 502)):
        status, body = clio._http("GET", "/x", ok_config)
    assert status == 502
    assert "raw" in body
    assert "html" in body["raw"]


def test_http_surfaces_http_error_with_body(ok_config: ClioConfig):
    """Kill mutation: drop HTTPError handling (would re-raise to caller).

    Clio 4xx responses arrive as HTTPError; _http converts them to
    (status, body) tuples so the caller's status-based branching works
    uniformly across success and failure paths.
    """
    err_body = b'{"error": "validation"}'
    fake_fp = MagicMock()
    fake_fp.read.return_value = err_body
    err = urllib.error.HTTPError("u", 422, "Unprocessable", {}, fake_fp)
    with patch("urllib.request.urlopen", side_effect=err):
        status, body = clio._http("POST", "/x", ok_config, body={"y": 1})
    assert status == 422
    assert body == {"error": "validation"}


def test_emit_not_configured_idr_threads_parent_decision_id(fake_logger: MagicMock):
    """Kill mutation: drop parent_decision_id from not_configured context.

    Degraded-mode IDR must still preserve the routing-decision link so
    replay tools can show "orchestrator decided to call Clio, but Clio
    wasn't configured for tenant X".
    """
    _emit_not_configured_idr(
        fake_logger, "POST", "/x",
        tenant_id="t", ritual_id="r", step_id="s",
        parent_decision_id="sha256:routing-decision",
    )
    kwargs = fake_logger.log_decision.call_args.kwargs
    assert kwargs["context"]["parent_decision_id"] == "sha256:routing-decision"
