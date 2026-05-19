"""
tests/test_smoke_harness_counter.py — regression guard for the smoke-harness
IDR counter (scripts/smoke-harness.sh::count_idr_entries).

Origin: the smoke harness was red on Linux CI for 5+ days while green on
macOS. Root cause: the grep pattern used backslash-escaped backticks
('^\\`\\`\\`idr'). GNU grep (Linux) treats \\` as a zero-width
start-of-buffer anchor, so the pattern matched nothing; BSD grep (macOS)
treats \\` as a literal backtick, so it matched — the exact CI/local split.
Compounded by `grep -c ... || echo 0` emitting "0\\n0" on a zero-match file,
which broke the numeric comparison in verify_idr_grew.

These tests execute the REAL shipped function (Goodhart-proof: they fail if
the function logic is wrong, not merely if it is called) and statically pin
the exact pattern regression so it cannot silently return.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "scripts" / "smoke-harness.sh"

_bash_required = pytest.mark.skipif(
    shutil.which("bash") is None, reason="bash not available"
)


def _extract_counter_fn() -> str:
    src = HARNESS.read_text(encoding="utf-8")
    m = re.search(r"^count_idr_entries\(\) \{.*?^\}", src, re.S | re.M)
    assert m, "count_idr_entries() not found in smoke-harness.sh"
    return m.group(0)


def _executable_lines(fn: str) -> str:
    """Strip shell comment lines so static pattern guards scan only the
    code that actually runs.

    The function's docstring-style comment legitimately *quotes* the
    forbidden ``\\``` escape to explain why it is dangerous (the 5-day
    outage post-mortem). Documenting an anti-pattern is not committing
    it — the regression guard must pin the executable grep, not the
    educational comment, or it false-positives on its own warning.
    """
    out = []
    for line in fn.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


def _run_counter(tmp_path: Path, target: str) -> subprocess.CompletedProcess:
    snippet = tmp_path / "snippet.sh"
    snippet.write_text(
        _extract_counter_fn() + f'\ncount_idr_entries "{target}"\n',
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(snippet)], capture_output=True, text=True, timeout=30
    )


@_bash_required
def test_counter_has_no_gnu_unsafe_escaped_backtick():
    """The grep pattern must use literal, unescaped backticks.

    GNU grep reads \\` as a start-of-buffer anchor (matches nothing on Linux
    CI); BSD grep reads it as a literal backtick. Unescaped backticks behave
    identically on both. This pins the exact 5-day-outage regression.
    """
    fn = _extract_counter_fn()
    assert "grep" in fn, "counter no longer uses grep — re-review this guard"
    code = _executable_lines(fn)
    assert "\\`" not in code, (
        "count_idr_entries executable code contains a backslash-escaped "
        "backtick. GNU grep reads \\` as a zero-width start-of-buffer anchor "
        "and matches nothing on Linux CI. Use literal unescaped backticks. "
        "(Comments quoting the anti-pattern are exempt — only runnable code "
        "is scanned.)"
    )


@_bash_required
def test_counter_counts_real_fences(tmp_path: Path):
    chain = tmp_path / "SMOKE.md"
    chain.write_text(
        "intro\n```idr\n{\"a\":1}\n```\nmid\n```idr\n{\"b\":2}\n```\n"
        "```idr\n{\"c\":3}\n```\ntail\n",
        encoding="utf-8",
    )
    r = _run_counter(tmp_path, str(chain))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "3\n", f"expected '3\\n', got {r.stdout!r}"


@_bash_required
def test_counter_zero_matches_is_single_zero(tmp_path: Path):
    """A file with no fences must yield exactly '0\\n' — not '0\\n0\\n'."""
    chain = tmp_path / "SMOKE.md"
    chain.write_text("no fences here\njust text\n", encoding="utf-8")
    r = _run_counter(tmp_path, str(chain))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0\n", (
        f"zero-match must be exactly '0\\n', got {r.stdout!r} — the "
        f"'0\\n0' regression that broke verify_idr_grew"
    )


@_bash_required
def test_counter_missing_file_is_zero(tmp_path: Path):
    r = _run_counter(tmp_path, str(tmp_path / "does-not-exist.md"))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0\n", f"missing file must yield '0\\n', got {r.stdout!r}"


@_bash_required
def test_counter_output_is_numeric_comparable(tmp_path: Path):
    """verify_idr_grew does `[ "$after" -gt "$before" ]`; the counter output
    must be a single clean integer usable in a numeric test."""
    chain = tmp_path / "SMOKE.md"
    chain.write_text("```idr\n{}\n```\n", encoding="utf-8")
    r = _run_counter(tmp_path, str(chain))
    val = r.stdout.strip()
    assert val.isdigit(), f"counter output {val!r} is not a clean integer"
    assert int(val) == 1
    assert r.stdout.count("\n") == 1, f"expected one line, got {r.stdout!r}"
