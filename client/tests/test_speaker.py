"""Tests for donna.speaker — Speaker TTS.

All OpenAI API calls and audio playback are mocked.
No network or audio hardware required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from donna.speaker import Speaker, SpeakerError


def _mock_client(mp3_bytes: bytes = b"FAKE_MP3") -> MagicMock:
    client = MagicMock()
    response = MagicMock()
    response.content = mp3_bytes
    client.audio.speech.create.return_value = response
    return client


class TestSpeakerSpeak:
    def test_speak_calls_tts_api(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        with patch.object(speaker, "_play"):
            speaker.speak("Logged. 90 minutes on the Smith motion.")
        client.audio.speech.create.assert_called_once()

    def test_speak_passes_text_to_api(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        with patch.object(speaker, "_play"):
            speaker.speak("Hello DONNA.")
        call_kwargs = client.audio.speech.create.call_args.kwargs
        assert call_kwargs["input"] == "Hello DONNA."

    def test_speak_uses_default_voice(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        with patch.object(speaker, "_play"):
            speaker.speak("Test.")
        call_kwargs = client.audio.speech.create.call_args.kwargs
        assert call_kwargs["voice"] == "nova"

    def test_speak_uses_custom_voice(self):
        client = _mock_client()
        speaker = Speaker(client=client, voice="shimmer")
        with patch.object(speaker, "_play"):
            speaker.speak("Test.")
        call_kwargs = client.audio.speech.create.call_args.kwargs
        assert call_kwargs["voice"] == "shimmer"

    def test_speak_requests_mp3(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        with patch.object(speaker, "_play"):
            speaker.speak("Test.")
        call_kwargs = client.audio.speech.create.call_args.kwargs
        assert call_kwargs["response_format"] == "mp3"

    def test_speak_disabled_skips_api(self):
        client = _mock_client()
        speaker = Speaker(client=client, enabled=False)
        speaker.speak("This should not be spoken.")
        client.audio.speech.create.assert_not_called()

    def test_speak_empty_text_skips_api(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        speaker.speak("   ")
        client.audio.speech.create.assert_not_called()

    def test_speak_empty_string_skips_api(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        speaker.speak("")
        client.audio.speech.create.assert_not_called()

    def test_api_error_raises_speaker_error(self):
        client = MagicMock()
        client.audio.speech.create.side_effect = RuntimeError("quota exceeded")
        speaker = Speaker(client=client)
        with pytest.raises(SpeakerError, match="TTS synthesis failed"):
            speaker.speak("Test.")


class TestSpeakerPlayFallback:
    def test_native_fallback_called_when_sounddevice_fails(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        with (
            patch.object(speaker, "_synthesise", return_value=b"FAKE_MP3"),
            patch.object(speaker, "_play_sounddevice", side_effect=ImportError("no pydub")),
            patch.object(speaker, "_play_native") as mock_native,
        ):
            speaker.speak("Test.")
        mock_native.assert_called_once_with(b"FAKE_MP3")

    def test_native_play_macos_uses_afplay(self):
        client = _mock_client()
        speaker = Speaker(client=client)
        with (
            patch("donna.speaker.sys") as mock_sys,
            patch("donna.speaker.subprocess.run") as mock_run,
            patch("donna.speaker.tempfile.NamedTemporaryFile") as mock_tmp,
            patch("donna.speaker.Path"),
        ):
            mock_sys.platform = "darwin"
            mock_tmp.return_value.__enter__.return_value.name = "/tmp/test.mp3"
            speaker._play_native(b"MP3")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "afplay"
