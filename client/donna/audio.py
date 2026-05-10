"""Audio capture via sounddevice.

This is the ONLY module that imports sounddevice. All other modules
receive raw bytes or numpy arrays — never a sounddevice object.

Usage::

    cap = AudioCapture(sample_rate=16000)
    cap.start()
    # ... speak ...
    audio_bytes = cap.stop()   # raw PCM int16 bytes
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np


class AudioCaptureError(RuntimeError):
    """Raised when the audio device cannot be opened or is already active."""


class AudioCapture:
    """Thread-safe microphone recorder.

    Records 16-bit mono PCM at *sample_rate* Hz until :meth:`stop` is called.
    Designed to be reused: ``start()`` / ``stop()`` cycles can repeat.
    """

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._frames: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: Optional[object] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Open the microphone stream and begin buffering audio."""
        import sounddevice as sd  # local import keeps the dep isolatable

        if self._stream is not None:
            raise AudioCaptureError("Recording already in progress")
        self._frames = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> bytes:
        """Stop recording and return raw PCM int16 bytes."""
        if self._stream is None:
            raise AudioCaptureError("No recording in progress")
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            frames = list(self._frames)
            self._frames = []
        if not frames:
            return b""
        audio = np.concatenate(frames, axis=0)
        return audio.astype(np.int16).tobytes()

    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _callback(self, indata: np.ndarray, frames: int, time, status) -> None:
        with self._lock:
            self._frames.append(indata.copy())
