"""
tests/test_notarise.py — DONNA · bin/notarise audit-chain verifier test suite.

Coverage: 100% public functions. Mutation target: ≥80% kill rate.
Each test documents which mutation it catches.
"""
import importlib.machinery
import importlib.util
import json
import os
import sys
import hashlib
import hmac
from dataclasses import asdict
from pathlib import Path

import pytest

# ─── Load bin/notarise (via .py symlink so mutmut coverage tracing works) ─────
_REPO_ROOT = Path(__file__).parent.parent
# Use the .py symlink path — keeps file.__file__ == bin/notarise.py so coverage
# maps correctly when mutmut mutates that path.
_notarise_path = str(_REPO_ROOT / "bin" / "notarise.py")
_loader = importlib.machinery.SourceFileLoader("notarise", _notarise_path)
_spec = importlib.util.spec_from_loader("notarise", _loader)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["notarise"] = _mod  # register BEFORE exec so @dataclass __module__ resolves
_loader.exec_module(_mod)
import notarise as _n  # noqa: E402

_TEST_SECRET = "test-key-donna-unit-2026-abc123xyz"


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    """Set signing key for every test; guard tests override via delenv."""
    monkeypatch.setenv(_n.ENV_KEY, _TEST_SECRET)


def _make_idr(**overrides) -> _n.IDR:
    defaults = dict(
        decision_id="idr_1000000000_001",
        timestamp="2026-05-09T12:00:00Z",
        protocol=_n.PROTOCOL_VERSION,
        intent="test intent",
        signer="test-bot",
        confidence=0.9,
        previous_hash=_n.GENESIS_PREVIOUS_HASH,
        metadata={},
    )
    defaults.update(overrides)
    return _n.IDR(**defaults)


def _signed(**overrides) -> _n.IDR:
    return _n.sign(_make_idr(**overrides))


def _write_chain(path: Path, chain: list) -> None:
    with path.open("w") as f:
        for idr in chain:
            f.write("```idr\n")
            f.write(json.dumps(asdict(idr), indent=2, sort_keys=True))
            f.write("\n```\n\n")


@pytest.fixture
def chain_file(tmp_path) -> Path:
    path = tmp_path / "PROBAT.md"
    _write_chain(path, _n.demo_chain())
    return path


# ─── IDR.canonical_payload() ──────────────────────────────────────────────────

def test_canonical_payload_returns_bytes():
    # Mutation: wrong return type
    assert isinstance(_make_idr().canonical_payload(), bytes)


def test_canonical_payload_excludes_signature():
    # Mutation: signature included → verify_one always fails on signed records
    idr = _make_idr()
    idr.signature = "deadbeef"
    assert "signature" not in json.loads(idr.canonical_payload())


def test_canonical_payload_includes_all_fields():
    # Mutation: any field missing → hash breaks silently
    d = json.loads(_make_idr().canonical_payload())
    for f in ("decision_id", "timestamp", "protocol", "intent",
              "signer", "confidence", "previous_hash", "metadata"):
        assert f in d, f"missing: {f}"


def test_canonical_payload_sort_keys():
    # Mutation: unsorted keys → cross-language verification breaks
    keys = list(json.loads(_make_idr().canonical_payload()).keys())
    assert keys == sorted(keys)


def test_canonical_payload_compact_separators():
    # Mutation: whitespace inserted → downstream HMAC mismatches
    raw = _make_idr().canonical_payload().decode()
    assert ": " not in raw and ",\n" not in raw


def test_canonical_payload_utf8():
    # Mutation: wrong encoding → HMAC over wrong bytes
    _make_idr(intent="naïve résumé").canonical_payload().decode("utf-8")


def test_canonical_payload_changes_with_field():
    # Mutation: field ignored → signatures interchangeable across intents
    a = _make_idr(intent="alpha").canonical_payload()
    b = _make_idr(intent="beta").canonical_payload()
    assert a != b


# ─── IDR.hash() ───────────────────────────────────────────────────────────────

def test_hash_returns_64_hex():
    h = _make_idr().hash()
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_hash_is_sha256_of_payload():
    # Mutation: wrong hash algo → chain links break
    idr = _make_idr()
    assert idr.hash() == hashlib.sha256(idr.canonical_payload()).hexdigest()


