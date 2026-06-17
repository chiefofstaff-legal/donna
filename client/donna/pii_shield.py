"""PII Shield: entity anonymization for legal time tracking.

Inspired by Grigorii Moskalev's PII Shield v2.

Client names, matter references, and person names stay local.
The LLM receives anonymized text; the narrative is de-anonymized before storage.

Session-stable: the same entity maps to the same placeholder across all
LLM calls within one dictation session, preserving cross-utterance context.

All replacement operations are O(n) via single-pass regex substitution —
no nested loops over text regardless of entity count.

Usage:
    session = PiiSession()
    anon, mappings = session.anonymize("Two hours on Acme Corp merger")
    # anon == "Two hours on ORG_1 merger"
    narrative = session.deanonymize("Reviewing ORG_1 merger documents")
    # narrative == "Reviewing Acme Corp merger documents"
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol
from urllib.parse import urlparse

# Single combined pattern: case refs first (most specific), then orgs, then persons.
# Named groups allow classification in one finditer pass — O(n), no nested loops.
_ORG_SUFFIX_ALT = (
    r"Corp|Inc|Ltd|LLC|LLP|LP|PLC|GmbH|AG|NV|SA|Pty|Co|Group|Holdings|"
    r"Partners|Associates|Consulting|Services|Investments|Capital|Law|"
    r"Lawyers|Attorneys|Firm|Foundation|Trust"
)
# Unicode-aware letter classes (donna#51). The original ASCII-only [A-Z]/[a-z]
# silently skipped accented client names — "Müller", "Søderberg", "Łukasz",
# "François" were NOT matched by this fast deterministic layer, so an accented
# name could reach a cloud LLM un-redacted whenever the layer-2 detector was
# absent (the confidentiality failure the shield exists to prevent). These
# classes cover Latin-1 Supplement + Latin Extended-A (European names) while
# preserving the capital-START anchor — so common lowercase words are still not
# matched as names. CASE refs stay ASCII (court codes are ASCII by construction).
_UPPER = "A-ZÀ-ÖØ-ÞĀ-ſ"  # A-Z, À-Þ, Latin Ext-A
_LOWER = "a-zß-öø-ÿĀ-ſ"  # a-z, ß-ÿ, Latin Ext-A
_ENTITY_PATTERN = re.compile(
    r"(?P<CASE>\b[A-Z]{2,8}-\d{4}-\d{2,6}\b)"
    r"|(?P<ORG>\b[" + _UPPER + r"][" + _UPPER + _LOWER + r"\-&\.\']{0,30}"
    r"(?:\s+(?:" + _ORG_SUFFIX_ALT + r"))\.?)"
    r"|(?P<PERSON>\b[" + _UPPER + r"][" + _LOWER + r"]{1,20}"
    r"(?:\s+[" + _UPPER + r"][" + _LOWER + r"]{1,20}){1,2}\b)",
    re.UNICODE,
)


def _kind_of(match: re.Match) -> str:
    return next(k for k, v in match.groupdict().items() if v is not None)


# Hosts the local-inference detector is allowed to reach. Kept in sync with
# config.PII_LOCAL_HOSTS but duplicated here so pii_shield has no import-time
# dependency on config (the shield must be usable standalone).
_LOCAL_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "0.0.0.0", "::1", "host.docker.internal"}
)


class PiiShieldError(RuntimeError):
    """Raised when the PII shield cannot guarantee redaction.

    Treated as fail-closed by callers: if this is raised the cloud LLM call
    MUST NOT proceed. Never downgrade this to a warning.
    """


def _is_local_url(url: str) -> bool:
    """True only if url's host is a loopback / local host.

    A cloud endpoint (api.openai.com, api.anthropic.com, …) returns False so
    the detector refuses to send raw transcript anywhere off the machine.
    """
    try:
        host = (urlparse(url).hostname or "").strip().lower()
    except (ValueError, TypeError):
        return False
    return host in _LOCAL_HOSTS


class EntityDetector(Protocol):
    """Swappable second-layer detector.

    detect(text) returns the raw substrings that must be redacted (person
    names incl. single/informal, orgs without legal suffixes, matter refs,
    addresses, monetary amounts, account numbers). Tests inject a fake; the
    default implementation calls a LOCAL OpenAI-compatible model.
    """

    def detect(self, text: str) -> list[str]: ...


_DETECT_SYSTEM = (
    "You are a PII redaction scanner for a law firm. Return ONLY a JSON array "
    "of the exact substrings in the user text that identify a real person, "
    "organisation, client, matter, case, address, monetary amount, or account "
    "number. Include informal/single first names (e.g. 'Mike', 'Smith'), "
    "organisations without a legal suffix (e.g. 'Acme'), street addresses, and "
    "amounts (e.g. '$40k'). Do NOT include generic legal words "
    "('motion', 'contract', 'hours'). Output strictly: [\"span\", \"span\"]. "
    "If nothing, output []."
)


@dataclass
class LocalLLMEntityDetector:
    """Default EntityDetector — a LOCAL OpenAI-compatible chat model.

    PARAMOUNT: this constructor REFUSES a non-local base_url. There is no
    cloud fallback by design — leaking raw transcript to a cloud provider
    would defeat the entire shield. If the local endpoint is unreachable
    the caller's anonymize() fails closed (PiiShieldError), it does NOT
    pass un-redacted text through.
    """

    base_url: str
    model: str
    api_key: str = "local"
    _client: Any = None

    def __post_init__(self) -> None:
        if not _is_local_url(self.base_url):
            raise PiiShieldError(
                "PII local-inference base_url is not a local host: "
                f"{self.base_url!r}. The redaction model must run on this "
                "machine; a cloud endpoint would leak client data. Set "
                "PII_LOCAL_LLM_BASE_URL to e.g. http://localhost:11434/v1."
            )

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - env-specific
            raise PiiShieldError(
                "openai package required for the local PII detector; "
                "install requirements or disable the shield explicitly."
            ) from exc
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def detect(self, text: str) -> list[str]:
        client = self._ensure_client()
        try:
            resp = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _DETECT_SYSTEM},
                    {"role": "user", "content": text},
                ],
                temperature=0,
            )
            raw = resp.choices[0].message.content or "[]"
        except Exception as exc:  # local model down / refused
            raise PiiShieldError(
                f"Local PII detector unreachable ({type(exc).__name__}: "
                f"{exc}). Failing closed — refusing to send transcript to "
                "the cloud LLM with incomplete redaction."
            ) from exc
        return _parse_spans(raw)


def _parse_spans(raw: str) -> list[str]:
    """Extract a JSON string array from a model reply. Lenient on fences."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [s for s in data if isinstance(s, str) and s.strip()]


