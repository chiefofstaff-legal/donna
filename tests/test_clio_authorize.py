"""Tests for client/donna/integrations/clio.py — D5 OAuth2 authorize leg.

Covers ``oauth_authorize_url`` and ``build_authorize_redirect``: the
consumer-side initiation half of the authorization_code flow whose token
half is ``grant_oauth_tokens`` (test_clio_grant.py).

Mutation-anchored per Rule 14: exact-string URL assertions kill region or
leaf hardcoding; param-set equality kills dropped or renamed query params;
verbatim state round-trips kill encode/normalise mutations; the keyword-only
signature test kills positional-API drift.

Origin: Track A of the Clio live-OAuth plan, 2026-06-12.
"""

from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import pytest

from donna.integrations import clio


# ---------------------------------------------------------------------------
# 1. oauth_authorize_url — region derivations (mirrors _oauth_token_url trio)
# ---------------------------------------------------------------------------


def test_authorize_url_eu_base() -> None:
    with patch.object(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4"):
        assert clio.oauth_authorize_url() == "https://eu.app.clio.com/oauth/authorize"


def test_authorize_url_us_base() -> None:
    with patch.object(clio, "CLIO_API_BASE", "https://app.clio.com/api/v4"):
        assert clio.oauth_authorize_url() == "https://app.clio.com/oauth/authorize"


def test_authorize_url_non_standard_base_falls_back_to_host() -> None:
    with patch.object(clio, "CLIO_API_BASE", "https://sandbox.clio.com"):
        assert clio.oauth_authorize_url() == "https://sandbox.clio.com/oauth/authorize"


def test_authorize_and_token_urls_share_host() -> None:
    """Kill mutation: leaf helper hardcoding a host for one endpoint only."""
    with patch.object(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4"):
        authorize_host = urlparse(clio.oauth_authorize_url()).netloc
        token_host = urlparse(clio._oauth_token_url()).netloc
    assert authorize_host == token_host == "eu.app.clio.com"


# ---------------------------------------------------------------------------
# 2. build_authorize_redirect — exact URL + param contract
# ---------------------------------------------------------------------------


def test_build_authorize_redirect_exact_url() -> None:
    """Exact full-string equality — the strongest mutation anchor."""
    with patch.object(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4"):
        url = clio.build_authorize_redirect(
            client_id="abc123",
            redirect_uri="https://example.com/api/clio/oauth/callback",
            state="st4te",
        )
    assert url == (
        "https://eu.app.clio.com/oauth/authorize"
        "?response_type=code"
        "&client_id=abc123"
        "&redirect_uri=https%3A%2F%2Fexample.com%2Fapi%2Fclio%2Foauth%2Fcallback"
        "&state=st4te"
    )


def test_build_authorize_redirect_param_set_complete_and_closed() -> None:
    """Param keys are exactly the RFC 6749 §4.1.1 set this flow needs."""
    with patch.object(clio, "CLIO_API_BASE", "https://app.clio.com/api/v4"):
        url = clio.build_authorize_redirect(
            client_id="id-1", redirect_uri="https://cb.example/x", state="s1"
        )
    qs = parse_qs(urlparse(url).query, keep_blank_values=True)
    assert set(qs) == {"response_type", "client_id", "redirect_uri", "state"}
    assert qs["response_type"] == ["code"]
    assert qs["client_id"] == ["id-1"]
    assert qs["redirect_uri"] == ["https://cb.example/x"]


def test_build_authorize_redirect_state_verbatim_roundtrip() -> None:
    """State with URL-hostile chars survives encode→parse unchanged."""
    hostile_state = "a b+c/d=e&f"
    with patch.object(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4"):
        url = clio.build_authorize_redirect(
            client_id="x", redirect_uri="https://cb.example/cb", state=hostile_state
        )
    qs = parse_qs(urlparse(url).query, keep_blank_values=True)
    assert qs["state"] == [hostile_state]


def test_build_authorize_redirect_keyword_only() -> None:
    """The * in the signature is load-bearing API shape — anchor it."""
    with pytest.raises(TypeError):
        clio.build_authorize_redirect(  # type: ignore[misc]
            "id", "https://cb.example/cb", "state"
        )


def test_build_authorize_redirect_is_pure_no_network() -> None:
    """Pure string construction: a network attempt would explode loudly."""

    def _boom(*_a, **_k):  # pragma: no cover - defensive
        raise AssertionError("build_authorize_redirect must not touch the network")

    with patch.object(clio.urllib.request, "urlopen", _boom):
        with patch.object(clio, "CLIO_API_BASE", "https://eu.app.clio.com/api/v4"):
            url = clio.build_authorize_redirect(
                client_id="x", redirect_uri="https://cb.example/cb", state="s"
            )
    assert url.startswith("https://eu.app.clio.com/oauth/authorize?")


# ---------------------------------------------------------------------------
# 3. Export surface
# ---------------------------------------------------------------------------


def test_authorize_leg_is_exported() -> None:
    """Kill the forgot-__all__ mutation: both names are public surface."""
    assert "oauth_authorize_url" in clio.__all__
    assert "build_authorize_redirect" in clio.__all__
