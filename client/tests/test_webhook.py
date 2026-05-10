"""Tests for donna.webhook — webhook delivery. stdlib urllib mocked; no network required."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from donna.webhook import post


class _FakeResponse:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class TestWebhookPost:
    def test_returns_true_on_200(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(200)):
            assert post("http://example.com/hook", {"key": "val"}) is True

    def test_returns_true_on_201(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(201)):
            assert post("http://example.com/hook", {}) is True

    def test_returns_false_on_404(self):
        with patch("urllib.request.urlopen", return_value=_FakeResponse(404)):
            assert post("http://example.com/hook", {}) is False

    def test_returns_false_on_connection_error(self):
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            assert post("http://example.com/hook", {}) is False

    def test_returns_false_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError("timeout")):
            assert post("http://example.com/hook", {}) is False

    def test_no_op_when_url_empty(self):
        with patch("urllib.request.urlopen") as mock_open:
            assert post("", {"key": "val"}) is False
        mock_open.assert_not_called()

    def test_no_op_when_url_none(self):
        with patch("urllib.request.urlopen") as mock_open:
            assert post(None, {"key": "val"}) is False  # type: ignore[arg-type]
        mock_open.assert_not_called()

    def test_payload_serialised_as_json(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["body"] = json.loads(req.data)
            return _FakeResponse(200)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            post("http://example.com/hook", {"matter": "Smith", "hours": 1.5})
        assert captured["body"] == {"matter": "Smith", "hours": 1.5}

    def test_content_type_header(self):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["ct"] = req.get_header("Content-type")
            return _FakeResponse(200)

        with patch("urllib.request.urlopen", side_effect=fake_urlopen):
            post("http://example.com/hook", {})
        assert captured["ct"] == "application/json"
