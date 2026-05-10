"""
examples/doc-ingest/query.py — query an ingested document index and emit IDR.

Usage:
    python3 examples/doc-ingest/query.py \
        --question "what is the termination clause?" \
        --emit-idr

When MOCK_PROVIDER=1: returns canned answer + chunk citation.
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


def _emit_idr(result: dict, question: str) -> int:
    event = {
        "event_type": "submission.created",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "submission_id": f"query-{int(time.time())}",
            "submitter": {"email": "donna-bot@example.com", "name": "DONNA"},
            "submission": {"id": 0, "template_id": 0},
        },
    }
    idr = event_to_idr(event)
    idr["intent"] = "document_queried"
    idr["actor"]["question"] = question
    idr["actor"]["sources"] = result["sources"]
    chain_path = Path(os.environ.get("DONNA_CHAIN_PATH", "PROBAT.md"))
    try:
        record_hash = append_to_chain(idr, chain_path)
        print(f"IDR:    {idr['signature']}")
        print(f"Chain:  {chain_path} (hash {record_hash[:8]}...)")
        return 0
    except EnvironmentError as exc:
        sys.stderr.write(f"warning: IDR not emitted — {exc}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query an ingested document.")
    parser.add_argument("--question", required=True)
    parser.add_argument("--emit-idr", action="store_true")
    args = parser.parse_args(argv)

    if is_mock():
        result = maybe_mock("doc_query")
    else:
        raise NotImplementedError("Live query not wired. Set MOCK_PROVIDER=1.")

    print(f"Answer:  {result['answer']}")
    print(f"Sources: {result['sources']}")
    return _emit_idr(result, args.question) if args.emit_idr else 0


if __name__ == "__main__":
    sys.exit(main())
