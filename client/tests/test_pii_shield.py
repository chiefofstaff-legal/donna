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
