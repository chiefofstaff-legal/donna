#!/usr/bin/env python3
"""probat_extend — notarise un-recorded main commits into PROBAT.md.

Catch-up semantics (chiefofstaff-legal/donna#38): find the last commit the
chain already records (newest record carrying metadata.commit_sha), then
append exactly one IDR per first-parent main commit since. Race-proof for
quick-succession merges (re-running after a reset recomputes the full pending
set) and self-healing (a missed run is absorbed by the next one). Running it
twice in a row is a no-op — the second pass finds nothing pending.

Skips its own output: commits whose subject starts with chore(probat) and
merge commits of the probat/extend fallback branch are never notarised,
otherwise the PR-fallback mode would notarise its own notarisations forever.

Stdlib only, like bin/notarise.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# bin/notarise is an extensionless executable — a plain `import` cannot see
# it (the notarise.py symlink some checkouts carry is test scaffolding, not
# tracked), so load it explicitly. Registered in sys.modules so the driver
# and any test importing `notarise` share one module instance.
_BIN = Path(__file__).resolve().parent.parent / "bin"
if "notarise" in sys.modules:
    notarise = sys.modules["notarise"]
else:
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader

    _loader = SourceFileLoader("notarise", str(_BIN / "notarise"))
    _spec = spec_from_loader("notarise", _loader)
    notarise = module_from_spec(_spec)
    sys.modules["notarise"] = notarise
    _loader.exec_module(notarise)

# Never notarise the notarisation itself (PR-fallback convergence guard).
SKIP_SUBJECT = re.compile(r"^chore\(probat\)|probat/extend")
PR_NUMBER = re.compile(r"\(#(\d+)\)\s*$")


def _git(repo_dir: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo_dir, *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def last_notarised_sha(records: List["notarise.IDR"]) -> Optional[str]:
    """Newest record that names a commit. None = per-merge era not started."""
    for rec in reversed(records):
        sha = rec.metadata.get("commit_sha")
        if sha:
            return sha
    return None


def pending_commits(repo_dir: str, since: Optional[str]) -> List[Tuple[str, str, str]]:
    """(sha, author, subject) for first-parent main commits needing records.

    since=None starts the per-merge era at HEAD only — the issue's done-when
    is per-merge extension, deliberately not a 29-commit historic backfill.
    A vanished `since` (history rewrite) degrades to the same HEAD-only start.
    """
    if since is None:
        rng = ["-1", "HEAD"]
    else:
        try:
            _git(repo_dir, "cat-file", "-e", f"{since}^{{commit}}")
            rng = ["--reverse", f"{since}..HEAD"]
        except subprocess.CalledProcessError:
            sys.stderr.write(
                f"warning: last notarised commit {since[:12]} not in history — "
                "starting per-merge era at HEAD\n"
            )
            rng = ["-1", "HEAD"]
    out = _git(repo_dir, "log", "--first-parent", "--format=%H%x09%an%x09%s", *rng)
    rows = [tuple(line.split("\t", 2)) for line in out.splitlines() if line]
    return [(s, a, subj) for s, a, subj in rows if not SKIP_SUBJECT.search(subj)]


def extend(chain_path: str, repo_dir: str, signer: str, dry_run: bool = False) -> int:
    """Append records for every pending commit. Returns the number appended."""
    records = notarise.parse_probat(chain_path)
    pending = pending_commits(repo_dir, last_notarised_sha(records))
    for sha, author, subject in pending:
        if dry_run:
            print(f"would notarise {sha[:12]} {subject}")
            continue
        metadata = {"commit_sha": sha, "author": author}
        pr = PR_NUMBER.search(subject)
        if pr:
            metadata["pr"] = int(pr.group(1))
        notarise.append_to_chain(
            chain_path=chain_path,
            intent=f"merge: {subject}",
            signer=signer,
            confidence=1.0,
            metadata=metadata,
            heading=f"merge: {subject}",
        )
        print(f"notarised {sha[:12]} {subject}")
    return len(pending)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="probat_extend", description=__doc__)
    parser.add_argument("--chain", default="PROBAT.md")
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--signer", default="github-actions")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        n = extend(args.chain, args.repo_dir, args.signer, args.dry_run)
    except (ValueError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    print(f"{n} record(s) {'pending' if args.dry_run else 'appended'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
