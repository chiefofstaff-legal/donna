"""
examples/matter-summary/summarise.py — summarise a matter folder and emit IDR.

Usage:
    python3 examples/matter-summary/summarise.py \
        --matter examples/matter-summary/sample-matter/ \
        --provider anthropic \
        --emit-idr

When MOCK_PROVIDER=1: returns canned summary without calling any LLM.
Falsification: IDR signature must verify under bin/notarise verify.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.mock_provider import is_mock, maybe_mock
from lib.docuseal_webhook import append_to_chain, event_to_idr


def _emit_idr(result: dict, matter_path: Path) -> int:
    event = {
        "event_type": "submission.created",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "submission_id": f"summary-{int(time.time())}",
            "submitter": {"email": "donna-bot@example.com", "name": "DONNA"},
            "submission": {"id": 0, "template_id": 0},
        },
    }
    idr = event_to_idr(event)
    idr["intent"] = "matter_summarised"
    idr["actor"]["matter_path"] = str(matter_path)
    idr["actor"]["sources"] = result["sources"]
    chain_path = Path(os.environ.get("DONNA_CHAIN_PATH", "PROBAT.md"))
    try:
        record_hash = append_to_chain(idr, chain_path)
        print(f"IDR: {idr['signature']}")
        print(f"Chain: {chain_path} (hash {record_hash[:8]}...)")
        return 0
    except EnvironmentError as exc:
        sys.stderr.write(f"warning: IDR not emitted — {exc}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Summarise a matter folder.")
    parser.add_argument("--matter", required=True)
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--emit-idr", action="store_true")
    args = parser.parse_args(argv)

    matter_path = Path(args.matter)
    if not matter_path.exists():
        sys.stderr.write(f"error: matter folder not found: {matter_path}\n")
        return 1

    if is_mock():
        result = maybe_mock("matter_summary")
    else:
        raise NotImplementedError(
            f"Live provider '{args.provider}' not wired. Set MOCK_PROVIDER=1."
        )

    print(f"Matter:    {matter_path.name}")
    print(f"Sources:   {result['sources']}")
    print(f"Summary:   {result['summary']}")
    print(f"Key dates: {result['key_dates']}")
    return _emit_idr(result, matter_path) if args.emit_idr else 0


if __name__ == "__main__":
    sys.exit(main())
