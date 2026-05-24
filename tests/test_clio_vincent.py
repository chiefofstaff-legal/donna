"""Tests for client/donna/integrations/clio_vincent.py — Vincent IDR wrapping.

Goodhart-anchored per Rule 14: each test names the one-line mutation it
catches. The IDR shape is mutation-resistant — renaming `intent`, dropping
`matter_id`, mis-mapping `outcome`, or breaking `predecessor` chaining
all fail their corresponding test.

Per Council R2 (2026-05-24): `model=` parameter is dropped; no test
references it. Per Council R8: explicit mutation pattern coverage for
IDR intent / outcome / predecessor.

Hypothesis anchor: H-CLIO-3 — "exactly one IDR per vincent_call with
intent=vincent_invocation and predecessor_idr correctly chained" over
30 days post-merge.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from donna.integrations import clio_vincent
from donna.integrations.clio import ClioConfig, ClioResult


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
        decision_id = f"sha256:vincent{self._next_id:04d}"
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


def _ok_config() -> ClioConfig:
    return ClioConfig(
        tenant_id="acme",
        access_token="stub-access",
        refresh_token="stub-refresh",
        expires_at=0.0,
    )


@pytest.fixture
def logger() -> _StubLogger:
    return _StubLogger()


# ---------------------------------------------------------------------------
# 1. Endpoint dispatch
# ---------------------------------------------------------------------------


def test_vincent_call_dispatches_to_default_path():
    """Mutation: change _VINCENT_PATH_DEFAULT — would 404 against Clio."""
    calls: List[Dict[str, Any]] = []

    def _capture(method, path, cfg, body):
        calls.append({"method": method, "path": path, "body": body})
        return 200, {"suggestion": "track 2 hours"}

    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", side_effect=_capture):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="summarise this matter",
        )

    assert calls[0]["path"] == "/vincent/invocations"
    assert calls[0]["method"] == "POST"


def test_vincent_call_dispatches_post_method():
    """Mutation: GET — wouldn't reach AI endpoint correctly."""
    captured: Dict[str, Any] = {}

    def _capture(method, path, cfg, body):
        captured["method"] = method
        return 200, {}

    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", side_effect=_capture):
        clio_vincent.vincent_call("acme", matter_id="M-1", prompt="p")

    assert captured["method"] == "POST"


def test_vincent_call_env_override_path():
    """Mutation: ignore $CLIO_VINCENT_PATH — would break sandbox/dev env."""
    captured: Dict[str, Any] = {}

    def _capture(method, path, cfg, body):
        captured["path"] = path
        return 200, {}

    with patch.dict(os.environ, {"CLIO_VINCENT_PATH": "/matters/M-1/vincent/invocations"}), \
         patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", side_effect=_capture):
        clio_vincent.vincent_call("acme", matter_id="M-1", prompt="p")

    assert captured["path"] == "/matters/M-1/vincent/invocations"


def test_vincent_request_body_includes_matter_and_prompt():
    """Mutation: drop matter_id or prompt from body — Clio would 422."""
    captured: Dict[str, Any] = {}

    def _capture(method, path, cfg, body):
        captured["body"] = body
        return 200, {}

    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", side_effect=_capture):
        clio_vincent.vincent_call("acme", matter_id="M-42", prompt="cite key facts")

    assert captured["body"] == {"matter_id": "M-42", "prompt": "cite key facts"}


# ---------------------------------------------------------------------------
# 2. IDR emission — count and shape
# ---------------------------------------------------------------------------


def test_vincent_emits_exactly_one_idr_on_success(logger):
    """Mutation: emit zero (drop logger) or two (double-call) — chain corruption."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {"r": 1})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert len(logger.calls) == 1


def test_vincent_idr_intent_field_is_vincent_invocation(logger):
    """Mutation: rename intent — replay tools filter on this exact string."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["intent"] == "vincent_invocation"
    assert clio_vincent.VINCENT_INTENT == "vincent_invocation"


def test_vincent_idr_matter_id_binding(logger):
    """Mutation: drop matter_id from IDR context — chain forensics break."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-99", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["matter_id"] == "M-99"


def test_vincent_idr_tenant_id_binding(logger):
    """Mutation: hardcode tenant_id — privacy break across tenants."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["tenant_id"] == "acme"


# ---------------------------------------------------------------------------
# 3. SHA hashing (PII-safe)
# ---------------------------------------------------------------------------


def test_vincent_idr_prompt_sha256(logger):
    """Mutation: store raw prompt — leaks privileged content to chain."""
    prompt = "Confidential: client SSN is 123-45-6789"
    expected = "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt=prompt, logger=logger,
        )

    ctx = logger.calls[0]["context"]
    assert ctx["prompt_sha256"] == expected
    # Raw prompt MUST NOT appear anywhere in the IDR context.
    assert prompt not in json.dumps(ctx)


def test_vincent_idr_response_sha256(logger):
    """Mutation: skip response hashing — no proof of response provenance."""
    response = {"suggestion": "track 2.5 hours under matter M-1"}
    expected = "sha256:" + hashlib.sha256(
        json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, response)):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["response_sha256"] == expected


