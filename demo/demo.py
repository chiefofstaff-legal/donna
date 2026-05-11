#!/usr/bin/env python3
"""DONNA OSS Demo — Delegation Orchestration in 60 Seconds.

Plays three lawyer utterances through the full DONNA pipeline end-to-end:

  1. Extract intent  (deterministic regex; in production this is voice→LLM)
  2. Generate signed IDR (Intent Decision Record) via `bin/notarise sign`
  3. Append to demo/chain.md (PROBAT-format audit chain)
  4. Verify the chain end-to-end via `bin/notarise verify`
  5. Replay in plain English (what regulators see in an audit)

Pure stdlib. No dependencies. Runs offline. Deterministic output.

Usage:
    python3 demo/demo.py
or:
    make demo
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Dict, List, Tuple

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTARISE = ROOT / "bin" / "notarise"
CHAIN_FILE = ROOT / "demo" / "chain.md"
DEMO_KEY = "donna-public-demo-key-2026-05-08"
GENESIS = "0" * 64

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(t: str) -> str: return _c("1", t)
def dim(t: str) -> str: return _c("2", t)
def green(t: str) -> str: return _c("32", t)
def yellow(t: str) -> str: return _c("33", t)
def blue(t: str) -> str: return _c("34", t)
def magenta(t: str) -> str: return _c("35", t)


UTTERANCES: List[Dict[str, str]] = [
    {
        "speech": "Just spent 90 minutes on the Smith motion drafting the indemnity clauses.",
        "category": "time_entry",
    },
    {
        "speech": "Send Sarah the M&A precedent we used for Dubrovnik; ask her to redline by Tuesday.",
        "category": "delegation",
    },
    {
        "speech": "Forward the closing memo for Project Phoenix to Marcus when Sarah's redlines come back.",
        "category": "conditional_routing",
    },
]


_PRONOUNS_AND_FILLERS = {"the", "a", "an", "him", "her", "them",
                         "us", "me", "you", "this", "that", "it"}
_MATTER_PATTERNS = (
    r"([A-Z][a-z]+)\s+(?:motion|matter|case)",        # "Smith motion"
    r"[Pp]roject\s+([A-Z][a-z]+)",                    # "Project Phoenix"
    r"\bfor\s+([A-Z][a-z]+)\b",                       # "for Dubrovnik"
)


def _extract_duration(lower: str) -> object:
    m = re.search(r"(\d+)\s*(?:min|minute)", lower)
    if m:
        return round(int(m.group(1)) / 60, 2)
    m = re.search(r"(\d+(?:\.\d+)?)\s*hour", lower)
    if m:
        return float(m.group(1))
    return None


def _extract_recipients(speech: str) -> List[str]:
    """Capture proper-noun recipients from routing verbs and 'to <Name>'."""
    recipients: List[str] = []
    for m in re.finditer(
        r"(?:[Ss]end|[Aa]sk|[Ff]orward|[Tt]ell|[Cc]opy)\s+(\w+)", speech
    ):
        w = m.group(1)
        if w.lower() not in _PRONOUNS_AND_FILLERS and w[0].isupper():
            recipients.append(w)
    for m in re.finditer(r"\bto\s+([A-Z][a-z]+)\b", speech):
        w = m.group(1)
        if w not in recipients:
            recipients.append(w)
    return recipients


def _extract_matter(speech: str) -> object:
    for pat in _MATTER_PATTERNS:
        m = re.search(pat, speech)
        if m:
            return m.group(1)
    return None


def extract_intent(speech: str, category: str) -> Dict[str, object]:
    """Deterministic intent extraction. Mocks the voice→LLM pipeline with regex
    so the demo runs offline, deterministically, in well under a second."""
    out: Dict[str, object] = {"category": category}
    lower = speech.lower()

    duration = _extract_duration(lower)
    if duration is not None:
        out["duration_hours"] = duration

    recipients = _extract_recipients(speech)
    if recipients:
        out["recipients"] = recipients

    matter = _extract_matter(speech)
    if matter is not None:
        out["matter"] = matter

    m = re.search(
        r"by\s+(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)",
        speech, re.IGNORECASE,
    )
    if m:
        out["deadline"] = m.group(1).capitalize()

    m = re.search(r"when\s+(.+?)(?:[.;]|$)", speech)
    if m:
        out["trigger"] = m.group(1).strip()

    return out


def _summarise(intent: Dict[str, object]) -> str:
    """One-line narrative the IDR's `intent` field will record."""
    cat = intent.get("category")
    matter = intent.get("matter", "unknown matter")
    if cat == "time_entry":
        d = intent.get("duration_hours", "?")
        return f"Time entry: {d}h on {matter} — drafting"
    if cat == "delegation":
        rec = ",".join(intent.get("recipients", ["?"]))  # type: ignore[arg-type]
        dl = intent.get("deadline", "soon")
        return f"Delegate to {rec}: {matter} precedent, redline by {dl}"
    rec = ",".join(intent.get("recipients", ["?"]))  # type: ignore[arg-type]
    trig = intent.get("trigger", "trigger")
    return f"Conditional route: {trig} → forward to {rec} re {matter}"


def sign_idr(intent_summary: str, signer: str, confidence: float,
             previous_hash: str, metadata: Dict[str, object]) -> Dict[str, object]:
    """Call `bin/notarise sign` and parse the IDR JSON it emits."""
    env = {**os.environ, "DONNA_NOTARISE_KEY": DEMO_KEY}
    result = subprocess.run(
        [sys.executable, str(NOTARISE), "sign",
         "--intent", intent_summary,
         "--signer", signer,
         "--confidence", str(confidence),
         "--previous-hash", previous_hash,
         "--metadata", json.dumps(metadata)],
        capture_output=True, text=True, env=env, check=True,
    )
    return json.loads(result.stdout)


