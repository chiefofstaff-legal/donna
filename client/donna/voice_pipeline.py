"""End-to-end voice pipeline: capture → VAD → STT → router → confirmation.

Usage::

    pipeline = VoicePipeline.from_config(config)
    result = pipeline.run_once()  # blocks until utterance processed + spoken
"""

from __future__ import annotations

import time
from typing import Optional, Union

from donna.audio import AudioCapture
from donna.confirmation import ConfirmationFormatter
from donna.config import DonnaConfig
from donna.models import ClarifyRequest, Task, TimeEntry
from donna.router import Router
from donna.transcriber import Transcriber, get_transcriber
from donna.vad import VoiceActivityDetector


PipelineResult = Union[TimeEntry, Task, ClarifyRequest]
_VAD_TIMEOUT_S = 30


class VoicePipelineError(RuntimeError):
    """Raised when the pipeline cannot produce a result."""


class VoicePipeline:
    """Orchestrates the full voice → intent → action → confirmation pipeline.

    All concrete dependencies are injected; use :meth:`from_config` as a
    composition root when you want defaults wired from environment config.

    Parameters
    ----------
    capture:
        An :class:`~donna.audio.AudioCapture` instance.
    vad:
        A :class:`~donna.vad.VoiceActivityDetector` instance.
    transcriber:
        Any object implementing the :class:`~donna.transcriber.Transcriber` protocol.
    router:
        A :class:`~donna.router.Router` instance.
    speaker:
        Optional :class:`~donna.speaker.Speaker`. When supplied, DONNA reads
        back the confirmation after every successful result. Pass ``None``
        to disable TTS (e.g. ``--no-tts`` flag).
    min_speech_bytes:
        Minimum PCM bytes for a valid utterance (default: 0.5s at 16kHz).
    """

    def __init__(
        self,
        capture: AudioCapture,
        vad: VoiceActivityDetector,
        transcriber: Transcriber,
        router: Router,
        speaker: Optional[object] = None,
        min_speech_bytes: int = 16000,
    ) -> None:
        self._capture = capture
        self._vad = vad
        self._transcriber = transcriber
        self._router = router
        self._speaker = speaker
        self._formatter = ConfirmationFormatter()
        self._min_speech_bytes = min_speech_bytes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_once(self, prompt: str = "Listening… (press Enter to stop)") -> PipelineResult:
        """Record until Enter is pressed, then transcribe, route, and confirm."""
        print(prompt)
        self._capture.start()
        try:
            input()
        finally:
            raw_pcm = self._capture.stop()
        return self._process(raw_pcm)

    def run_vad(self, prompt: str = "Listening…") -> PipelineResult:
        """Record for _VAD_TIMEOUT_S seconds, then VAD-extract and process speech."""
        print(prompt)
        self._capture.start()
        time.sleep(_VAD_TIMEOUT_S)
        raw_pcm = self._capture.stop()
        return self._process(raw_pcm)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process(self, raw_pcm: bytes) -> PipelineResult:
        if len(raw_pcm) < self._min_speech_bytes:
            raise VoicePipelineError("No audio captured")
        segments = self._vad.extract_speech(raw_pcm)
        speech = b"".join(segments)
        if len(speech) < self._min_speech_bytes:
            raise VoicePipelineError("No speech detected in audio")
        transcript = self._transcriber.transcribe(speech, self._capture.sample_rate)
        if not transcript.strip():
            raise VoicePipelineError("Transcription returned empty text")
        result = self._router.handle(transcript)
        self._confirm(result)
        return result

    def _confirm(self, result: PipelineResult) -> None:
        """Speak the confirmation if a speaker is wired in."""
        if self._speaker is None:
            return
        text = self._formatter.format(result)
        self._speaker.speak(text)

    def speak(self, text: str) -> None:
        """Speak arbitrary text via TTS if a speaker is wired in."""
        if self._speaker is None:
            return
        self._speaker.speak(text)

    # ------------------------------------------------------------------
    # Composition root — concrete wiring lives here, not in __init__
    # ------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: DonnaConfig, tts_enabled: bool = True) -> "VoicePipeline":
        """Build a VoicePipeline from a DonnaConfig.

        Pass ``tts_enabled=False`` to skip TTS (equivalent to ``--no-tts``).
        """
        import openai
        from donna.speaker import Speaker

        openai_client = openai.OpenAI(api_key=config.openai_api_key)
        capture = AudioCapture(sample_rate=config.sample_rate)
        vad = VoiceActivityDetector(
            aggressiveness=config.vad_aggressiveness,
            sample_rate=config.sample_rate,
        )
        transcriber_kwargs = (
            {"client": openai_client} if config.stt_backend == "api" else {}
        )
        transcriber = get_transcriber(config.stt_backend, **transcriber_kwargs)
        router = Router(config)
        speaker = Speaker(client=openai_client) if tts_enabled else None
        return cls(
            capture=capture,
            vad=vad,
            transcriber=transcriber,
            router=router,
            speaker=speaker,
        )
