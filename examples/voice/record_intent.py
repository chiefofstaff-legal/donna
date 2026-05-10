"""
examples/voice/record_intent.py — record a voice note to a WAV file.

Usage:
    python3 examples/voice/record_intent.py --out my-intent.wav [--duration 15]

When MOCK_PROVIDER=1: creates a minimal stub WAV so downstream scripts can run
without microphone access (smoke-harness safe).
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.mock_provider import is_mock


def _stub_wav(out_path: Path) -> None:
    """Write a minimal valid WAV header (44 bytes, 0 audio frames)."""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36, b"WAVE", b"fmt ", 16,
        1, 1, 16000, 32000, 2, 16, b"data", 0,
    )
    out_path.write_bytes(header)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record a voice note.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--duration", type=int, default=15)
    args = parser.parse_args(argv)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if is_mock():
        _stub_wav(out_path)
        print(f"[MOCK] Stub WAV written to {out_path}")
    else:
        raise NotImplementedError(
            "Live audio recording requires a microphone. "
            "Set MOCK_PROVIDER=1 for smoke testing."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
