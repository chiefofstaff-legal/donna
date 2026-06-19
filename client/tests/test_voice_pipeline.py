"""Integration tests for donna.voice_pipeline — VoicePipeline.

All hardware and external APIs are mocked. Tests verify:
- Full pipeline path: capture → VAD → transcriber → router
- Error paths (no audio, no speech, empty transcript)
- from_config factory wires all dependencies correctly
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest

# voice_pipeline transitively imports donna.audio, which imports numpy. numpy is
# a declared client dep (present in CI), but skip — not abort collection — when a
# contributor's bare env lacks it. See test_audio.py for the same guard rationale.
pytest.importorskip("numpy")

from donna.models import ClarifyRequest, Task, TimeEntry
from donna.voice_pipeline import VoicePipeline, VoicePipelineError


def _pcm(seconds: float = 1.0, sample_rate: int = 16000, value: int = 1000) -> bytes:
    n = int(sample_rate * seconds)
    return struct.pack(f"<{n}h", *([value] * n))


@pytest.fixture()
def mock_capture():
    cap = MagicMock()
    cap.sample_rate = 16000
    cap.is_recording = False
    return cap


@pytest.fixture()
def mock_vad():
    vad = MagicMock()
    vad.extract_speech.return_value = [_pcm(1.0)]
    return vad


@pytest.fixture()
def mock_transcriber():
    t = MagicMock()
    t.transcribe.return_value = "90 minutes on the Smith motion"
    return t


@pytest.fixture()
def mock_router():
    r = MagicMock()
    r.handle.return_value = TimeEntry(
        matter="Smith", duration_hours=1.5, confidence=0.95
    )
    return r


@pytest.fixture()
def pipeline(mock_capture, mock_vad, mock_transcriber, mock_router):
    return VoicePipeline(
        capture=mock_capture,
        vad=mock_vad,
        transcriber=mock_transcriber,
        router=mock_router,
        min_speech_bytes=100,
    )


class TestRunOnce:
    def test_happy_path_returns_time_entry(self, pipeline, mock_capture):
        mock_capture.stop.return_value = _pcm(1.0)
        with patch("builtins.input", return_value=""):
            result = pipeline.run_once()
        assert isinstance(result, TimeEntry)
        assert result.matter == "Smith"

    def test_calls_capture_start_and_stop(self, pipeline, mock_capture):
        mock_capture.stop.return_value = _pcm(1.0)
        with patch("builtins.input", return_value=""):
            pipeline.run_once()
        mock_capture.start.assert_called_once()
        mock_capture.stop.assert_called_once()

    def test_calls_vad_with_captured_audio(self, pipeline, mock_capture, mock_vad):
        audio = _pcm(1.0)
        mock_capture.stop.return_value = audio
        with patch("builtins.input", return_value=""):
            pipeline.run_once()
        mock_vad.extract_speech.assert_called_once_with(audio)

    def test_calls_transcriber_with_speech_segment(
        self, pipeline, mock_capture, mock_vad, mock_transcriber
    ):
        mock_capture.stop.return_value = _pcm(1.0)
        speech = _pcm(0.8)
        mock_vad.extract_speech.return_value = [speech]
        with patch("builtins.input", return_value=""):
            pipeline.run_once()
        mock_transcriber.transcribe.assert_called_once_with(speech, 16000)

    def test_calls_router_with_transcript(
        self, pipeline, mock_capture, mock_transcriber, mock_router
    ):
        mock_capture.stop.return_value = _pcm(1.0)
        mock_transcriber.transcribe.return_value = "Mike, draft by Friday"
        with patch("builtins.input", return_value=""):
            pipeline.run_once()
        mock_router.handle.assert_called_once_with("Mike, draft by Friday")

    def test_no_audio_raises(self, pipeline, mock_capture):
        mock_capture.stop.return_value = b""
        with patch("builtins.input", return_value=""):
            with pytest.raises(VoicePipelineError, match="No audio"):
                pipeline.run_once()

    def test_no_speech_raises(self, pipeline, mock_capture, mock_vad):
        mock_capture.stop.return_value = _pcm(1.0)
        mock_vad.extract_speech.return_value = []
        with patch("builtins.input", return_value=""):
            with pytest.raises(VoicePipelineError, match="No speech"):
                pipeline.run_once()

    def test_empty_transcript_raises(self, pipeline, mock_capture, mock_transcriber):
        mock_capture.stop.return_value = _pcm(1.0)
        mock_transcriber.transcribe.return_value = "   "
        with patch("builtins.input", return_value=""):
            with pytest.raises(VoicePipelineError, match="empty text"):
                pipeline.run_once()

    def test_stop_called_on_exception_in_input(self, pipeline, mock_capture):
        mock_capture.stop.return_value = _pcm(1.0)
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                pipeline.run_once()
        mock_capture.stop.assert_called_once()  # stop always fires (finally block)

    def test_router_returns_task(self, pipeline, mock_capture, mock_router):
        mock_capture.stop.return_value = _pcm(1.0)
        mock_router.handle.return_value = Task(
            assignee="Mike", task="Draft brief", priority="high", confidence=0.9
        )
        with patch("builtins.input", return_value=""):
            result = pipeline.run_once()
        assert isinstance(result, Task)
        assert result.assignee == "Mike"


class TestFromConfig:
    def test_from_config_builds_pipeline(self):
        from donna.config import Config

        config = Config(llm_api_key="test-key", openai_api_key="test-key")
        with (
            patch("openai.OpenAI"),
            patch("donna.voice_pipeline.AudioCapture"),
            patch("donna.voice_pipeline.VoiceActivityDetector"),
            patch("donna.voice_pipeline.get_transcriber", return_value=MagicMock()),
            patch("donna.voice_pipeline.Router"),
        ):
            pipeline = VoicePipeline.from_config(config)
        assert isinstance(pipeline, VoicePipeline)

    def test_from_config_uses_sample_rate(self):
        from donna.config import Config

        config = Config(llm_api_key="key", openai_api_key="key", sample_rate=8000)
        with (
            patch("openai.OpenAI"),
            patch("donna.voice_pipeline.AudioCapture") as mock_cap_cls,
            patch("donna.voice_pipeline.VoiceActivityDetector"),
            patch("donna.voice_pipeline.get_transcriber", return_value=MagicMock()),
            patch("donna.voice_pipeline.Router"),
        ):
            VoicePipeline.from_config(config)
        mock_cap_cls.assert_called_once_with(sample_rate=8000)

    def test_from_config_uses_vad_aggressiveness(self):
        from donna.config import Config

        config = Config(llm_api_key="key", openai_api_key="key", vad_aggressiveness=3)
        with (
            patch("openai.OpenAI"),
            patch("donna.voice_pipeline.AudioCapture"),
            patch("donna.voice_pipeline.VoiceActivityDetector") as mock_vad_cls,
            patch("donna.voice_pipeline.get_transcriber", return_value=MagicMock()),
            patch("donna.voice_pipeline.Router"),
        ):
            VoicePipeline.from_config(config)
        mock_vad_cls.assert_called_with(aggressiveness=3, sample_rate=16000)
