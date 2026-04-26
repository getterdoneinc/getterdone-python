"""
Tests for cancel_task() and approve_task() envelope shapes.

Both routes return { "task": ..., "refunded"|"payout": ... } (not a bare Task dict).
These tests confirm the SDK correctly surfaces those shapes to the caller.

Uses the same mock pattern as test_client.py:
  - _make_urlopen_mock patches urllib.request.urlopen
  - _get_token is patched out to avoid a second HTTP round-trip
"""

import json
import urllib.request
from typing import Any
from unittest.mock import MagicMock

import pytest

from getterdone import GetterDone, CancelTaskResult, ApproveTaskResult


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_urlopen_mock(mocker: Any, payload: Any) -> MagicMock:
    """Return a mock suitable for patching urllib.request.urlopen."""
    mock_resp = mocker.MagicMock()
    mock_resp.read.return_value = json.dumps({"data": payload}).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = mocker.MagicMock(return_value=False)
    return mocker.patch("urllib.request.urlopen", return_value=mock_resp)


def _make_client() -> GetterDone:
    return GetterDone(api_key="gd_testid:testsecret", base_url="https://test.example")


# ─── cancel_task ──────────────────────────────────────────────────────────────

class TestCancelTask:
    """Tests for GetterDone.cancel_task()."""

    def test_returns_task_and_refunded_keys(self, mocker: Any) -> None:
        """cancel_task() should return a dict with 'task' and 'refunded' keys."""
        mock_payload = {
            "task": {
                "id": "task_123",
                "status": "cancelled",
                "title": "Test Task",
                "reward": 8.00,
            },
            "refunded": 8.00,
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result: CancelTaskResult = gd.cancel_task("task_123")

        assert "task" in result
        assert "refunded" in result

    def test_task_has_cancelled_status(self, mocker: Any) -> None:
        """The task inside the result should have status 'cancelled' (double-l)."""
        mock_payload = {
            "task": {"id": "task_123", "status": "cancelled"},
            "refunded": 8.00,
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.cancel_task("task_123")

        assert result["task"]["id"] == "task_123"
        assert result["task"]["status"] == "cancelled"

    def test_refunded_value_is_correct(self, mocker: Any) -> None:
        """result['refunded'] should match the value from the server."""
        mock_payload = {
            "task": {"id": "task_123", "status": "cancelled"},
            "refunded": 8.00,
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.cancel_task("task_123")

        assert result["refunded"] == 8.00

    def test_result_does_not_have_top_level_status(self, mocker: Any) -> None:
        """The result itself should not have a top-level 'status' key (it lives on result['task'])."""
        mock_payload = {
            "task": {"id": "task_123", "status": "cancelled"},
            "refunded": 8.00,
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.cancel_task("task_123")

        assert "status" not in result
        assert result["task"]["status"] == "cancelled"

    def test_calls_correct_endpoint(self, mocker: Any) -> None:
        """cancel_task() should POST to /api/tasks/{id}/cancel."""
        mock_payload = {
            "task": {"id": "task_123", "status": "cancelled"},
            "refunded": 8.00,
        }
        mock_urlopen = _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.cancel_task("task_123")

        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        assert "/api/tasks/task_123/cancel" in req.full_url
        assert req.method == "POST"


# ─── approve_task ─────────────────────────────────────────────────────────────

class TestApproveTask:
    """Tests for GetterDone.approve_task()."""

    def test_returns_task_and_payout_keys(self, mocker: Any) -> None:
        """approve_task() should return a dict with 'task' and 'payout' keys."""
        mock_payload = {
            "task": {
                "id": "task_123",
                "status": "completed",
                "title": "Test Task",
                "reward": 8.00,
            },
            "payout": {"workerId": "worker_1", "amount": 8.00, "currency": "usd"},
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result: ApproveTaskResult = gd.approve_task("task_123")

        assert "task" in result
        assert "payout" in result

    def test_task_is_a_dict(self, mocker: Any) -> None:
        """result['task'] should be a dict (the updated Task object)."""
        mock_payload = {
            "task": {"id": "task_123", "status": "completed"},
            "payout": {"workerId": "worker_1", "amount": 8.00, "currency": "usd"},
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.approve_task("task_123")

        assert isinstance(result["task"], dict)
        assert result["task"]["id"] == "task_123"

    def test_payout_value_is_correct(self, mocker: Any) -> None:
        """result['payout'] should be a PayoutResult dict with amount, workerId, currency."""
        mock_payload = {
            "task": {"id": "task_123", "status": "completed"},
            "payout": {"workerId": "worker_1", "amount": 8.00, "currency": "usd"},
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.approve_task("task_123")

        assert isinstance(result["payout"], dict)
        assert result["payout"]["amount"] == 8.00
        assert result["payout"]["workerId"] == "worker_1"
        assert result["payout"]["currency"] == "usd"

    def test_task_status_is_completed(self, mocker: Any) -> None:
        """The task inside the result should have status 'completed'."""
        mock_payload = {
            "task": {"id": "task_123", "status": "completed"},
            "payout": {"workerId": "worker_1", "amount": 8.00, "currency": "usd"},
        }
        _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.approve_task("task_123")

        assert result["task"]["status"] == "completed"

    def test_calls_correct_endpoint(self, mocker: Any) -> None:
        """approve_task() should POST to /api/tasks/{id}/complete."""
        mock_payload = {
            "task": {"id": "task_123", "status": "completed"},
            "payout": {"workerId": "worker_1", "amount": 8.00, "currency": "usd"},
        }
        mock_urlopen = _make_urlopen_mock(mocker, mock_payload)
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.approve_task("task_123")

        req: urllib.request.Request = mock_urlopen.call_args[0][0]
        assert "/api/tasks/task_123/complete" in req.full_url
        assert req.method == "POST"