def test_hash_deterministic():
    idr = _make_idr()
    assert idr.hash() == idr.hash()


def test_hash_differs_across_records():
    # Mutation: constant hash → chaining useless
    assert _make_idr(intent="a").hash() != _make_idr(intent="b").hash()


def test_hash_not_affected_by_signature():
    # Mutation: signature in hash → previous_hash can't be pre-computed
    a = _make_idr()
    b = _make_idr()
    b.signature = "changed"
    assert a.hash() == b.hash()


def test_hash_changes_with_previous_hash():
    # Mutation: previous_hash excluded → chain forgery possible
    assert _make_idr(previous_hash="a" * 64).hash() != _make_idr(previous_hash="b" * 64).hash()


def test_genesis_hash_is_64_zeros():
    # Mutation: wrong constant → entry 1 always fails
    assert _n.GENESIS_PREVIOUS_HASH == "0" * 64


def test_hash_changes_with_metadata():
    # Mutation: metadata excluded → metadata tampering undetectable
    assert _make_idr(metadata={}).hash() != _make_idr(metadata={"k": "v"}).hash()


# ─── sign() ───────────────────────────────────────────────────────────────────

def test_sign_sets_64_char_signature():
    # Mutation: signature not set → verify_one always fails
    idr = _n.sign(_make_idr())
    assert len(idr.signature) == 64


def test_sign_is_hmac_sha256():
    # Mutation: wrong algorithm → cross-impl breaks
    idr = _make_idr()
    expected = hmac.new(_TEST_SECRET.encode(), idr.canonical_payload(), hashlib.sha256).hexdigest()
    assert _n.sign(idr).signature == expected


def test_sign_deterministic():
    # Mutation: non-deterministic → verify always fails
    assert _n.sign(_make_idr()).signature == _n.sign(_make_idr()).signature


def test_sign_different_keys_differ(monkeypatch):
    # Mutation: key unused → spoofable with any key
    sig_a = _n.sign(_make_idr()).signature
    monkeypatch.setenv(_n.ENV_KEY, "other-key-xyz")
    sig_b = _n.sign(_make_idr()).signature
    assert sig_a != sig_b


def test_sign_modifies_in_place():
    # Mutation: sign returns copy → caller's record not updated
    idr = _make_idr()
    assert _n.sign(idr) is idr


# ─── verify_one() ─────────────────────────────────────────────────────────────

def test_verify_one_valid_empty():
    assert _n.verify_one(_signed(), _n.GENESIS_PREVIOUS_HASH) == []


def test_verify_one_no_chain_check_when_none():
    # Mutation: always checks previous_hash → genesis entry rejects None
    assert _n.verify_one(_signed(), None) == []


def test_verify_one_detects_signature_mismatch():
    # Mutation: sig check removed → tampered sigs pass
    idr = _signed()
    idr.signature = "0" * 64
    assert any("signature" in f for f in _n.verify_one(idr))


def test_verify_one_detects_chain_break():
    # Mutation: previous_hash check removed → chain break passes
    idr = _signed()
    failures = _n.verify_one(idr, "wrong" + "0" * 59)
    assert any("chain" in f.lower() or "previous_hash" in f.lower() for f in failures)


def test_verify_one_detects_wrong_protocol():
    # Mutation: protocol check removed → drift undetected
    idr = _make_idr(protocol="happi/0.9")
    _n.sign(idr)
    assert any("protocol" in f for f in _n.verify_one(idr))


def test_verify_one_detects_negative_confidence():
    # Mutation: lower bound removed → negative confidence passes
    idr = _make_idr(confidence=-0.1)
    _n.sign(idr)
    assert any("confidence" in f for f in _n.verify_one(idr))


def test_verify_one_detects_confidence_over_one():
    # Mutation: upper bound removed
    idr = _make_idr(confidence=1.1)
    _n.sign(idr)
    assert any("confidence" in f for f in _n.verify_one(idr))


def test_verify_one_confidence_zero_valid():
    assert _n.verify_one(_signed(confidence=0.0)) == []