def chain_hash(idr: Dict[str, object]) -> str:
    payload = {k: v for k, v in idr.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def write_chain(idrs: List[Dict[str, object]], path: pathlib.Path) -> None:
    """Write IDRs as a PROBAT-format markdown chain (fenced ```idr blocks)."""
    lines: List[str] = [
        "# DONNA Demo Chain", "",
        "Generated by `python3 demo/demo.py`. Three lawyer utterances captured",
        "as signed IDRs, chained, verifiable end-to-end.", "",
        "Verify locally:", "",
        "```bash",
        "export DONNA_NOTARISE_KEY=donna-public-demo-key-2026-05-08",
        "python3 bin/notarise verify --chain demo/chain.md",
        "```", "",
        "Expected output: `OK: 3 record(s) verified (HMAC-SHA256)`", "",
        "---", "",
    ]
    for i, idr in enumerate(idrs, start=1):
        category = idr.get("metadata", {}).get("category", "decision")  # type: ignore[union-attr]
        lines.append(f"## Entry {i} — {category}")
        lines.append("")
        lines.append("```idr")
        lines.append(json.dumps(idr, sort_keys=True, indent=2))
        lines.append("```")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def verify_chain_file(path: pathlib.Path) -> Tuple[bool, str]:
    env = {**os.environ, "DONNA_NOTARISE_KEY": DEMO_KEY}
    r = subprocess.run(
        [sys.executable, str(NOTARISE), "verify", "--chain", str(path)],
        capture_output=True, text=True, env=env,
    )
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def banner() -> None:
    print()
    print(bold(magenta("═" * 60)))
    print(bold(magenta(" DONNA · Delegation Orchestration Demo · 60 Seconds")))
    print(dim("    Decision-Oriented Network Notarisation for Attorneys"))
    print(dim("    chiefofstaff-legal/donna · AGPL-3.0 · DONNA probat"))
    print(bold(magenta("═" * 60)))
    print()


def replay(idrs: List[Dict[str, object]]) -> None:
    print(bold(blue("Audit-chain replay (plain English — this is what regulators read):")))
    print()
    for i, idr in enumerate(idrs, start=1):
        meta = idr.get("metadata", {})
        ts = idr.get("timestamp", "")
        signer = idr.get("signer", "")
        conf = idr.get("confidence", "?")
        intent = idr.get("intent", "")
        sig = str(idr.get("signature", ""))[:16]
        prev = str(idr.get("previous_hash", ""))[:16]
        print(f"  {green(f'#{i}')} [{ts}] {bold(str(signer))} (confidence {conf}):")
        print(f"      {intent}")
        if meta:
            print(dim(f"      metadata: {json.dumps(meta)}"))
        print(dim(f"      signature: {sig}…   previous_hash: {prev}…"))
        print()


def _stage1_capture_and_sign() -> List[Dict[str, object]]:
    """Stage 1 — extract intent and sign one IDR per utterance."""
    print(bold("Stage 1 — Lawyer speaks. DONNA listens. Intent extracted."))
    print(dim("  (In production: voice → STT → LLM intent extraction → IDR."))
    print(dim("   In this demo: regex extraction, deterministic, offline.)"))
    print()
    idrs: List[Dict[str, object]] = []
    previous_hash = GENESIS
    for i, utterance in enumerate(UTTERANCES, start=1):
        speech = utterance["speech"]
        category = utterance["category"]
        print(f"  {yellow(f'[{i}/3]')} {bold('Lawyer says:')}")
        print(f"          \"{speech}\"")
        intent = extract_intent(speech, category)
        print(f"          {dim('→ intent extracted:')} {green(json.dumps(intent))}")
        summary = _summarise(intent)
        idr = sign_idr(summary, signer="donna-demo", confidence=0.92,
                       previous_hash=previous_hash, metadata=intent)
        previous_hash = chain_hash(idr)
        idrs.append(idr)
        print(f"          {dim('→ IDR signed:')} {green(str(idr['decision_id']))}  "
              f"{dim('sig:')} {str(idr['signature'])[:16]}…")
        print()
    return idrs


def _stage2_write_chain(idrs: List[Dict[str, object]]) -> None:
    print(bold("Stage 2 — Write the audit chain (markdown, regulator-readable)."))
    write_chain(idrs, CHAIN_FILE)
    rel = CHAIN_FILE.relative_to(ROOT)
    print(f"  chain → {green(str(rel))}")
    print()


def _stage3_verify() -> bool:
    print(bold("Stage 3 — Verify the chain end-to-end (HMAC-SHA256)."))
    ok, msg = verify_chain_file(CHAIN_FILE)
    status = green("✓") if ok else bold(yellow("✗"))
    print(f"  {status} {msg}")
    print()
    return ok


def _stage4_replay(idrs: List[Dict[str, object]]) -> None:
    print(bold("Stage 4 — Replay."))
    print()
    replay(idrs)


def _epilogue(elapsed: float) -> None:
    print(bold(green(f"Done in {elapsed:.1f}s. Three decisions, signed and chained.")))
    print()
    print(dim("  Verify yourself:"))
    print(dim(f"    export DONNA_NOTARISE_KEY={DEMO_KEY}"))
    print(dim("    python3 bin/notarise verify --chain demo/chain.md"))
    print()
    print(dim("  The chain notarises itself. DONNA probat."))
    print()


def main() -> int:
    start = time.time()
    banner()
    CHAIN_FILE.parent.mkdir(parents=True, exist_ok=True)
    idrs = _stage1_capture_and_sign()
    _stage2_write_chain(idrs)
    if not _stage3_verify():
        return 1
    _stage4_replay(idrs)
    _epilogue(time.time() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
