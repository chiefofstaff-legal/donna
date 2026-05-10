"""Voice Activity Detection via webrtcvad.

This is the ONLY module that imports webrtcvad. Consumers receive
plain lists of bytes (speech segments) — no webrtcvad objects leak out.

Usage::

    vad = VoiceActivityDetector(aggressiveness=2, sample_rate=16000)
    segments = vad.extract_speech(pcm_bytes)  # list[bytes]
    merged = b"".join(segments)
"""

from __future__ import annotations

from typing import Iterator


# webrtcvad requires 10ms, 20ms, or 30ms frames at 8/16/32/48 kHz.
_VALID_FRAME_MS = {10, 20, 30}
_VALID_SAMPLE_RATES = {8000, 16000, 32000, 48000}


class VADError(ValueError):
    """Raised for unsupported sample rates or frame durations."""


class VoiceActivityDetector:
    """Thin wrapper around webrtcvad.Vad.

    Parameters
    ----------
    aggressiveness:
        0 = least aggressive (more false positives),
        3 = most aggressive (fewer false positives, may clip speech).
    sample_rate:
        Must be one of 8000, 16000, 32000, 48000.
    frame_duration_ms:
        Frame size in milliseconds. Must be 10, 20, or 30.
    """

    def __init__(
        self,
        aggressiveness: int = 2,
        sample_rate: int = 16000,
        frame_duration_ms: int = 30,
    ) -> None:
        if sample_rate not in _VALID_SAMPLE_RATES:
            raise VADError(f"sample_rate must be one of {sorted(_VALID_SAMPLE_RATES)}")
        if frame_duration_ms not in _VALID_FRAME_MS:
            raise VADError(f"frame_duration_ms must be one of {sorted(_VALID_FRAME_MS)}")
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self._frame_bytes = int(sample_rate * frame_duration_ms / 1000) * 2  # int16 = 2 bytes/sample
        self._vad = self._make_vad(aggressiveness)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_speech(self, frame: bytes) -> bool:
        """Return True if *frame* contains speech.

        *frame* must be exactly :attr:`frame_bytes` bytes of int16 PCM.
        """
        if len(frame) != self._frame_bytes:
            raise VADError(
                f"Frame must be {self._frame_bytes} bytes "
                f"({self.frame_duration_ms}ms @ {self.sample_rate}Hz), "
                f"got {len(frame)}"
            )
        return bool(self._vad.is_speech(frame, self.sample_rate))

    def extract_speech(self, pcm_bytes: bytes, padding_frames: int = 3) -> list[bytes]:
        """Split *pcm_bytes* into voiced segments, discarding silence.

        Uses a simple ring-buffer triggered VAD: collects *padding_frames*
        silent frames before closing a segment.

        Returns a list of raw PCM bytes chunks, one per continuous speech region.
        """
        segments: list[bytes] = []
        current: list[bytes] = []
        silence_count = 0

        for frame in self._frames(pcm_bytes):
            if self.is_speech(frame):
                current.append(frame)
                silence_count = 0
            else:
                if current:
                    silence_count += 1
                    current.append(frame)
                    if silence_count >= padding_frames:
                        segments.append(b"".join(current))
                        current = []
                        silence_count = 0

        if current:
            segments.append(b"".join(current))
        return segments

    @property
    def frame_bytes(self) -> int:
        return self._frame_bytes

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _frames(self, pcm_bytes: bytes) -> Iterator[bytes]:
        offset = 0
        while offset + self._frame_bytes <= len(pcm_bytes):
            yield pcm_bytes[offset : offset + self._frame_bytes]
            offset += self._frame_bytes

    @staticmethod
    def _make_vad(aggressiveness: int):
        import webrtcvad  # local import keeps the dep isolatable
        vad = webrtcvad.Vad()
        vad.set_mode(aggressiveness)
        return vad
