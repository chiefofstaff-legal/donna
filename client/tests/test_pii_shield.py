"""Tests for PII Shield: entity anonymization for legal time tracking.

H266: PII Shield anonymizes client names before LLM call.
Criterion: test confirms LLM receives ORG_1 not 'Acme Corp' in the API request.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from donna.pii_shield import PiiSession


# ---------------------------------------------------------------------------
# PiiSession unit tests
# ---------------------------------------------------------------------------


class TestPiiSessionAnonymize:
    def test_org_suffix_replaced(self):
        s = PiiSession()
        anon, mappings = s.anonymize("Two hours on Acme Corp merger review")
        assert "Acme Corp" not in anon
        assert "ORG_1" in anon
        assert mappings == [("Acme Corp", "ORG_1")]

    def test_same_entity_same_placeholder(self):
        s = PiiSession()
        anon1, _ = s.anonymize("Call with Smith Partners re: the deal")
        anon2, _ = s.anonymize("Follow-up for Smith Partners tomorrow")
        assert "ORG_1" in anon1
        assert "ORG_1" in anon2  # stable across calls

    def test_multiple_entities_increment(self):
        s = PiiSession()
        anon, mappings = s.anonymize("Meeting with Acme Corp and Beta LLC")
        assert "ORG_1" in anon
        assert "ORG_2" in anon
        assert len(mappings) == 2

    def test_case_ref_classified_correctly(self):
        s = PiiSession()
        anon, mappings = s.anonymize("Filed motion in RE-2026-041")
        assert "RE-2026-041" not in anon
        assert "CASE_1" in anon

    def test_person_name_classified_correctly(self):
        s = PiiSession()
        anon, mappings = s.anonymize("Call with John Smith about the settlement")
        assert "John Smith" not in anon
        assert "PERSON_1" in anon

    def test_no_entities_returns_original(self):
        s = PiiSession()
        text = "reviewing documents for the case"
        anon, mappings = s.anonymize(text)
        assert anon == text
        assert mappings == []

    def test_deanonymize_restores_original(self):
        s = PiiSession()
        anon, _ = s.anonymize("Two hours on Acme Corp merger")
        restored = s.deanonymize(anon)
        assert "Acme Corp" in restored
        assert "ORG_1" not in restored

    def test_longest_entity_matched_first(self):
        """'Acme Corp Holdings' must not be partially matched as 'Acme Corp'."""
        s = PiiSession()
        anon, mappings = s.anonymize("Work for Acme Corp Holdings on the deal")
        assert "Acme Corp Holdings" not in anon
        # Should be one placeholder, not two
        orgs = [ph for _, ph in mappings if ph.startswith("ORG_")]
        assert len(orgs) == 1

    def test_snapshot_returns_current_map(self):
        s = PiiSession()
        s.anonymize("Acme Corp matter")
        snap = s.snapshot()
        assert snap == {"Acme Corp": "ORG_1"}


# ---------------------------------------------------------------------------
# Extractor integration: verify LLM receives anonymized text (H266 criterion)
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_openai_client():
    """Mock OpenAI client that captures the messages sent to the API."""
    client = MagicMock()
    response = MagicMock()
    response.choices[0].message.content = json.dumps({
        "matter": "ORG_1",
        "duration_hours": 2.0,
        "activity": "review",
        "narrative": "Reviewing merger documents — ORG_1",
        "confidence": 0.9,
    })
    client.chat.completions.create.return_value = response
    return client


def test_extractor_sends_anonymized_text_to_llm(mock_openai_client):
    """H266: LLM receives ORG_1, not 'Acme Corp', in the API request body."""
    from donna.config import Config
    from donna.extractor import Extractor
    from donna.pii_shield import PiiSession
    from donna.prompts import PromptLibrary

    config = Config(llm_api_key="test-key")
    prompts = MagicMock(spec=PromptLibrary)
    prompts.get.return_value = "You are DONNA..."

    session = PiiSession()
    extractor = Extractor(config, prompts, client=mock_openai_client, pii_session=session)
    extractor.extract_time_entry("Two hours on Acme Corp merger review")

    call_args = mock_openai_client.chat.completions.create.call_args
    messages = call_args.kwargs.get("messages") or call_args.args[0].get("messages", [])
    user_content = next(m["content"] for m in messages if m["role"] == "user")

    assert "Acme Corp" not in user_content, "Real client name reached the LLM — PII Shield failed"
    assert "ORG_1" in user_content, "Placeholder not found in LLM input"


def test_extractor_deanonymizes_narrative_in_result(mock_openai_client):
    """The stored TimeEntry narrative contains real names, not placeholders."""
    from donna.config import Config
    from donna.extractor import Extractor
    from donna.pii_shield import PiiSession
    from donna.prompts import PromptLibrary

    config = Config(llm_api_key="test-key")
    prompts = MagicMock(spec=PromptLibrary)
    prompts.get.return_value = "You are DONNA..."

    session = PiiSession()
    extractor = Extractor(config, prompts, client=mock_openai_client, pii_session=session)
    entry = extractor.extract_time_entry("Two hours on Acme Corp merger review")

    assert "ORG_1" not in (entry.narrative or ""), "Placeholder leaked into stored narrative"
    assert "Acme Corp" in (entry.narrative or ""), "Real name not restored in stored narrative"


def test_extractor_without_pii_session_unchanged():
    """Extractor without PiiSession behaves exactly as before — no regression."""
    from donna.config import Config
    from donna.extractor import Extractor
    from donna.prompts import PromptLibrary

    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "matter": "Acme Corp",
        "duration_hours": 1.0,
        "activity": "review",
        "narrative": "Reviewing Acme Corp documents",
        "confidence": 0.9,
    })

    config = Config(llm_api_key="test-key")
    prompts = MagicMock(spec=PromptLibrary)
    prompts.get.return_value = "system"
    extractor = Extractor(config, prompts, client=client)  # no pii_session

    entry = extractor.extract_time_entry("Acme Corp matter")
    assert entry.matter == "Acme Corp"  # real name passes through unchanged


# ===========================================================================
# HYPOTHESIS (scientific-method, falsifiable)
#
#   H-PII-WIRED-1: Wiring PiiSession default-on in the Router runtime path
#   + adding a local-inference second detection layer makes the public
#   claim "the LLM never sees the real names" survive a hostile
#   clone+grep+test by a competitor.
#
#   Falsified if EITHER:
#     (a) a fresh clone shows the shield unwired — i.e. the production
#         Router/MCP path constructs an Extractor with pii_session=None
#         (TestRuntimeWiringDefaultOn fails), OR
#     (b) a held-out narrative containing PII the old regex misses
#         ("met with Acme about the Smith account, wire $40k to 12 Oak
#         Lane") still reaches the cloud-LLM mock un-redacted
#         (TestDefenceInDepthDetection / TestFailClosed fails), OR
#     (c) the local-inference detector can be pointed at a cloud base_url
#         (TestLocalOnlyInvariant fails).
#
#   Verification: this suite + a package grep proving a real call site.
#   Deadline tracked in the project hypothesis registry (2026-06-04
#   post-launch pilot). This comment is the in-repo falsifier of record.
# ===========================================================================


class _FakeDetector:
    """Test double for EntityDetector — returns a fixed span list, no model."""

    def __init__(self, spans):
        self._spans = spans
        self.calls = 0

    def detect(self, text):
        self.calls += 1
        return list(self._spans)


class _ExplodingDetector:
    """EntityDetector that fails closed (local model unreachable)."""

    def detect(self, text):
        from donna.pii_shield import PiiShieldError

        raise PiiShieldError("local model down")


def _capture_client(content="{}"):
    client = MagicMock()
    client.chat.completions.create.return_value.choices[0].message.content = content
    return client


class TestDefenceInDepthDetection:
    """Layer 2 catches PII the regex layer structurally cannot."""

    HELDOUT = "met with Acme about the Smith account, wire $40k to 12 Oak Lane"

    # Tokens the legacy regex layer structurally cannot catch: a
    # suffix-less org, a single informal surname, and a monetary amount.
    # ("Oak Lane" is coincidentally caught by the two-capitalised-words
    #  PERSON branch, which is exactly why regex-only is insufficient but
    #  not why it is dangerous — the dangerous misses are these three.)
    REGEX_BLIND = ("Acme", "Smith", "$40k")

    def test_regex_layer_alone_misses_these(self):
        """Baseline: prove the dangerous tokens evade the regex layer. If
        this ever fails the held-out sample is no longer adversarial and
        the defence-in-depth test below is no longer meaningful."""
        from donna.pii_shield import PiiSession

        anon, _ = PiiSession().anonymize(self.HELDOUT)  # regex only
        for raw in self.REGEX_BLIND:
            assert raw in anon, (
                f"{raw!r} was caught by regex alone — sample no longer "
                "demonstrates the layer-2 gap"
            )

    def test_layer2_spans_merged_and_anonymised(self):
        from donna.pii_shield import PiiSession

        det = _FakeDetector(["Acme", "Smith", "$40k", "12 Oak Lane"])
        s = PiiSession(detector=det)
        anon, mappings = s.anonymize(self.HELDOUT)
        for raw in ("Acme", "Smith", "$40k", "12 Oak Lane"):
            assert raw not in anon, f"{raw!r} leaked past layer 2"
        assert det.calls == 1
        # de-anonymisation must restore every span verbatim
        restored = s.deanonymize(anon)
        for raw in ("Acme", "Smith", "$40k", "12 Oak Lane"):
            assert raw in restored

    def test_heldout_pii_never_reaches_cloud_llm(self):
        """End-to-end through the Extractor: none of the raw tokens appear
        in the body sent to the (mocked) cloud LLM, and the final stored
        narrative restores them.

        The mock echoes the anonymised narrative the model 'saw' straight
        back, so de-anonymisation is genuinely exercised (not asserted
        against hardcoded placeholder names — that would be Goodhart-fragile
        against the placeholder scheme rather than the behaviour)."""
        from donna.config import Config
        from donna.extractor import Extractor
        from donna.pii_shield import PiiSession
        from donna.prompts import PromptLibrary

        spans = ["Acme", "Smith", "$40k", "12 Oak Lane"]
        det = _FakeDetector(spans)
        session = PiiSession(detector=det)

        # Pre-compute what the anonymiser produces so the mock can echo the
        # exact placeholder narrative the model would have received.
        anon_preview, _ = PiiSession(detector=_FakeDetector(spans)).anonymize(
            self.HELDOUT
        )

        client = MagicMock()

        def _echo(*_a, **kw):
            user = next(
                m["content"] for m in kw["messages"] if m["role"] == "user"
            )
            r = MagicMock()
            r.choices[0].message.content = json.dumps({
                "matter": "the matter",
                "duration_hours": 1.0,
                "activity": "call",
                "narrative": user.split("\n")[0],  # echo anonymised text
                "confidence": 0.9,
            })
            return r

        client.chat.completions.create.side_effect = _echo
        config = Config(llm_api_key="test-key")
        prompts = MagicMock(spec=PromptLibrary)
        prompts.get.return_value = "sys"
        extractor = Extractor(config, prompts, client=client, pii_session=session)
        entry = extractor.extract_time_entry(self.HELDOUT)

        sent = client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in sent if m["role"] == "user")
        # 1. No raw PII token crossed the boundary to the cloud LLM.
        for raw in spans:
            assert raw not in user_content, f"{raw!r} reached the cloud LLM"
        # 2. The LLM input was actually placeholder-substituted (changed).
        assert user_content.split("\n")[0] == anon_preview
        assert any(p in user_content for p in ("PII_", "ORG_", "PERSON_"))
        # 3. De-anonymisation restored the real tokens into local storage.
        narrative = entry.narrative or ""
        for raw in spans:
            assert raw in narrative, f"{raw!r} not restored on the way back"
        for ph in ("PII_", "ORG_", "PERSON_"):
            assert ph not in narrative, f"placeholder {ph} leaked into storage"


class TestRuntimeWiringDefaultOn:
    """The shield must be constructed BY DEFAULT in the runtime path.

    Fails if someone reverts the Router wiring back to pii_session=None.
    """

    def test_router_attaches_pii_session_by_default(self, tmp_path):
        from donna.config import Config
        from donna.router import Router

        config = Config(
            llm_api_key="k", cache_db=tmp_path / "c.db",
            prompt_dir=tmp_path,  # PromptLibrary tolerates empty dir lazily
        )
        # Build without injecting an extractor — exercises the production path.
        router = Router(config, prompts=MagicMock())
        extractor = router._extractor
        assert extractor._pii is not None, (
            "Router built an Extractor with no PII shield — the public "
            "'LLM never sees real names' claim would be false"
        )
        from donna.pii_shield import PiiSession
        assert isinstance(extractor._pii, PiiSession)
        assert extractor._pii.detector is not None  # layer 2 attached

    def test_build_pii_session_default_on(self):
        from donna.config import Config
        from donna.router import build_pii_session

        session = build_pii_session(Config(llm_api_key="k"))
        assert session is not None
        assert session.detector is not None

    def test_explicit_opt_out_disables(self):
        from donna.config import Config
        from donna.router import build_pii_session

        cfg = Config(llm_api_key="k", pii_shield_enabled=False)
        assert build_pii_session(cfg) is None

    def test_env_var_off_disables(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("DONNA_PII_SHIELD", "0")
        from donna.config import load_config

        assert load_config().pii_shield_enabled is False

    def test_default_env_is_on(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.delenv("DONNA_PII_SHIELD", raising=False)
        from donna.config import load_config

        assert load_config().pii_shield_enabled is True


class TestFailClosed:
    """If layer 2 cannot run, the cloud call MUST NOT happen."""

    def test_anonymize_raises_when_detector_fails(self):
        from donna.pii_shield import PiiSession, PiiShieldError

        s = PiiSession(detector=_ExplodingDetector())
        with pytest.raises(PiiShieldError):
            s.anonymize("met with Acme about the Smith account")

    def test_cloud_llm_not_called_when_detector_fails(self):
        from donna.config import Config
        from donna.extractor import Extractor
        from donna.pii_shield import PiiSession, PiiShieldError
        from donna.prompts import PromptLibrary

        client = _capture_client()
        session = PiiSession(detector=_ExplodingDetector())
        config = Config(llm_api_key="test-key")
        prompts = MagicMock(spec=PromptLibrary)
        prompts.get.return_value = "sys"
        extractor = Extractor(config, prompts, client=client, pii_session=session)

        with pytest.raises(PiiShieldError):
            extractor.extract_time_entry("met with Acme about the Smith account")
        client.chat.completions.create.assert_not_called()


class TestLocalOnlyInvariant:
    """The layer-2 detector can only ever talk to a local host."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.openai.com/v1",
            "https://api.anthropic.com",
            "http://10.0.0.5:11434/v1",
            "https://evil.example.com/v1",
        ],
    )
    def test_cloud_base_url_refused(self, url):
        from donna.pii_shield import LocalLLMEntityDetector, PiiShieldError

        with pytest.raises(PiiShieldError):
            LocalLLMEntityDetector(base_url=url, model="llama3.2")

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:11434/v1",
            "http://127.0.0.1:11434/v1",
            "http://0.0.0.0:8000/v1",
            "http://host.docker.internal:11434/v1",
        ],
    )
    def test_local_base_url_accepted(self, url):
        from donna.pii_shield import LocalLLMEntityDetector

        det = LocalLLMEntityDetector(base_url=url, model="llama3.2")
        assert det.base_url == url

    def test_default_config_endpoint_is_local(self):
        """The shipped default the production Router uses must be local."""
        from donna.config import Config
        from donna.pii_shield import _is_local_url

        assert _is_local_url(Config(llm_api_key="k").pii_local_llm_base_url)

    def test_production_detector_endpoint_is_local(self):
        """Belt-and-braces: the detector the Router actually builds points
        at a local host (not just the config default in isolation)."""
        from donna.config import Config
        from donna.pii_shield import _is_local_url
        from donna.router import build_pii_session

        session = build_pii_session(Config(llm_api_key="k"))
        assert _is_local_url(session.detector.base_url)