def test_verify_one_confidence_one_valid():
    assert _n.verify_one(_signed(confidence=1.0)) == []


def test_verify_one_returns_list():
    assert isinstance(_n.verify_one(_signed()), list)


def test_verify_one_metadata_tamper_fails():
    # Mutation: metadata excluded from signature
    idr = _signed(metadata={"cat": "original"})
    idr.metadata = {"cat": "tampered"}
    assert _n.verify_one(idr) != []


def test_verify_one_intent_tamper_fails():
    idr = _signed(intent="original")
    idr.intent = "tampered"
    assert _n.verify_one(idr) != []


def test_verify_one_off_by_one_sig():
    # One char flip → mismatch detected (timing-safe compare)
    idr = _signed()
    last = idr.signature[-1]
    idr.signature = idr.signature[:-1] + ("0" if last != "0" else "1")
    assert _n.verify_one(idr) != []


# ─── verify_chain() ───────────────────────────────────────────────────────────

def test_verify_chain_empty_valid():
    # Mutation: empty list raises → genesis-only chain can't stand alone
    assert _n.verify_chain([]) == []


def test_verify_chain_single_valid():
    assert _n.verify_chain([_signed()]) == []


def test_verify_chain_demo_valid():
    # Full 3-entry chain verifies
    assert _n.verify_chain(_n.demo_chain()) == []


def test_verify_chain_stops_at_first():
    # Mutation: continues past failure → misleading error count
    good = _signed()
    bad = _make_idr(previous_hash=good.hash())
    bad.signature = "0" * 64
    assert len(_n.verify_chain([good, bad])) == 1


def test_verify_chain_detects_broken_link():
    # Mutation: link check removed → garbage previous_hash passes
    idr1 = _signed()
    idr2 = _n.sign(_make_idr(previous_hash="wrong" + "0" * 59))
    assert _n.verify_chain([idr1, idr2]) != []


def test_verify_chain_entry_number_in_failure():
    # Mutation: entry number wrong → developer confused which entry
    bad = _make_idr()
    bad.signature = "bad" + "0" * 61
    failures = _n.verify_chain([bad])
    assert "1" in failures[0]


def test_verify_chain_entry2_number_in_failure():
    # Mutation: always reports entry 1
    good = _signed()
    bad = _make_idr(previous_hash=good.hash())
    bad.signature = "0" * 64
    assert "2" in _n.verify_chain([good, bad])[0]


def test_verify_chain_returns_list():
    assert isinstance(_n.verify_chain([]), list)


def test_verify_chain_propagates_hash():
    # Mutation: hash not propagated → entry N+1 always fails
    e1 = _signed()
    e2 = _n.sign(_make_idr(decision_id="idr_2", previous_hash=e1.hash()))
    assert _n.verify_chain([e1, e2]) == []


def test_verify_chain_genesis_anchor():
    idr = _n.sign(_make_idr(previous_hash=_n.GENESIS_PREVIOUS_HASH))
    assert _n.verify_chain([idr]) == []


# ─── demo_chain() ─────────────────────────────────────────────────────────────

def test_demo_returns_three():
    assert len(_n.demo_chain()) == 3


def test_demo_entry1_genesis():
    assert _n.demo_chain()[0].previous_hash == _n.GENESIS_PREVIOUS_HASH


def test_demo_links_valid():
    chain = _n.demo_chain()
    assert chain[1].previous_hash == chain[0].hash()
    assert chain[2].previous_hash == chain[1].hash()


def test_demo_all_verify():
    assert _n.verify_chain(_n.demo_chain()) == []


def test_demo_entry1_bootstrap():
    assert "Bootstrap" in _n.demo_chain()[0].intent


def test_demo_entry2_delegation():
    assert "Delegation" in _n.demo_chain()[1].intent


def test_demo_entry3_soundbite():
    intent = _n.demo_chain()[2].intent
    assert "sound bite" in intent.lower() or "DONNA" in intent


def test_demo_all_happi11():
    for idr in _n.demo_chain():
        assert idr.protocol == _n.PROTOCOL_VERSION


def test_demo_all_signed():
    for idr in _n.demo_chain():
        assert len(idr.signature) == 64


# ─── parse_probat() ───────────────────────────────────────────────────────────