def test_vincent_idr_uses_sha256_not_md5_or_sha1(logger):
    """Mutation: weaken hash algorithm — chain integrity downgraded."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    ctx = logger.calls[0]["context"]
    assert ctx["prompt_sha256"].startswith("sha256:")
    assert ctx["response_sha256"].startswith("sha256:")
    # SHA-256 hex = 64 chars; sha1 = 40, md5 = 32 — length anchor.
    assert len(ctx["prompt_sha256"]) == len("sha256:") + 64
    assert len(ctx["response_sha256"]) == len("sha256:") + 64


def test_vincent_idr_does_not_include_model_field(logger):
    """Council R2: model parameter dropped; IDR must not carry a model field."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert "model" not in logger.calls[0]["context"]


# ---------------------------------------------------------------------------
# 4. Predecessor chaining (chain forest)
# ---------------------------------------------------------------------------


def test_vincent_idr_chains_to_predecessor(logger):
    """Mutation: drop parent_decision_id from context — chain forest breaks."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
            parent_decision_id="sha256:routing0001",
        )

    assert logger.calls[0]["context"]["parent_decision_id"] == "sha256:routing0001"


def test_vincent_idr_omits_predecessor_when_none(logger):
    """Mutation: always include parent_decision_id (even when None) — IDR shape drift."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert "parent_decision_id" not in logger.calls[0]["context"]


# ---------------------------------------------------------------------------
# 5. Outcome classification (mirrors clio.py _classify_outcome)
# ---------------------------------------------------------------------------


def test_vincent_success_outcome_2xx(logger):
    """Mutation: classify 200 as failure — would lie in chain."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        result = clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["outcome"] == "success"
    assert logger.calls[0]["context"]["status"] == 200
    assert logger.calls[0]["confidence"] == 1.0
    assert result.ok is True


def test_vincent_failure_4xx_still_emits_idr(logger):
    """Mutation: skip IDR on 4xx — exactly the chain hole post-mortems need."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(404, {"error": "matter_not_found"})):
        result = clio_vincent.vincent_call(
            "acme", matter_id="M-deleted", prompt="p", logger=logger,
        )

    assert len(logger.calls) == 1
    assert logger.calls[0]["context"]["outcome"] == "failure"
    assert logger.calls[0]["context"]["status"] == 404
    assert logger.calls[0]["confidence"] == 0.0
    assert result.ok is False


def test_vincent_failure_5xx_still_emits_idr(logger):
    """Mutation: classify 5xx as success — would corrupt chain."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(503, {"error": "unavailable"})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["outcome"] == "failure"
    assert logger.calls[0]["context"]["status"] == 503


def test_vincent_transport_failure_emits_transport_failure_outcome(logger):
    """Mutation: collapse transport_failure → failure — distinct ops modes merged."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(0, {"error": "transport: connection refused"})):
        clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert logger.calls[0]["context"]["outcome"] == "transport_failure"


# ---------------------------------------------------------------------------
# 6. Not-configured path (fail-CLOSED)
# ---------------------------------------------------------------------------


def test_vincent_not_configured_emits_not_configured_idr(logger):
    """Mutation: silent failure when load_config returns None — chain hole."""
    with patch.object(clio_vincent, "load_config", return_value=None):
        result = clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert len(logger.calls) == 1
    assert logger.calls[0]["context"]["outcome"] == "transport_failure"
    assert logger.calls[0]["context"]["status"] == 0
    assert result.ok is False
    assert result.body == {"error": "not_configured"}


def test_vincent_not_configured_without_logger_returns_no_decision_id():
    """Mutation: emit IDR even without logger — substrate must tolerate logger-less calls."""
    with patch.object(clio_vincent, "load_config", return_value=None):
        result = clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p",
        )

    assert result.ok is False
    assert result.decision_id is None


# ---------------------------------------------------------------------------
# 7. Logger optionality
# ---------------------------------------------------------------------------


def test_vincent_logger_optional_no_idr_when_omitted():
    """Mutation: NPE when logger=None — substrate must tolerate logger-less calls."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {"r": 1})):
        result = clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p",
        )

    assert result.ok is True
    assert result.decision_id is None


def test_vincent_call_returns_decision_id_when_logger_present(logger):
    """Mutation: drop decision_id from ClioResult — caller can't chain follow-ons."""
    with patch.object(clio_vincent, "load_config", return_value=_ok_config()), \
         patch.object(clio_vincent, "_http_with_retry", return_value=(200, {})):
        result = clio_vincent.vincent_call(
            "acme", matter_id="M-1", prompt="p", logger=logger,
        )

    assert result.decision_id is not None
    assert result.decision_id == logger.calls[0]["decision_id"]


# ---------------------------------------------------------------------------
# 8. Module-level invariants
# ---------------------------------------------------------------------------


def test_vincent_module_exports_public_surface():
    """Mutation: rename public symbol — would break consumer imports."""
    assert hasattr(clio_vincent, "vincent_call")
    assert hasattr(clio_vincent, "VINCENT_INTENT")
    assert "vincent_call" in clio_vincent.__all__
    assert "VINCENT_INTENT" in clio_vincent.__all__


def test_vincent_module_documents_endpoint_assumption():
    """Mutation: undocumented assumption — operator can't audit the API surface choice."""
    docstring = clio_vincent.__doc__ or ""
    assert "Endpoint assumption" in docstring
    assert "UNVERIFIED" in docstring
    assert "CLIO_VINCENT_PATH" in docstring


def test_vincent_call_signature_has_no_model_param():
    """Council R2: model parameter dropped — verify by signature inspection."""
    import inspect
    sig = inspect.signature(clio_vincent.vincent_call)
    assert "model" not in sig.parameters
