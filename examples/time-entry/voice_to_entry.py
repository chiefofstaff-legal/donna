"""
examples/time-entry/voice_to_entry.py — record voice, produce structured time entry + IDR.

Usage:
    python3 examples/time-entry/voice_to_entry.py \
        --provider anthropic \
        --matter-list examples/time-entry/sample-matters.json \
        --emit-idr

When MOCK_PROVIDER=1: skips recording and AI extraction; uses canned time entry.
Falsification: bin/notarise verify --chain time-entries/<date>.jsonl must pass.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.mock_provider import is_mock, maybe_mock
from lib.docuseal_webhook import append_to_chain, event_to_idr


def _emit_idr_for_entry(entry: dict, out_path: Path) -> int:
    event = {
        "event_type": "submission.created",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "data": {
            "submission_id": f"time-{int(time.time())}",
            "submitter": {"email": "donna-bot@example.com", "name": "DONNA"},
            "submission": {"id": 0, "template_id": 0},
        },
    }
    idr = event_to_idr(event)
    idr["intent"] = "time_entry_recorded"
    idr["actor"]["matter_id"] = entry["matter_id"]
    idr["actor"]["duration_minutes"] = entry["duration_minutes"]
    chain_path = Path(os.environ.get("DONNA_CHAIN_PATH", str(out_path)))
    try:
        record_hash = append_to_chain(idr, chain_path)
        print(f"IDR signature: {idr['signature']}")
        print(f"Saved to:      {chain_path} (hash {record_hash[:8]}...)")
        return 0
    except EnvironmentError as exc:
        sys.stderr.write(f"warning: IDR not emitted — {exc}\n")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice to structured time entry.")
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--matter-list", default="examples/time-entry/sample-matters.json")
    parser.add_argument("--emit-idr", action="store_true")
    args = parser.parse_args(argv)

    if is_mock():
        entry = maybe_mock("time_entry")
    else:
        raise NotImplementedError(
            f"Live provider '{args.provider}' not wired. Set MOCK_PROVIDER=1."
        )

    date_str = time.strftime("%Y-%m-%d", time.gmtime())
    out_dir = Path("time-entries")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{date_str}.jsonl"

    print(f"Matter:   {entry['matter']} ({entry['matter_id']})")
    print(f"Duration: {entry['duration_minutes']} minutes")
    print(f"Activity: {entry['activity']}")
    print(f"Date:     {date_str}")

    return _emit_idr_for_entry(entry, out_path) if args.emit_idr else 0


if __name__ == "__main__":
    sys.exit(main())