def test_parse_returns_three(chain_file):
    assert len(_n.parse_probat(str(chain_file))) == 3


def test_parse_returns_idr_instances(chain_file):
    assert all(isinstance(r, _n.IDR) for r in _n.parse_probat(str(chain_file)))


def test_parse_entry1_genesis(chain_file):
    assert _n.parse_probat(str(chain_file))[0].previous_hash == _n.GENESIS_PREVIOUS_HASH


def test_parse_chain_verifies(chain_file):
    assert _n.verify_chain(_n.parse_probat(str(chain_file))) == []


def test_parse_missing_file_raises():
    # JIT fix: FileNotFoundError → ValueError("not found")
    with pytest.raises(ValueError, match="not found"):
        _n.parse_probat("/nonexistent/PROBAT.md")


def test_parse_malformed_json_raises(tmp_path):
    # JIT fix: JSONDecodeError → ValueError("malformed")
    p = tmp_path / "bad.md"
    p.write_text("```idr\n{not valid json}\n```\n")
    with pytest.raises(ValueError, match="malformed"):
        _n.parse_probat(str(p))


def test_parse_wrong_fields_raises(tmp_path):
    # JIT fix: TypeError from IDR(**d) → ValueError("wrong fields")
    p = tmp_path / "bad.md"
    p.write_text('```idr\n{"unknown_field": "value"}\n```\n')
    with pytest.raises(ValueError, match="wrong fields"):
        _n.parse_probat(str(p))


def test_parse_unclosed_block_raises(tmp_path):
    # JIT fix: unclosed block → ValueError("unclosed")
    p = tmp_path / "bad.md"
    p.write_text("```idr\n{}\n")  # no closing ```
    with pytest.raises(ValueError, match="unclosed"):
        _n.parse_probat(str(p))


def test_parse_empty_file(tmp_path):
    # Mutation: empty file raises → should return []
    p = tmp_path / "empty.md"
    p.write_text("")
    assert _n.parse_probat(str(p)) == []


def test_parse_skips_non_idr_blocks(tmp_path):
    # Mutation: all fenced blocks parsed → python code blocks corrupt chain
    idr = _signed()
    p = tmp_path / "mixed.md"
    p.write_text(
        "```python\nprint('hi')\n```\n\n"
        + "```idr\n" + json.dumps(asdict(idr), indent=2, sort_keys=True) + "\n```\n"
    )
    assert len(_n.parse_probat(str(p))) == 1


def test_parse_correct_field_values(chain_file):
    # Mutation: field values swapped during parse
    demo = _n.demo_chain()
    parsed = _n.parse_probat(str(chain_file))
    assert parsed[0].intent == demo[0].intent
    assert parsed[0].signer == demo[0].signer
    assert parsed[0].confidence == demo[0].confidence


# ─── CLI: verify ──────────────────────────────────────────────────────────────

def test_cli_verify_exit0(chain_file):
    assert _n.main(["verify", "--chain", str(chain_file)]) == 0


def test_cli_verify_ok_message(chain_file, capsys):
    _n.main(["verify", "--chain", str(chain_file)])
    err = capsys.readouterr().err
    assert "OK" in err and "3" in err


def test_cli_verify_exit1_tampered(tmp_path):
    # Mutation: tampered chain returns 0 → security check bypassed
    chain = _n.demo_chain()
    chain[0].intent = "tampered"
    p = tmp_path / "tampered.md"
    _write_chain(p, chain)
    assert _n.main(["verify", "--chain", str(p)]) == 1


def test_cli_verify_at1(chain_file, capsys):
    result = _n.main(["verify", "--chain", str(chain_file), "--at", "1"])
    err = capsys.readouterr().err
    assert result == 0 and "1" in err


def test_cli_verify_at3(chain_file):
    assert _n.main(["verify", "--chain", str(chain_file), "--at", "3"]) == 0


def test_cli_verify_at_too_high(chain_file, capsys):
    # JIT fix: --at N where N > len → exit 2
    result = _n.main(["verify", "--chain", str(chain_file), "--at", "4"])
    err = capsys.readouterr().err
    assert result == 2
    assert "range" in err.lower()


