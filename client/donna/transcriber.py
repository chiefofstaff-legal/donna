"""Pluggable speech-to-text via the Transcriber protocol.

This is the ONLY module that calls STT APIs. Two backends ship out of the box:

- ``WhisperAPITranscriber``: calls OpenAI's ``audio.transcriptions.create``
  endpoint. Requires ``OPENAI_API_KEY``. Default.
- ``LocalWhisperTranscriber``: uses the ``openai-whisper`` package locally.
  No API key. Requires ``pip install openai-whisper`` (pulls torch).

Select via ``DONNA_STT_BACKEND`` env var: ``api`` (default) or ``local``.

Usage::

    t = get_transcriber("api", client=openai_client)
    text = t.transcribe(pcm_bytes, sample_rate=16000)
"""

from __future__ import annotations

import io
import wave
from typing import Protocol, runtime_checkable


@runtime_checkable
class Transcriber(Protocol):
    """Minimal STT interface. Every backend must implement this."""

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        """Convert raw PCM int16 *audio_bytes* to a text transcript."""
        ...


class WhisperAPITranscriber:
    """Transcribe via the OpenAI Whisper API (audio.transcriptions.create).

    Parameters
    ----------
    client:
        An initialised ``openai.OpenAI`` instance.
    model:
        Whisper model name. ``whisper-1`` is the only hosted option.
    language:
        ISO-639-1 language hint (e.g. ``"en"``). None = auto-detect.
    """

    def __init__(self, client, model: str = "whisper-1", language: str | None = "en") -> None:
        self._client = client
        self._model = model
        self._language = language

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        wav_bytes = _pcm_to_wav(audio_bytes, sample_rate)
        kwargs: dict = {
            "model": self._model,
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }
        if self._language:
            kwargs["language"] = self._language
        response = self._client.audio.transcriptions.create(**kwargs)
        return (response.text or "").strip()


class LocalWhisperTranscriber:
    """Transcribe locally using the ``openai-whisper`` package.

    ``openai-whisper`` (and torch) must be installed separately:
    ``pip install openai-whisper``.

    Parameters
    ----------
    model_name:
        Whisper model size: ``tiny``, ``base``, ``small``, ``medium``, ``large``.
    """

    def __init__(self, model_name: str = "base") -> None:
        self._model_name = model_name
        self._model = None  # lazy — torch import is slow

    def _load(self):
        if self._model is None:
            import whisper  # optional dep
            self._model = whisper.load_model(self._model_name)
        return self._model

    def transcribe(self, audio_bytes: bytes, sample_rate: int = 16000) -> str:
        import numpy as np
        import whisper

        model = self._load()
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        audio_fp32 = whisper.pad_or_trim(audio_np)
        mel = whisper.log_mel_spectrogram(audio_fp32).to(model.device)
        options = whisper.DecodingOptions(fp16=False)
        result = whisper.decode(model, mel, options)
        return (result.text or "").strip()


_BACKENDS: dict[str, type] = {
    "api": WhisperAPITranscriber,
    "local": LocalWhisperTranscriber,
}


def get_transcriber(backend: str = "api", **kwargs) -> Transcriber:
    """Factory. *kwargs* are forwarded to the backend constructor.

    For ``api``: pass ``client=<openai.OpenAI instance>``.
    For ``local``: pass ``model_name=<size>`` (optional).
    """
    cls = _BACKENDS.get(backend)
    if cls is None:
        raise ValueError(f"Unknown STT backend {backend!r}. Choose from: {sorted(_BACKENDS)}")
    return cls(**kwargs)


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap raw int16 PCM in a WAV container for the Whisper API."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # int16 = 2 bytes/sample
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
