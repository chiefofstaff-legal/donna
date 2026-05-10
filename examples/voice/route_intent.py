"""
examples/voice/route_intent.py — transcribe an audio file and route the intent.

Usage:
    python3 examples/voice/route_intent.py --audio <file> [--provider anthropic] [--emit-idr]

When MOCK_PROVIDER=1: skips transcription and routing AI calls; uses canned response.
Always emits the IDR when --emit-idr is passed and DONNA_NOTARISE_KEY is set.
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


def _route_via_provider(audio_path: Path, provider: str) -> dict:
    raise NotImplementedError(
        f"Live provider '{provider}' not wired in OSS surface. "
        "Set MOCK_PROVIDER=1 for smoke testing."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe audio and route intent.")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--emit-idr", action="store_true")
    args = parser.parse_args(argv)

    audio_path = Path(args.audio)
    if not audio_path.exists():
        sys.stderr.write(f"error: audio file not found: {audio_path}\n")
        return 1

    if is_mock():
        result = maybe_mock("route_intent")
    else:
        result = _route_via_provider(audio_path, args.provider)

    print(f"Transcript:   {result['transcript']}")
    print(f"Routed to:    {result['route']} ({result['destination']})")
    print(f"Confidence:   {result['confidence']}")

    if args.emit_idr:
        event = {
            "event_type": "submission.created",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "data": {
                "submission_id": f"voice-{int(time.time())}",
                "submitter": {"email": result["destination"], "name": ""},
                "submission": {"id": 0, "template_id": 0},
            },
        }
        idr = event_to_idr(event)
        idr["intent"] = "voice_intent_routed"
        idr["actor"]["transcript"] = result["transcript"]
        idr["actor"]["route"] = result["route"]

        chain_path = Path(os.environ.get("DONNA_CHAIN_PATH", "PROBAT.md"))
        try:
            record_hash = append_to_chain(idr, chain_path)
            print(f"IDR signature: {idr['signature']}")
            print(f"IDR chain:     {chain_path} (hash {record_hash[:8]}...)")
        except EnvironmentError as exc:
            sys.stderr.write(f"warning: IDR not emitted — {exc}\n")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
