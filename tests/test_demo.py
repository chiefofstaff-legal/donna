"""Goodhart-proof tests for the DONNA demo (demo/demo.py).

These tests assert real, falsifiable behaviour:
- The demo writes a 3-entry PROBAT chain
- All 3 entries verify via `bin/notarise verify` (exit 0)
- Tampering with any signature makes verify FAIL (exit 1)
- The regex extractor returns the expected fields for known utterances
- End-to-end runtime is under the 60-second budget claimed by the README

A test that always passes is worse than no test. Each assertion below would
fail if the corresponding piece of demo behaviour broke.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "demo"))

import demo  # noqa: E402

DEMO_KEY = "donna-public-demo-key-2026-05-08"
ENV = {**os.environ, "DONNA_NOTARISE_KEY": DEMO_KEY}


def _run_demo() -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(ROOT / "demo" / "demo.py")],
        capture_output=True, text=True, env=ENV,
    )
    return r.returncode, r.stdout + r.stderr


def _verify_chain(path: pathlib.Path) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "notarise"), "verify", "--chain", str(path)],
        capture_output=True, text=True, env=ENV,
    )
    return r.returncode, r.stdout + r.stderr


# ─── End-to-end: run demo, inspect chain ────────────────────────────────


def test_demo_exits_zero():
    rc, _ = _run_demo()
    assert rc == 0, "demo/demo.py must exit 0 on a healthy run"


def test_demo_writes_chain_file():
    _run_demo()
    chain = ROOT / "demo" / "chain.md"
    assert chain.exists(), "demo must produce demo/chain.md"
    assert chain.stat().st_size > 200, "chain.md must be non-trivial"


def test_demo_chain_has_three_entries():
    _run_demo()
    text = (ROOT / "demo" / "chain.md").read_text(encoding="utf-8")
    fenced = text.count("```idr")
    assert fenced == 3, f"chain must have exactly 3 ```idr blocks, found {fenced}"


def test_demo_chain_verifies():
    _run_demo()
    rc, out = _verify_chain(ROOT / "demo" / "chain.md")
    assert rc == 0, f"verify must exit 0; got rc={rc}, output={out!r}"
    assert "OK: 3 record(s) verified" in out, f"verify output missing OK line: {out!r}"


def test_demo_runtime_under_60s():
    start = time.time()
    rc, _ = _run_demo()
    elapsed = time.time() - start
    assert rc == 0
    assert elapsed < 60.0, f"H-DEMO-1 falsified: demo ran in {elapsed:.1f}s (limit 60s)"


# ─── Tamper detection (Goodhart killer) ─────────────────────────────────


def test_tampering_with_signature_breaks_verify(tmp_path):
    _run_demo()
    chain_text = (ROOT / "demo" / "chain.md").read_text(encoding="utf-8")
    tampered = tmp_path / "tampered.md"
    new = chain_text.replace('"signature": "', '"signature": "ff', 1)
    tampered.write_text(new, encoding="utf-8")
    rc, out = _verify_chain(tampered)
    assert rc != 0, "verify must FAIL on tampered signature"
    assert "FAIL" in out or "signature mismatch" in out


def test_tampering_with_intent_breaks_verify(tmp_path):
    _run_demo()
    chain_text = (ROOT / "demo" / "chain.md").read_text(encoding="utf-8")
    tampered = tmp_path / "tampered.md"
    new = chain_text.replace("Time entry:", "BACKDATED entry:", 1)
    tampered.write_text(new, encoding="utf-8")
    rc, _ = _verify_chain(tampered)
    assert rc != 0, "verify must FAIL on tampered intent text"


# ─── Extractor unit tests ────────────────────────────────────────────────


def test_extract_time_entry_duration_minutes():
    out = demo.extract_intent(
        "Just spent 90 minutes on the Smith motion drafting the indemnity clauses.",
        "time_entry",
    )
    assert out["duration_hours"] == 1.5
    assert out["matter"] == "Smith"


def test_extract_delegation_recipient_filters_pronouns():
    out = demo.extract_intent(
        "Send Sarah the M&A precedent we used for Dubrovnik; ask her to redline by Tuesday.",
        "delegation",
    )
    assert out["recipients"] == ["Sarah"], (
        f"pronoun 'her' must be filtered; got {out['recipients']}"
    )
    assert out["matter"] == "Dubrovnik"
    assert out["deadline"] == "Tuesday"


def test_extract_conditional_routing_captures_named_recipient():
    out = demo.extract_intent(
        "Forward the closing memo for Project Phoenix to Marcus when Sarah's redlines come back.",
        "conditional_routing",
    )
    assert out["recipients"] == ["Marcus"], (
        f"'to <Name>' pattern must catch Marcus, not 'the'; got {out['recipients']}"
    )
    assert out["matter"] == "Phoenix"
    assert out["trigger"] == "Sarah's redlines come back"


def test_extract_returns_only_known_fields():
    out = demo.extract_intent("Hello world.", "noise")
    assert out == {"category": "noise"}, (
        f"empty-speech extraction must produce only category; got {out}"
    )


# ─── Hypothesis H-DEMO-1 marker ─────────────────────────────────────────


def test_hypothesis_h_demo_1():
    """H-DEMO-1: fresh-clone demo produces 3 verifiable IDRs in <60s, all fields
    extracted correctly. Falsification = any sub-test above fails."""
    rc, out = _run_demo()
    assert rc == 0
    assert "Done in" in out
    assert "OK: 3 record(s) verified" in out
