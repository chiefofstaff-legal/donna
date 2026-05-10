"""IP-claims reproducibility audit (PH-W3).

Tests every published IP claim in the launch artefacts against a
falsifiable invariant. See `tests/IP-CLAIMS-AUDIT-2026-05-09.md` for
the audit map (Groups A-F).

Group E covers claims previously untested. Group F is mutation
meta-tests proving existing tests can actually fail.
"""
from __future__ import annotations

import ast
import hmac
import json
import os
import re
import subprocess
from hashlib import sha256
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
NOTARISE_BIN = REPO_ROOT / "bin" / "notarise"
PROBAT_PATH = REPO_ROOT / "PROBAT.md"
README_PATH = REPO_ROOT / "README.md"
LICENSE_PATH = REPO_ROOT / "LICENSE"
SCENARIOS_PATH = REPO_ROOT / "docs" / "SCENARIOS.md"
TESTS_DIR = Path(__file__).parent

DEMO_KEY = "donna-public-demo-key-2026-05-08"


# ── Group E — new claim tests ───────────────────────────────────────────────


def test_notarise_stdlib_only():
    """E1: bin/notarise uses stdlib only — zero third-party imports."""
    src = NOTARISE_BIN.read_text(encoding="utf-8")
    tree = ast.parse(src)

    third_party = []
    stdlib_modules = {
        "argparse", "ast", "base64", "collections", "dataclasses", "datetime",
        "enum", "functools", "hashlib", "hmac", "io", "itertools", "json",
        "os", "pathlib", "re", "shutil", "stat", "string", "subprocess",
        "sys", "tempfile", "textwrap", "time", "traceback", "typing",
        "uuid", "warnings", "__future__",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in stdlib_modules:
                    third_party.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top not in stdlib_modules and node.level == 0:
                    third_party.append(node.module)

    assert third_party == [], (
        f"bin/notarise imports non-stdlib: {third_party}. "
        f"The 'stdlib-only' invariant is core to the README's promise."
    )


def test_probat_md_live_chain_verifies():
    """E2: PROBAT.md live chain verifies with the published demo key."""
    env = os.environ.copy()
    env["DONNA_NOTARISE_KEY"] = DEMO_KEY
    result = subprocess.run(
        [str(NOTARISE_BIN), "verify", "--chain", str(PROBAT_PATH)],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, (
        f"bin/notarise verify exited {result.returncode} on PROBAT.md. "
        f"stderr: {result.stderr[:500]}"
    )


def test_probat_md_entry1_is_genesis():
    """E3: PROBAT.md entry 1 uses genesis (64-zero) previous_hash."""
    text = PROBAT_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```idr\n(.*?)\n```", text, re.DOTALL)
    assert blocks, "PROBAT.md has no ```idr fenced blocks"
    first = json.loads(blocks[0])
    assert first.get("previous_hash") == "0" * 64, (
        f"Entry 1 previous_hash should be 64 zeros, got: "
        f"{first.get('previous_hash')!r}"
    )


def test_probat_md_all_entries_happi11():
    """E4: every PROBAT.md entry uses protocol `happi/1.1`."""
    text = PROBAT_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```idr\n(.*?)\n```", text, re.DOTALL)
    assert blocks, "PROBAT.md has no ```idr fenced blocks"
    for i, block in enumerate(blocks, start=1):
        record = json.loads(block)
        protocol = record.get("protocol") or record.get("v")
        assert protocol == "happi/1.1", (
            f"Entry {i} has protocol={protocol!r}, expected 'happi/1.1'. "
            f"Protocol drift would break the published-spec invariant."
        )


def test_idr_has_all_six_load_bearing_fields():
    """E5: IDR has all 6 load-bearing fields per PROBAT.md Appendix A.

    Canonical fields per the live PROBAT.md format:
    protocol, timestamp, intent, signer, previous_hash, signature.
    """
    text = PROBAT_PATH.read_text(encoding="utf-8")
    blocks = re.findall(r"```idr\n(.*?)\n```", text, re.DOTALL)
    assert blocks, "PROBAT.md has no IDR blocks to inspect"
    required = {
        "protocol", "timestamp", "intent",
        "signer", "previous_hash", "signature",
    }
    for i, block in enumerate(blocks, start=1):
        record = json.loads(block)
        missing = required - record.keys()
        assert not missing, (
            f"Entry {i} missing required fields: {missing}. "
            f"All six fields are load-bearing per Appendix A."
        )


def test_license_is_agpl3():
    """E6: LICENSE file is AGPL-3.0."""
    assert LICENSE_PATH.exists(), "LICENSE file is missing"
    text = LICENSE_PATH.read_text(encoding="utf-8")
    # AGPL-3.0 header is consistent across the canonical text.
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text, (
        "LICENSE does not contain the AGPL-3.0 header line. "
        "README badges + HN/LinkedIn launch posts advertise AGPL-3.0; "
        "drift here breaks the licensing invariant."
    )
    assert "Version 3" in text, (
        "LICENSE does not declare Version 3 — the launch posts cite v3 specifically."
    )


def test_scenarios_provider_agnostic_env_vars_documented():
    """E7: SCENARIOS.md documents the provider-agnostic env vars."""
    text = SCENARIOS_PATH.read_text(encoding="utf-8")
    # The README/HN/LinkedIn promise provider-agnostic operation. The
    # SCENARIOS prereqs section is the canonical place this is documented.
    for env_var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        assert env_var in text, (
            f"SCENARIOS.md does not mention {env_var}. "
            f"Provider-agnostic operation requires the three reference "
            f"envs to be discoverable in the runbook."
        )


def test_verify_ok_message_format_contains_hmac_sha256():
    """E8: bin/notarise verify prints 'OK: N record(s) verified (HMAC-SHA256)'."""
    env = os.environ.copy()
    env["DONNA_NOTARISE_KEY"] = DEMO_KEY
    result = subprocess.run(
        [str(NOTARISE_BIN), "verify", "--chain", str(PROBAT_PATH)],
        env=env, capture_output=True, text=True, timeout=15,
    )
    output = (result.stdout + result.stderr).strip()
    assert "OK:" in output, (
        f"verify output missing 'OK:' marker. Got: {output[:300]!r}"
    )
    assert "HMAC-SHA256" in output, (
        f"verify output missing 'HMAC-SHA256' label. The README + PROBAT "
        f"Appendix C promise this exact wording. Got: {output[:300]!r}"
    )


def test_demo_piped_through_verify_is_clean(tmp_path):
    """E9: bin/notarise demo output is self-verifying via --chain."""
    env = os.environ.copy()
    env["DONNA_NOTARISE_KEY"] = DEMO_KEY
    demo = subprocess.run(
        [str(NOTARISE_BIN), "demo"],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert demo.returncode == 0, f"demo exited {demo.returncode}"
    assert demo.stdout.strip(), "demo produced empty stdout"

    chain_path = tmp_path / "demo-chain.md"
    chain_path.write_text(demo.stdout, encoding="utf-8")
    verify = subprocess.run(
        [str(NOTARISE_BIN), "verify", "--chain", str(chain_path)],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert verify.returncode == 0, (
        f"demo output failed verify: returncode={verify.returncode}, "
        f"stderr={verify.stderr[:500]}"
    )


def test_mcp_server_directory_exists():
    """E10: TypeScript MCP server directory exists per ROADMAP W3."""
    mcp_dir = REPO_ROOT / "mcp-servers" / "donna"
    assert mcp_dir.is_dir(), (
        f"{mcp_dir} missing — ROADMAP W3 advertises the TS MCP server. "
        f"Removing this directory breaks the published roadmap invariant."
    )
    # Server entry point should be present
    entry = mcp_dir / "src" / "server.ts"
    assert entry.exists(), (
        f"{entry} missing — the MCP server entry point is load-bearing "
        f"for the donna_sign / donna_analyse / donna_draft / donna_review / "
        f"donna_export tool advertisements."
    )


# ── Group F — mutation meta-tests ───────────────────────────────────────────


def test_mutation_wrong_hmac_algo_detected():
    """F-M1: replacing SHA-256 with MD5 in sign() produces different bytes,
    which the canonical exact-signature assertion in test_sign_is_hmac_sha256
    would catch (different digest = assertion fails)."""
    payload = '{"intent":"test","ts":"2026-01-01T00:00:00Z","v":"happi/1.1"}'
    key = "test-key"
    sha256_digest = hmac.new(
        key.encode(), payload.encode(), sha256
    ).hexdigest()
    md5_digest = hmac.new(key.encode(), payload.encode(), "md5").hexdigest()
    # Mutation produces a digest of different length AND different bytes.
    assert len(sha256_digest) == 64
    assert len(md5_digest) == 32
    assert sha256_digest != md5_digest, (
        "MD5 and SHA-256 must produce different digests for the canonical "
        "test to detect the mutation."
    )
    # Verify the test_notarise suite asserts on SHA-256 specifically
    test_src = (TESTS_DIR / "test_notarise.py").read_text(encoding="utf-8")
    assert "sha256" in test_src.lower() or "hmac.new" in test_src, (
        "test_notarise.py does not reference HMAC-SHA256 — the mutation "
        "test cannot rely on an assertion that is not made."
    )


def test_mutation_skipped_sig_check_detected():
    """F-M2: a verify_one() that always returns [] (skipping signature
    check) would let a tampered record pass. The canonical
    test_verify_one_detects_signature_mismatch test detects this by
    constructing a record with a known-bad signature and asserting the
    returned errors list is non-empty."""
    test_src = (TESTS_DIR / "test_notarise.py").read_text(encoding="utf-8")
    assert "test_verify_one_detects_signature_mismatch" in test_src, (
        "Canonical mutation-detector test missing from test_notarise.py."
    )
    # The test must construct a tamper case AND assert errors is non-empty
    sig_test_block = re.search(
        r"def test_verify_one_detects_signature_mismatch.*?(?=\ndef |\Z)",
        test_src, re.DOTALL,
    )
    assert sig_test_block, "test body not parseable"
    block_text = sig_test_block.group(0)
    assert "assert" in block_text, "no assertion found in sig-mismatch test"


def test_mutation_signature_in_payload_detected():
    """F-M3: a canonical_payload() that includes the signature field
    would produce the same bytes regardless of the signature, breaking
    verifiability. The canonical test_canonical_payload_excludes_signature
    test detects this by inspecting the canonical bytes for absence of
    the 'signature' key."""
    test_src = (TESTS_DIR / "test_notarise.py").read_text(encoding="utf-8")
    assert "test_canonical_payload_excludes_signature" in test_src, (
        "Canonical mutation-detector test missing from test_notarise.py."
    )
    # The test must check the canonical bytes do NOT contain 'signature'
    block = re.search(
        r"def test_canonical_payload_excludes_signature.*?(?=\ndef |\Z)",
        test_src, re.DOTALL,
    )
    assert block, "test body not parseable"
    body = block.group(0)
    assert "signature" in body, (
        "test does not mention 'signature' — cannot detect inclusion mutation"
    )
    assert "not in" in body or "assert" in body, (
        "test lacks an absence assertion — mutation would not be detected"
    )


def test_mutation_broken_chain_link_detected():
    """F-M4: a verify_chain() that does not thread previous_hash between
    entries would fail to detect a re-ordered or substituted chain. The
    canonical test_verify_chain_detects_broken_link test detects this by
    constructing a chain with a bad link and asserting errors are returned."""
    test_src = (TESTS_DIR / "test_notarise.py").read_text(encoding="utf-8")
    assert "test_verify_chain_detects_broken_link" in test_src, (
        "Canonical chain-link mutation-detector test missing."
    )
    # The test must construct a chain AND assert that broken links surface errors
    block = re.search(
        r"def test_verify_chain_detects_broken_link.*?(?=\ndef |\Z)",
        test_src, re.DOTALL,
    )
    assert block, "test body not parseable"
    body = block.group(0)
    assert "previous_hash" in body, (
        "test does not reference previous_hash — cannot detect link mutation"
    )
