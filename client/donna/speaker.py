"""Text-to-speech via the OpenAI audio.speech.create endpoint.

This is the ONLY module that calls the TTS API and the ONLY module
that plays audio output. Everything else passes plain text strings.

Usage::

    speaker = Speaker(openai_client)
    speaker.speak("Logged. 90 minutes on the Smith motion.")
"""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
from pathlib import Path


_DEFAULT_MODEL = "tts-1"
_DEFAULT_VOICE = "nova"  # warm, professional — suits a legal assistant


class SpeakerError(RuntimeError):
    """Raised when TTS or audio playback fails."""


class Speaker:
    """Speaks text aloud using the OpenAI TTS API.

    Audio is played via sounddevice when available; falls back to
    the platform's native audio command (afplay on macOS, aplay on Linux).

    Parameters
    ----------
    client:
        An initialised ``openai.OpenAI`` instance.
    model:
        OpenAI TTS model. ``tts-1`` (faster) or ``tts-1-hd`` (higher quality).
    voice:
        Voice ID. Options: alloy, echo, fable, onyx, nova, shimmer.
        ``nova`` is warm and professional — recommended for DONNA.
    enabled:
        Set False to disable TTS globally (e.g. ``--no-tts`` flag).
    """

    def __init__(
        self,
        client,
        model: str = _DEFAULT_MODEL,
        voice: str = _DEFAULT_VOICE,
        enabled: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._voice = voice
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Convert *text* to speech and play it. No-op when disabled or text is empty."""
        if not self.enabled or not text.strip():
            return
        audio_bytes = self._synthesise(text)
        self._play(audio_bytes)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _synthesise(self, text: str) -> bytes:
        """Call the TTS API and return MP3 bytes."""
        try:
            response = self._client.audio.speech.create(
                model=self._model,
                voice=self._voice,
                input=text,
                response_format="mp3",
            )
            return response.content
        except Exception as exc:
            raise SpeakerError(f"TTS synthesis failed: {exc}") from exc

    def _play(self, audio_bytes: bytes) -> None:
        """Play MP3 bytes via sounddevice or platform fallback."""
        try:
            self._play_sounddevice(audio_bytes)
        except Exception:
            self._play_native(audio_bytes)

    def _play_sounddevice(self, audio_bytes: bytes) -> None:
        import sounddevice as sd
        from pydub import AudioSegment  # type: ignore[import]
        import numpy as np

        audio = AudioSegment.from_mp3(io.BytesIO(audio_bytes))
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        samples /= 32768.0
        if audio.channels == 2:
            samples = samples.reshape((-1, 2))
        sd.play(samples, samplerate=audio.frame_rate, blocking=True)

    def _play_native(self, audio_bytes: bytes) -> None:
        """Write to a temp file and play with afplay (macOS) or aplay (Linux)."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp = f.name
        try:
            if sys.platform == "darwin":
                subprocess.run(["afplay", tmp], check=True, capture_output=True)
            else:
                subprocess.run(
                    ["aplay", "--file-type", "mp3", tmp],
                    check=True,
                    capture_output=True,
                )
        finally:
            Path(tmp).unlink(missing_ok=True)
