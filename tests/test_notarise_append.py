"""Anchors for bin/notarise append (donna#38) — atomic, verify-before-write.

Each test fails under the obvious mutation: drop the verify-before-write and
the tamper test passes a broken file; append at EOF instead of after the last
block and the appendix-ordering test fails; allow genesis-less append and the
no-genesis test fails.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

_BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(_BIN))
import notarise  # noqa: E402

KEY = "test-key-for-append-anchors"
APPENDIX = "## Appendix Z · must stay after every record\n"


def _seed_chain(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv(notarise.ENV_KEY, KEY)
    chain = tmp_path / "PROBAT.md"
    blocks = []
    for rec in notarise.demo_chain():
        blocks.append("```idr\n" + json.dumps(asdict(rec), indent=2, sort_keys=True) + "\n```\n")
    chain.write_text("# chain\n\n" + "\n".join(blocks) + "\n" + APPENDIX)
    return chain


def test_append_grows_chain_by_one_and_verifies(tmp_path, monkeypatch):
    chain = _seed_chain(tmp_path, monkeypatch)
    rec = notarise.append_to_chain(str(chain), intent="merge: test", signer="t", confidence=1.0,
                                   metadata={"commit_sha": "a" * 40})
    records = notarise.parse_probat(str(chain))
    assert len(records) == 4
    assert records[3].previous_hash == records[2].hash()
    assert records[3].decision_id == rec.decision_id
    assert notarise.verify_chain(records) == []


def test_append_inserts_before_appendices(tmp_path, monkeypatch):
    chain = _seed_chain(tmp_path, monkeypatch)
    notarise.append_to_chain(str(chain), intent="merge: ordering", signer="t", confidence=1.0)
    text = chain.read_text()
    assert text.index("merge: ordering") < text.index("Appendix Z")
    assert text.rstrip().endswith(APPENDIX.rstrip())


def test_append_requires_genesis(tmp_path, monkeypatch):
    monkeypatch.setenv(notarise.ENV_KEY, KEY)
    empty = tmp_path / "EMPTY.md"
    empty.write_text("# no records here\n")
    with pytest.raises(ValueError, match="genesis"):
        notarise.append_to_chain(str(empty), intent="x", signer="t", confidence=1.0)


def test_append_never_writes_a_broken_chain(tmp_path, monkeypatch):
    chain = _seed_chain(tmp_path, monkeypatch)
    before = chain.read_text()
    # chain was signed with KEY; switching keys makes the grown chain
    # unverifiable — append must refuse and leave the file byte-identical
    monkeypatch.setenv(notarise.ENV_KEY, "a-different-key-entirely")
    with pytest.raises(ValueError, match="verification"):
        notarise.append_to_chain(str(chain), intent="merge: tamper", signer="t", confidence=1.0)
    assert chain.read_text() == before


def test_cli_append_roundtrip(tmp_path, monkeypatch, capsys):
    chain = _seed_chain(tmp_path, monkeypatch)
    rc = notarise.main([
        "append", "--chain", str(chain), "--intent", "merge: via cli",
        "--signer", "cli", "--confidence", "0.9",
        "--metadata", '{"commit_sha": "bbb"}',
    ])
    assert rc == 0
    assert len(notarise.parse_probat(str(chain))) == 4
