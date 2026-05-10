"""Tests for donna.vad — VoiceActivityDetector.

webrtcvad is mocked; no C extension required at test time.
"""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, patch

import pytest

from donna.vad import VADError, VoiceActivityDetector


def _make_frame(duration_ms: int = 30, sample_rate: int = 16000, fill: int = 0) -> bytes:
    """Build a PCM int16 frame of the right byte length."""
    n_samples = int(sample_rate * duration_ms / 1000)
    return struct.pack(f"<{n_samples}h", *([fill] * n_samples))


@pytest.fixture()
def mock_vad_lib():
    """Patch webrtcvad so no C extension is needed."""
    mock_vad = MagicMock()
    with patch("donna.vad.VoiceActivityDetector._make_vad", return_value=mock_vad):
        yield mock_vad


@pytest.fixture()
def detector(mock_vad_lib):
    return VoiceActivityDetector(aggressiveness=2, sample_rate=16000, frame_duration_ms=30)


class TestVADInit:
    def test_invalid_sample_rate(self):
        with pytest.raises(VADError, match="sample_rate"):
            VoiceActivityDetector(sample_rate=44100)

    def test_invalid_frame_duration(self):
        with pytest.raises(VADError, match="frame_duration_ms"):
            VoiceActivityDetector(frame_duration_ms=25)

    def test_frame_bytes_calculation(self, detector):
        # 30ms @ 16kHz = 480 samples × 2 bytes = 960 bytes
        assert detector.frame_bytes == 960

    def test_frame_bytes_10ms(self, mock_vad_lib):
        vad = VoiceActivityDetector(frame_duration_ms=10)
        assert vad.frame_bytes == 320  # 160 samples × 2 bytes


class TestIsSpeech:
    def test_returns_true_when_vad_says_speech(self, detector, mock_vad_lib):
        mock_vad_lib.is_speech.return_value = True
        frame = _make_frame()
        assert detector.is_speech(frame) is True

    def test_returns_false_when_vad_says_silence(self, detector, mock_vad_lib):
        mock_vad_lib.is_speech.return_value = False
        frame = _make_frame()
        assert detector.is_speech(frame) is False

    def test_wrong_frame_size_raises(self, detector):
        with pytest.raises(VADError, match="Frame must be"):
            detector.is_speech(b"\x00" * 100)

    def test_passes_sample_rate_to_vad(self, detector, mock_vad_lib):
        mock_vad_lib.is_speech.return_value = False
        frame = _make_frame()
        detector.is_speech(frame)
        mock_vad_lib.is_speech.assert_called_once_with(frame, 16000)


class TestExtractSpeech:
    def _build_audio(self, pattern: list[bool], detector: VoiceActivityDetector) -> bytes:
        """Build PCM where speech frames contain noise (value=1000) and silence is zeros."""
        frames = []
        for is_speech in pattern:
            fill = 1000 if is_speech else 0
            frames.append(_make_frame(fill=fill))
        return b"".join(frames)

    def test_all_silence_returns_empty(self, detector, mock_vad_lib):
        mock_vad_lib.is_speech.return_value = False
        audio = self._build_audio([False] * 10, detector)
        assert detector.extract_speech(audio) == []

    def test_all_speech_returns_one_segment(self, detector, mock_vad_lib):
        mock_vad_lib.is_speech.return_value = True
        audio = self._build_audio([True] * 5, detector)
        # After 5 speech frames, no segment closed until trailing silence
        segments = detector.extract_speech(audio, padding_frames=3)
        # Final flush collects remaining
        assert len(segments) == 1

    def test_speech_then_silence_closes_segment(self, detector, mock_vad_lib):
        # 3 speech, then 5 silence (> padding_frames=3)
        responses = [True] * 3 + [False] * 5
        mock_vad_lib.is_speech.side_effect = responses
        audio = self._build_audio([True] * 3 + [False] * 5, detector)
        segments = detector.extract_speech(audio, padding_frames=3)
        assert len(segments) == 1
        # Segment includes 3 speech + 3 silence padding frames
        assert len(segments[0]) == detector.frame_bytes * 6

    def test_empty_audio_returns_empty(self, detector, mock_vad_lib):
        assert detector.extract_speech(b"") == []

    def test_partial_frame_ignored(self, detector, mock_vad_lib):
        """Leftover bytes that don't form a complete frame are silently dropped."""
        mock_vad_lib.is_speech.return_value = True
        # One full frame + 100 junk bytes
        audio = _make_frame() + b"\x00" * 100
        segments = detector.extract_speech(audio)
        # One frame = one speech segment (flushed at end)
        assert len(segments) == 1
