"""Anchors for scripts/probat_extend.py (donna#38) — catch-up, idempotent.

The driver must: notarise exactly the un-recorded first-parent commits, skip
its own chore(probat) output (PR-fallback convergence guard), be a no-op on
re-run, and degrade to HEAD-only when the chain has never named a commit.
"""
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "bin"))
sys.path.insert(0, str(_ROOT / "scripts"))
import notarise  # noqa: E402
import probat_extend  # noqa: E402

KEY = "test-key-for-extend-anchors"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo, fname, subject):
    (repo / fname).write_text(subject + "\n")
    _git(repo, "add", fname)
    _git(repo, "commit", "-m", subject)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv(notarise.ENV_KEY, KEY)
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.name", "t")
    _git(r, "config", "user.email", "t@t")
    return r


def _seed_chain(repo, commit_sha):
    genesis = notarise.sign(notarise.IDR(
        decision_id="idr_genesis", timestamp="2026-06-10T00:00:00Z",
        protocol=notarise.PROTOCOL_VERSION, intent="genesis", signer="t",
        confidence=1.0, previous_hash=notarise.GENESIS_PREVIOUS_HASH,
        metadata={"commit_sha": commit_sha},
    ))
    chain = repo / "PROBAT.md"
    chain.write_text(
        "# chain\n\n```idr\n"
        + json.dumps(asdict(genesis), indent=2, sort_keys=True)
        + "\n```\n\n## Appendix\n"
    )
    return chain


def test_catchup_notarises_each_pending_commit_once(repo):
    a = _commit(repo, "a.txt", "feat: first (#1)")
    chain = _seed_chain(repo, a)
    _commit(repo, "b.txt", "feat: second (#2)")
    _commit(repo, "c.txt", "fix: third")

    n = probat_extend.extend(str(chain), str(repo), signer="t")
    assert n == 2
    records = notarise.parse_probat(str(chain))
    assert len(records) == 3
    assert records[1].metadata["pr"] == 2
    assert "pr" not in records[2].metadata
    assert notarise.verify_chain(records) == []

    # idempotent fold: second pass finds nothing
    assert probat_extend.extend(str(chain), str(repo), signer="t") == 0


def test_skips_own_probat_commits(repo):
    a = _commit(repo, "a.txt", "feat: real work")
    chain = _seed_chain(repo, a)
    _commit(repo, "p.txt", "chore(probat): notarise abc123 [chain extend]")
    _commit(repo, "m.txt", "Merge pull request #9 from chiefofstaff-legal/probat/extend")
    assert probat_extend.extend(str(chain), str(repo), signer="t") == 0


def test_no_recorded_commit_starts_era_at_head_only(repo):
    _commit(repo, "a.txt", "feat: old history one")
    _commit(repo, "b.txt", "feat: old history two")
    head = _commit(repo, "c.txt", "feat: current (#7)")
    # chain whose records never name a commit_sha
    genesis = notarise.sign(notarise.IDR(
        decision_id="idr_g", timestamp="2026-06-10T00:00:00Z",
        protocol=notarise.PROTOCOL_VERSION, intent="bootstrap", signer="t",
        confidence=1.0, previous_hash=notarise.GENESIS_PREVIOUS_HASH,
        metadata={"commit": "bootstrap"},
    ))
    chain = repo / "PROBAT.md"
    chain.write_text("# c\n\n```idr\n" + json.dumps(asdict(genesis), indent=2, sort_keys=True) + "\n```\n")

    n = probat_extend.extend(str(chain), str(repo), signer="t")
    assert n == 1  # HEAD only — no 29-commit backfill
    records = notarise.parse_probat(str(chain))
    assert records[-1].metadata["commit_sha"] == head


def test_vanished_since_sha_degrades_to_head_only(repo, capsys):
    _commit(repo, "a.txt", "feat: base")
    chain = _seed_chain(repo, "f" * 40)  # commit that does not exist
    head = _commit(repo, "b.txt", "feat: tip")
    n = probat_extend.extend(str(chain), str(repo), signer="t")
    assert n == 1
    assert notarise.parse_probat(str(chain))[-1].metadata["commit_sha"] == head