@dataclass
class PiiSession:
    """Per-session entity registry.

    Not thread-safe — one session per transcript stream. Create a new
    PiiSession per voice dictation session for isolation.
    """

    _entity_to_ph: dict[str, str] = field(default_factory=dict)
    _ph_to_entity: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)
    # Optional layer-2 detector. When set, its spans are merged with the
    # regex hits before substitution. When it raises PiiShieldError the
    # whole anonymize() fails closed (the cloud call must not proceed).
    detector: Optional[EntityDetector] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _register(
        self, entity: str, kind: str, mappings: list[tuple[str, str]]
    ) -> None:
        """Add entity→placeholder to the registry if new (idempotent, O(1))."""
        if entity not in self._entity_to_ph and entity not in self._ph_to_entity:
            idx = self._counters.get(kind, 0) + 1
            self._counters[kind] = idx
            ph = f"{kind}_{idx}"
            self._entity_to_ph[entity] = ph
            self._ph_to_entity[ph] = entity
        if entity in self._entity_to_ph:
            pair = (entity, self._entity_to_ph[entity])
            if pair not in mappings:
                mappings.append(pair)

    def anonymize(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Replace PII entities with stable placeholders in a single O(n) pass.

        Returns (anonymized_text, [(original_entity, placeholder), ...]).
        The same entity always maps to the same placeholder within a session.
        """
        # Phase 1a: layer-1 regex scan — fast, deterministic (O(n)).
        mappings: list[tuple[str, str]] = []
        for match in _ENTITY_PATTERN.finditer(text):
            self._register(match.group(0), _kind_of(match), mappings)

        # Phase 1b: layer-2 local-inference scan — catches single names,
        # suffix-less orgs, addresses, amounts the regex cannot. A detector
        # failure raises PiiShieldError here (fail-closed) so the caller
        # never sends partially-redacted text to the cloud LLM.
        if self.detector is not None:
            for span in self.detector.detect(text):
                if span and span in text:
                    self._register(span, "PII", mappings)

        if not mappings:
            return text, []

        # Phase 2: single-pass O(n) substitution — longest entity first to
        # prevent "Acme" from shadowing "Acme Corp".
        sorted_entities = sorted(self._entity_to_ph, key=len, reverse=True)
        sub_pattern = re.compile("|".join(re.escape(e) for e in sorted_entities))
        result = sub_pattern.sub(lambda m: self._entity_to_ph[m.group(0)], text)
        return result, mappings

    def deanonymize(self, text: str) -> str:
        """Replace placeholders back to original entities in a single O(n) pass."""
        if not self._ph_to_entity:
            return text
        sub_pattern = re.compile(
            "|".join(re.escape(p) for p in self._ph_to_entity)
        )
        return sub_pattern.sub(lambda m: self._ph_to_entity[m.group(0)], text)

    def snapshot(self) -> dict[str, str]:
        """Return the current entity map for export / audit logging."""
        return dict(self._entity_to_ph)
