"""Tests for CLI entry point — run_voice session summary."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from donna.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(llm_api_key="test-key", cache_db=tmp_path / "test.db")


class TestRunVoiceSessionSummary:
    def test_speaks_summary_on_keyboard_interrupt(self, cfg):
        """DONNA speaks daily_summary() text when voice mode exits."""
        mock_pipeline = MagicMock()
        mock_store = MagicMock()
        mock_store.daily_summary.return_value = "You've logged 1.5 hours today."
        with (
            patch("donna.voice_pipeline.VoicePipeline.from_config", return_value=mock_pipeline),
            patch("donna.store.TimeEntryStore", return_value=mock_store),
            patch("builtins.input", side_effect=KeyboardInterrupt),
        ):
            from main import run_voice

            run_voice(cfg, tts_enabled=True)
        mock_pipeline.speak.assert_called_once_with("You've logged 1.5 hours today.")

    def test_no_speak_when_tts_disabled(self, cfg):
        mock_pipeline = MagicMock()
        mock_store = MagicMock()
        mock_store.daily_summary.return_value = "No time logged today."
        with (
            patch("donna.voice_pipeline.VoicePipeline.from_config", return_value=mock_pipeline),
            patch("donna.store.TimeEntryStore", return_value=mock_store),
            patch("builtins.input", side_effect=KeyboardInterrupt),
        ):
            from main import run_voice

            run_voice(cfg, tts_enabled=False)
        # speak() is called — pipeline.speak() is a no-op when TTS disabled
        mock_pipeline.speak.assert_called_once()

    def test_speak_called_even_when_no_entries(self, cfg):
        mock_pipeline = MagicMock()
        mock_store = MagicMock()
        mock_store.daily_summary.return_value = "No time logged today."
        with (
            patch("donna.voice_pipeline.VoicePipeline.from_config", return_value=mock_pipeline),
            patch("donna.store.TimeEntryStore", return_value=mock_store),
            patch("builtins.input", side_effect=KeyboardInterrupt),
        ):
            from main import run_voice

            run_voice(cfg, tts_enabled=True)
        mock_pipeline.speak.assert_called_once_with("No time logged today.")


class TestRunVoiceWebhook:
    def test_posts_to_webhook_when_configured(self, cfg):
        cfg.webhook_url = "http://example.com/hook"
        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_pipeline.run_once.return_value = mock_result
        mock_store = MagicMock()
        with (
            patch("donna.voice_pipeline.VoicePipeline.from_config", return_value=mock_pipeline),
            patch("donna.store.TimeEntryStore", return_value=mock_store),
            patch("builtins.input", side_effect=["", KeyboardInterrupt]),
            patch("donna.webhook.post") as mock_webhook,
        ):
            from main import run_voice

            run_voice(cfg, tts_enabled=False)
        mock_webhook.assert_called_once()

    def test_no_webhook_when_url_not_configured(self, cfg):
        # cfg.webhook_url is None by default
        mock_pipeline = MagicMock()
        mock_store = MagicMock()
        with (
            patch("donna.voice_pipeline.VoicePipeline.from_config", return_value=mock_pipeline),
            patch("donna.store.TimeEntryStore", return_value=mock_store),
            patch("builtins.input", side_effect=KeyboardInterrupt),
            patch("donna.webhook.post") as mock_webhook,
        ):
            from main import run_voice

            run_voice(cfg, tts_enabled=False)
        mock_webhook.assert_not_called()


class TestRunHistory:
    def test_prints_entries(self, cfg, capsys):
        from donna.models import TimeEntry
        from donna.store import TimeEntryStore

        store = TimeEntryStore(cfg.cache_db)
        store.add(TimeEntry(matter="Smith", duration_hours=1.5, activity="drafting", confidence=0.9))
        with patch("donna.store.TimeEntryStore", return_value=store):
            from main import run_history

            run_history(cfg)
        out = capsys.readouterr().out
        assert "Smith" in out
        assert "1.50h" in out

    def test_prints_no_entries(self, cfg, capsys):
        with patch("donna.store.TimeEntryStore", return_value=MagicMock(query=MagicMock(return_value=[]))):
            from main import run_history

            run_history(cfg)
        assert "No time logged today." in capsys.readouterr().out

    def test_prints_total_row(self, cfg, capsys):
        from donna.models import TimeEntry
        from donna.store import TimeEntryStore

        store = TimeEntryStore(cfg.cache_db)
        store.add(TimeEntry(matter="A", duration_hours=1.0, confidence=0.9))
        store.add(TimeEntry(matter="B", duration_hours=0.5, confidence=0.9))
        with patch("donna.store.TimeEntryStore", return_value=store):
            from main import run_history

            run_history(cfg)
        assert "Total" in capsys.readouterr().out


class TestRunExportToday:
    def test_csv_output(self, cfg, capsys):
        from donna.models import TimeEntry
        from donna.store import TimeEntryStore

        store = TimeEntryStore(cfg.cache_db)
        store.add(TimeEntry(matter="Smith", duration_hours=1.0, activity="drafting", confidence=0.9))
        with patch("donna.store.TimeEntryStore", return_value=store):
            from main import run_export_today

            run_export_today(cfg, fmt="csv")
        out = capsys.readouterr().out
        assert "matter" in out
        assert "Smith" in out

    def test_json_output(self, cfg, capsys):
        import json as _json

        from donna.models import TimeEntry
        from donna.store import TimeEntryStore

        store = TimeEntryStore(cfg.cache_db)
        store.add(TimeEntry(matter="Jones", duration_hours=0.5, confidence=0.9))
        with patch("donna.store.TimeEntryStore", return_value=store):
            from main import run_export_today

            run_export_today(cfg, fmt="json")
        out = capsys.readouterr().out
        data = _json.loads(out)
        assert "data" in data

    def test_empty_export(self, cfg, capsys):
        with patch("donna.store.TimeEntryStore", return_value=MagicMock(query=MagicMock(return_value=[]))):
            from main import run_export_today

            run_export_today(cfg, fmt="csv")
        assert "matter" in capsys.readouterr().out


class TestMainDispatch:
    def test_history_flag_dispatches(self, cfg):
        with (
            patch("main.load_config", return_value=cfg),
            patch("main.run_history", return_value=0) as mock_history,
        ):
            from main import main

            main(["--history"])
        mock_history.assert_called_once_with(cfg)

    def test_export_today_flag_dispatches(self, cfg):
        with (
            patch("main.load_config", return_value=cfg),
            patch("main.run_export_today", return_value=0) as mock_export,
        ):
            from main import main

            main(["--export-today"])
        mock_export.assert_called_once_with(cfg, fmt="csv")

    def test_export_today_json_format(self, cfg):
        with (
            patch("main.load_config", return_value=cfg),
            patch("main.run_export_today", return_value=0) as mock_export,
        ):
            from main import main

            main(["--export-today", "--format", "json"])
        mock_export.assert_called_once_with(cfg, fmt="json")
