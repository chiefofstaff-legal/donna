"""
examples/doc-ingest/ingest.py — ingest a document and emit an IDR.

Usage:
    python3 examples/doc-ingest/ingest.py \
        --file examples/doc-ingest/sample-contract.pdf \
        --emit-idr

When MOCK_PROVIDER=1: skips embedding; records canned chunk count in IDR.
Falsification: bin/notarise verify --chain PROBAT.md must pass after run.
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


def _emit_idr(result: dict, file_path: Path) -> int:
    event = {
        "event_type": "submission.created",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "submission_id": f"ingest-{int(time.time())}",
            "submitter": {"email": "donna-bot@example.com", "name": "DONNA"},
            "submission": {"id": 0, "template_id": 0},
        },
    }
    idr = event_to_idr(event)
    idr["intent"] = "document_ingested"
    idr["actor"]["document"] = result["document"]
    idr["actor"]["chunks"] = result["chunks"]
    chain_path = Path(os.environ.get("DONNA_CHAIN_PATH", "PROBAT.md"))
    try:
        record_hash = append_to_chain(idr, chain_path)
        print(f"IDR:      {idr['signature']}")
        print(f"Chain:    {chain_path} (hash {record_hash[:8]}...)")
        return 0
    except EnvironmentError as exc:
        sys.stderr.write(f"warning: IDR not emitted — {exc}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a document.")
    parser.add_argument("--file", required=True)
    parser.add_argument("--emit-idr", action="store_true")
    args = parser.parse_args(argv)

    doc_path = Path(args.file)
    if not doc_path.exists():
        sys.stderr.write(f"error: file not found: {doc_path}\n")
        return 1

    if is_mock():
        result = maybe_mock("doc_ingest")
        result["document"] = doc_path.name
    else:
        raise NotImplementedError("Live embedding not wired. Set MOCK_PROVIDER=1.")

    print(f"Document: {result['document']}")
    print(f"Chunks:   {result['chunks']}")
    return _emit_idr(result, doc_path) if args.emit_idr else 0


if __name__ == "__main__":
    sys.exit(main())
