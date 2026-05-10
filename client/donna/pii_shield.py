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

import re
from dataclasses import dataclass, field

# Single combined pattern: case refs first (most specific), then orgs, then persons.
# Named groups allow classification in one finditer pass — O(n), no nested loops.
_ORG_SUFFIX_ALT = (
    r"Corp|Inc|Ltd|LLC|LLP|LP|PLC|GmbH|AG|NV|SA|Pty|Co|Group|Holdings|"
    r"Partners|Associates|Consulting|Services|Investments|Capital|Law|"
    r"Lawyers|Attorneys|Firm|Foundation|Trust"
)
_ENTITY_PATTERN = re.compile(
    r"(?P<CASE>\b[A-Z]{2,8}-\d{4}-\d{2,6}\b)"
    r"|(?P<ORG>\b[A-Z][A-Za-z\-&\.\']{0,30}"
    r"(?:\s+(?:" + _ORG_SUFFIX_ALT + r"))\.?)"
    r"|(?P<PERSON>\b[A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20}){1,2}\b)"
)


def _kind_of(match: re.Match) -> str:
    return next(k for k, v in match.groupdict().items() if v is not None)


@dataclass
class PiiSession:
    """Per-session entity registry.

    Not thread-safe — one session per transcript stream. Create a new
    PiiSession per voice dictation session for isolation.
    """

    _entity_to_ph: dict[str, str] = field(default_factory=dict)
    _ph_to_entity: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def anonymize(self, text: str) -> tuple[str, list[tuple[str, str]]]:
        """Replace PII entities with stable placeholders in a single O(n) pass.

        Returns (anonymized_text, [(original_entity, placeholder), ...]).
        The same entity always maps to the same placeholder within a session.
        """
        # Phase 1: discover entities and extend the registry (O(n) scan)
        mappings: list[tuple[str, str]] = []
        for match in _ENTITY_PATTERN.finditer(text):
            entity = match.group(0)
            if entity not in self._entity_to_ph and entity not in self._ph_to_entity:
                kind = _kind_of(match)
                idx = self._counters.get(kind, 0) + 1
                self._counters[kind] = idx
                ph = f"{kind}_{idx}"
                self._entity_to_ph[entity] = ph
                self._ph_to_entity[ph] = entity
            if entity in self._entity_to_ph:
                mappings.append((entity, self._entity_to_ph[entity]))

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
