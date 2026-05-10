"""Tests for donna.transcriber — WhisperAPITranscriber and LocalWhisperTranscriber.

All external API calls are mocked; no OpenAI key or torch required.
"""

from __future__ import annotations

import io
import wave
from unittest.mock import MagicMock, patch

import pytest

from donna.transcriber import (
    LocalWhisperTranscriber,
    Transcriber,
    WhisperAPITranscriber,
    _pcm_to_wav,
    get_transcriber,
)


def _silent_pcm(seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    n_samples = int(sample_rate * seconds)
    return b"\x00\x02" * n_samples  # pseudo-PCM bytes


class TestPcmToWav:
    def test_produces_valid_wav(self):
        pcm = _silent_pcm(0.5)
        wav = _pcm_to_wav(pcm, 16000)
        buf = io.BytesIO(wav)
        with wave.open(buf) as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == len(pcm) // 2

    def test_output_is_bytes(self):
        assert isinstance(_pcm_to_wav(b"\x00" * 32, 16000), bytes)


class TestWhisperAPITranscriber:
    def _make_client(self, text: str = "90 minutes on the Smith matter") -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        response.text = text
        client.audio.transcriptions.create.return_value = response
        return client

    def test_returns_transcript_text(self):
        client = self._make_client("90 minutes on the Smith matter")
        t = WhisperAPITranscriber(client=client)
        result = t.transcribe(_silent_pcm(), sample_rate=16000)
        assert result == "90 minutes on the Smith matter"

    def test_strips_whitespace(self):
        client = self._make_client("  hello  ")
        t = WhisperAPITranscriber(client=client)
        assert t.transcribe(_silent_pcm()) == "hello"

    def test_passes_language_hint(self):
        client = self._make_client()
        t = WhisperAPITranscriber(client=client, language="de")
        t.transcribe(_silent_pcm())
        call_kwargs = client.audio.transcriptions.create.call_args.kwargs
        assert call_kwargs.get("language") == "de"

    def test_no_language_omits_param(self):
        client = self._make_client()
        t = WhisperAPITranscriber(client=client, language=None)
        t.transcribe(_silent_pcm())
        call_kwargs = client.audio.transcriptions.create.call_args.kwargs
        assert "language" not in call_kwargs

    def test_passes_wav_not_raw_pcm(self):
        client = self._make_client()
        t = WhisperAPITranscriber(client=client)
        t.transcribe(_silent_pcm())
        call_kwargs = client.audio.transcriptions.create.call_args.kwargs
        filename, data, mime = call_kwargs["file"]
        assert filename == "audio.wav"
        assert mime == "audio/wav"
        # WAV starts with RIFF header
        assert data[:4] == b"RIFF"

    def test_empty_response_returns_empty_string(self):
        client = self._make_client("")
        client.audio.transcriptions.create.return_value.text = None
        t = WhisperAPITranscriber(client=client)
        assert t.transcribe(_silent_pcm()) == ""

    def test_implements_transcriber_protocol(self):
        client = self._make_client()
        t = WhisperAPITranscriber(client=client)
        assert isinstance(t, Transcriber)


class TestGetTranscriber:
    def test_api_backend_returns_whisper_api(self):
        client = MagicMock()
        t = get_transcriber("api", client=client)
        assert isinstance(t, WhisperAPITranscriber)

    def test_local_backend_returns_local_whisper(self):
        t = get_transcriber("local")
        assert isinstance(t, LocalWhisperTranscriber)

    def test_unknown_backend_raises(self):
        with pytest.raises(ValueError, match="Unknown STT backend"):
            get_transcriber("nonexistent")

    def test_result_implements_protocol(self):
        client = MagicMock()
        t = get_transcriber("api", client=client)
        assert isinstance(t, Transcriber)