def test_cli_verify_at_zero(chain_file, capsys):
    # JIT fix: --at 0 (1-indexed) → exit 2
    result = _n.main(["verify", "--chain", str(chain_file), "--at", "0"])
    err = capsys.readouterr().err
    assert result == 2
    assert "range" in err.lower()


def test_cli_verify_missing_file_exit1(capsys):
    # JIT fix: missing file → exit 1, not crash
    result = _n.main(["verify", "--chain", "/nonexistent/PROBAT.md"])
    err = capsys.readouterr().err
    assert result == 1
    assert "error" in err.lower()


def test_cli_verify_fail_in_stderr(tmp_path, capsys):
    # Mutation: FAIL message not written → operator can't see what failed
    chain = _n.demo_chain()
    chain[1].signature = "0" * 64
    p = tmp_path / "fail.md"
    _write_chain(p, chain)
    _n.main(["verify", "--chain", str(p)])
    assert "FAIL" in capsys.readouterr().err


# ─── CLI: sign ────────────────────────────────────────────────────────────────

def test_cli_sign_exit0(capsys):
    assert _n.main(["sign", "--intent", "create the NDA"]) == 0


def test_cli_sign_json_output(capsys):
    # Mutation: non-JSON → callers crash
    _n.main(["sign", "--intent", "create the NDA"])
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "signature" in parsed


def test_cli_sign_hash_to_stderr(capsys):
    # Mutation: hash not written → downstream can't link next entry
    _n.main(["sign", "--intent", "test"])
    assert "hash" in capsys.readouterr().err.lower()


def test_cli_sign_previous_hash(capsys):
    prev = "a" * 64
    _n.main(["sign", "--intent", "test", "--previous-hash", prev])
    assert json.loads(capsys.readouterr().out)["previous_hash"] == prev


def test_cli_sign_signer(capsys):
    _n.main(["sign", "--intent", "test", "--signer", "human-lawyer"])
    assert json.loads(capsys.readouterr().out)["signer"] == "human-lawyer"


def test_cli_sign_confidence(capsys):
    _n.main(["sign", "--intent", "test", "--confidence", "0.75"])
    assert abs(json.loads(capsys.readouterr().out)["confidence"] - 0.75) < 1e-9


def test_cli_sign_output_verifies(capsys):
    # End-to-end: signed entry passes verify_one
    _n.main(["sign", "--intent", "end-to-end"])
    idr = _n.IDR(**json.loads(capsys.readouterr().out))
    assert _n.verify_one(idr) == []


# ─── CLI: demo ────────────────────────────────────────────────────────────────

def test_cli_demo_exit0(capsys):
    assert _n.main(["demo"]) == 0


def test_cli_demo_three_blocks(capsys):
    _n.main(["demo"])
    assert capsys.readouterr().out.count("```idr") == 3


def test_cli_demo_output_verifies(tmp_path, capsys):
    # Mutation: demo output not valid → users get bad example
    _n.main(["demo"])
    p = tmp_path / "demo.md"
    p.write_text(capsys.readouterr().out)
    assert _n.verify_chain(_n.parse_probat(str(p))) == []


# ─── Missing-key guard ────────────────────────────────────────────────────────

def test_guard_sign_exits_2(monkeypatch):
    # Mutation: sys.exit(2) not called → missing key silently produces bad sig
    monkeypatch.delenv(_n.ENV_KEY)
    with pytest.raises(SystemExit) as exc:
        _n.sign(_make_idr())
    assert exc.value.code == 2


def test_guard_verify_cli_exits_2(chain_file, monkeypatch):
    # Mutation: key check removed → verify with garbage HMAC
    monkeypatch.delenv(_n.ENV_KEY)
    with pytest.raises(SystemExit) as exc:
        _n.main(["verify", "--chain", str(chain_file)])
    assert exc.value.code == 2


def test_guard_error_contains_env_var_name(monkeypatch, capsys):
    # Mutation: wrong var name in message → user doesn't know what to set
    monkeypatch.delenv(_n.ENV_KEY)
    with pytest.raises(SystemExit):
        _n.sign(_make_idr())
    assert _n.ENV_KEY in capsys.readouterr().err
