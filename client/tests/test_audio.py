"""Tests for donna.audio — AudioCapture.

All sounddevice calls are mocked; no hardware required.
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

# numpy is a real runtime dep (declared in client/pyproject.toml + installed in
# CI), but a contributor's bare env may not have it. Skip — rather than abort the
# WHOLE suite's collection — when it is absent. CI always has it, so this never
# hides a regression there; it only keeps `pytest` usable in a minimal env.
np = pytest.importorskip("numpy")

from donna.audio import AudioCapture, AudioCaptureError


@pytest.fixture()
def capture():
    return AudioCapture(sample_rate=16000, channels=1)


class TestAudioCaptureInit:
    def test_defaults(self):
        cap = AudioCapture()
        assert cap.sample_rate == 16000
        assert cap.channels == 1

    def test_custom_params(self):
        cap = AudioCapture(sample_rate=8000, channels=2)
        assert cap.sample_rate == 8000
        assert cap.channels == 2

    def test_not_recording_initially(self, capture):
        assert not capture.is_recording


class TestAudioCaptureStart:
    def test_start_opens_stream(self, capture):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream) as mock_cls:
            capture.start()
            mock_cls.assert_called_once_with(
                samplerate=16000,
                channels=1,
                dtype="int16",
                callback=capture._callback,
            )
            mock_stream.start.assert_called_once()
        capture._stream = None  # cleanup

    def test_is_recording_after_start(self, capture):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            capture.start()
            assert capture.is_recording
        capture._stream = None

    def test_double_start_raises(self, capture):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            capture.start()
            with pytest.raises(AudioCaptureError, match="already in progress"):
                capture.start()
        capture._stream = None


class TestAudioCaptureStop:
    def test_stop_without_start_raises(self, capture):
        with pytest.raises(AudioCaptureError, match="No recording"):
            capture.stop()

    def test_stop_returns_bytes(self, capture):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            capture.start()
            # Simulate two callbacks with 480-sample frames (30ms @ 16kHz)
            frame = np.zeros((480, 1), dtype=np.int16)
            capture._callback(frame, 480, None, None)
            capture._callback(frame, 480, None, None)
            result = capture.stop()
        assert isinstance(result, bytes)
        assert len(result) == 480 * 2 * 2  # 2 frames × 480 samples × 2 bytes

    def test_stop_empty_when_no_frames(self, capture):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            capture.start()
            result = capture.stop()
        assert result == b""

    def test_not_recording_after_stop(self, capture):
        mock_stream = MagicMock()
        with patch("sounddevice.InputStream", return_value=mock_stream):
            capture.start()
            capture.stop()
        assert not capture.is_recording


class TestAudioCaptureCallback:
    def test_callback_is_thread_safe(self, capture):
        """Multiple threads calling _callback must not corrupt _frames."""
        frame = np.zeros((480, 1), dtype=np.int16)
        threads = [
            threading.Thread(target=capture._callback, args=(frame, 480, None, None))
            for _ in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(capture._frames) == 20
