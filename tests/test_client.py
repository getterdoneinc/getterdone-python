"""
Unit tests for the GetterDone Python SDK client.

Uses pytest-mock to patch urllib.request.urlopen so no real HTTP calls are made.
list_tasks() is an unauthenticated endpoint, so _get_token() is patched out
for all tests to avoid a second HTTP round-trip.
"""

import io
import json
import urllib.error
import urllib.parse
import urllib.request
from io import BytesIO
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from getterdone import GetterDone
from getterdone.exceptions import AgentNameTakenError, FundingRequiredError, InsufficientBalanceError, TaskStateError


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_urlopen_mock(mocker: Any, payload: Any) -> MagicMock:
    """Return a mock suitable for patching urllib.request.urlopen."""
    mock_resp = mocker.MagicMock()
    mock_resp.read.return_value = json.dumps({"data": payload}).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = mocker.MagicMock(return_value=False)
    return mocker.patch("urllib.request.urlopen", return_value=mock_resp)


def _get_request_url(mock_urlopen: MagicMock) -> str:
    """Extract the URL string from the Request object passed to urlopen."""
    call_args = mock_urlopen.call_args
    req: urllib.request.Request = call_args[0][0]
    return req.full_url


# ─── list_tasks ───────────────────────────────────────────────────────────────

class TestListTasks:
    """Tests for GetterDone.list_tasks()."""

    def _make_client(self) -> GetterDone:
        return GetterDone(api_key="gd_testid:testsecret", base_url="https://test.example")

    def test_forwards_agent_id_as_query_param(self, mocker: Any) -> None:
        """agent_id should be forwarded as agentId in the query string."""
        mock_urlopen = _make_urlopen_mock(mocker, [])
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.list_tasks(agent_id="agent-abc", status="open")

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs.get("agentId") == ["agent-abc"]
        assert qs.get("status") == ["open"]

    def test_omits_agent_id_when_not_provided(self, mocker: Any) -> None:
        """agentId should NOT appear in the query string when agent_id is not given."""
        mock_urlopen = _make_urlopen_mock(mocker, [])
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.list_tasks(status="open")

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        assert "agentId" not in qs

    def test_omits_agent_id_when_none(self, mocker: Any) -> None:
        """Explicit agent_id=None should also produce no agentId param."""
        mock_urlopen = _make_urlopen_mock(mocker, [])
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.list_tasks(agent_id=None)

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        assert "agentId" not in qs

    def test_includes_default_limit(self, mocker: Any) -> None:
        """limit=50 should always be present even with no other params."""
        mock_urlopen = _make_urlopen_mock(mocker, [])
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.list_tasks()

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs.get("limit") == ["50"]

    def test_combines_agent_id_with_q_and_status(self, mocker: Any) -> None:
        """agent_id, q, and status can all appear together for server-side scoping."""
        mock_urlopen = _make_urlopen_mock(mocker, [])
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.list_tasks(agent_id="agent-xyz", q="beta", status="completed")

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs.get("agentId") == ["agent-xyz"]
        assert qs.get("q") == ["beta"]
        assert qs.get("status") == ["completed"]


# ─── get_balance ──────────────────────────────────────────────────────────────

class TestGetBalance:
    """Tests for GetterDone.get_balance()."""

    def _make_client(self) -> GetterDone:
        return GetterDone(api_key="gd_testid:testsecret", base_url="https://test.example")

    def _full_balance_payload(self) -> Dict[str, Any]:
        return {
            "balance": 94.00,
            "pendingEscrow": 6.00,
            "currency": "USD",
            "name": "Test Agent",
            "tasksCreated": 12,
        }

    def test_returns_all_five_fields(self, mocker: Any) -> None:
        """get_balance() should return all 5 fields: balance, pendingEscrow, currency, name, tasksCreated."""
        _make_urlopen_mock(mocker, self._full_balance_payload())
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.get_balance()

        assert result["balance"] == 94.00
        assert result["pendingEscrow"] == 6.00
        assert result["currency"] == "USD"
        assert result["name"] == "Test Agent"
        assert result["tasksCreated"] == 12

    def test_hits_correct_endpoint(self, mocker: Any) -> None:
        """get_balance() should call GET /api/agents/balance."""
        mock_urlopen = _make_urlopen_mock(mocker, self._full_balance_payload())
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        gd.get_balance()

        url = _get_request_url(mock_urlopen)
        assert url == "https://test.example/api/agents/balance"

    def test_name_is_string(self, mocker: Any) -> None:
        """The name field should be a string."""
        _make_urlopen_mock(mocker, self._full_balance_payload())
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.get_balance()

        assert isinstance(result["name"], str)

    def test_tasks_created_is_integer(self, mocker: Any) -> None:
        """The tasksCreated field should be an integer."""
        _make_urlopen_mock(mocker, self._full_balance_payload())
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        result = gd.get_balance()

        assert isinstance(result["tasksCreated"], int)


# ─── 409 error dispatch ───────────────────────────────────────────────────────

def _make_http_error(mocker: Any, status: int, error_message: str) -> None:
    """Patch urlopen to raise an HTTPError with the given status and JSON error body."""
    body = json.dumps({"error": error_message}).encode("utf-8")
    http_error = urllib.error.HTTPError(
        url="https://test.example/api/tasks/task_123/cancel",
        code=status,
        msg=str(status),
        hdrs=None,  # type: ignore[arg-type]
        fp=BytesIO(body),
    )
    mocker.patch("urllib.request.urlopen", side_effect=http_error)


class TestErrorDispatch409:
    """Tests for context-aware 409 error dispatch."""

    def _make_client(self, mocker: Any) -> GetterDone:
        gd = GetterDone(api_key="gd_testid:testsecret", base_url="https://test.example")
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        return gd

    def test_cancel_task_409_with_cancel_message_raises_task_state_error(self, mocker: Any) -> None:
        """cancel_task 409 with 'Cannot cancel' message should raise TaskStateError."""
        _make_http_error(mocker, 409, "Cannot cancel a claimed task")
        gd = self._make_client(mocker)

        with pytest.raises(TaskStateError):
            gd.cancel_task("task_123")

    def test_cancel_task_409_with_cancel_message_does_not_raise_agent_name_taken(self, mocker: Any) -> None:
        """cancel_task 409 with cancel message must NOT be AgentNameTakenError."""
        _make_http_error(mocker, 409, "Cannot cancel a claimed task")
        gd = self._make_client(mocker)

        with pytest.raises(TaskStateError):
            gd.cancel_task("task_123")

        # Confirm it is strictly TaskStateError, not AgentNameTakenError
        try:
            gd.cancel_task("task_123")
        except TaskStateError:
            pass
        except AgentNameTakenError:
            pytest.fail("Should not raise AgentNameTakenError for cancel conflict")

    def test_409_with_name_conflict_message_raises_agent_name_taken_error(self, mocker: Any) -> None:
        """409 with 'Agent name already taken' message should raise AgentNameTakenError."""
        _make_http_error(mocker, 409, "Agent name already taken")
        gd = self._make_client(mocker)

        with pytest.raises(AgentNameTakenError):
            gd.cancel_task("task_123")

    def test_409_with_unknown_message_raises_task_state_error_as_safe_default(self, mocker: Any) -> None:
        """409 with an unrecognised message should raise TaskStateError as the safe default."""
        _make_http_error(mocker, 409, "Generic conflict")
        gd = self._make_client(mocker)

        with pytest.raises(TaskStateError):
            gd.cancel_task("task_123")


# ─── 402 error disambiguation ─────────────────────────────────────────────────
# The backend emits two distinct 402 semantics:
#   1. INSUFFICIENT_BALANCE_FUNDABLE — wallet is short, but an active funding
#      token is available; the agent should call fund_account() to draw from it.
#   2. FundingRequired — no active token; agent-owner must finish onboarding.
#
# The SDK previously disambiguated by string-matching "funding token" in the
# message, which misroutes new backends that include the phrase in the helpful
# balance-shortfall hint. These tests lock in structured-`code` routing and the
# legacy fallback so older backends keep working.


def _build_http_error(status: int, body: Dict[str, Any]) -> urllib.error.HTTPError:
    """Build a urllib HTTPError whose body is a JSON object, mimicking a 4xx response."""
    raw = json.dumps(body).encode("utf-8")
    return urllib.error.HTTPError(
        url="https://test.example/api/tasks",
        code=status,
        msg="Payment Required",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(raw),
    )


TASK_KWARGS: Dict[str, Any] = {
    "title": "Photograph storefront",
    "description": "Take a clear photo of the entrance sign and posted hours.",
    "reward": 22.0,
    "location": {"lat": 40.7128, "lng": -74.006, "label": "42 Main St, NYC"},
}


class TestCreateTask402Routing:
    """Tests for how 402 responses are translated into typed exceptions."""

    def _make_client(self) -> GetterDone:
        return GetterDone(api_key="gd_testid:testsecret", base_url="https://test.example")

    def test_code_insufficient_balance_fundable_routes_to_insufficient_balance(
        self, mocker: Any
    ) -> None:
        """`code: INSUFFICIENT_BALANCE_FUNDABLE` must route to InsufficientBalanceError,
        even though the message contains "funding token" that would legacy-match
        FundingRequiredError. needed/available/funding_token must all be populated."""
        err = _build_http_error(
            402,
            {
                "success": False,
                "error": (
                    "Insufficient balance: need $26.40, have $0.00. An active funding "
                    "token authorises up to $50.00 — call fund_account to draw from it "
                    "before creating the task."
                ),
                "code": "INSUFFICIENT_BALANCE_FUNDABLE",
                "needed": 26.40,
                "available": 0,
                "fundingToken": {"id": "gd_fund_kapqm3dt", "amountUsd": 50, "recurring": True},
            },
        )
        mocker.patch("urllib.request.urlopen", side_effect=err)
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        with pytest.raises(InsufficientBalanceError) as exc_info:
            gd.create_task(**TASK_KWARGS)

        exc = exc_info.value
        assert not isinstance(exc, FundingRequiredError)
        assert exc.needed == 26.40
        assert exc.available == 0
        assert exc.funding_token == {
            "id": "gd_fund_kapqm3dt",
            "amountUsd": 50,
            "recurring": True,
        }
        # Shortfall $26.40, capped by token limit $50 → $26.40
        assert exc.recommended_draw_amount() == pytest.approx(26.40)

    def test_recommended_draw_amount_clamps_to_token_limit(self, mocker: Any) -> None:
        """When shortfall exceeds the token's amountUsd, the recommendation is
        clamped to the token limit."""
        err = _build_http_error(
            402,
            {
                "success": False,
                "error": "Insufficient balance: need $80.00, have $10.00. An active funding token authorises up to $50.00 — call fund_account to draw from it before creating the task.",
                "code": "INSUFFICIENT_BALANCE_FUNDABLE",
                "needed": 80,
                "available": 10,
                "fundingToken": {"id": "gd_fund_abc", "amountUsd": 50, "recurring": True},
            },
        )
        mocker.patch("urllib.request.urlopen", side_effect=err)
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        with pytest.raises(InsufficientBalanceError) as exc_info:
            gd.create_task(**{**TASK_KWARGS, "reward": 75.0})

        # Shortfall $70, capped by token limit $50
        assert exc_info.value.recommended_draw_amount() == 50

    def test_legacy_funding_string_match_still_raises_funding_required(
        self, mocker: Any
    ) -> None:
        """Older backends without `code` should still get FundingRequiredError
        when the message contains "funding token" (backward compat)."""
        err = _build_http_error(
            402,
            {
                "success": False,
                "error": "No active funding token found. Complete AgentOwner setup to fund this agent.",
                "onboardingUrl": "https://getterdone.ai/agent-owner",
            },
        )
        mocker.patch("urllib.request.urlopen", side_effect=err)
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        with pytest.raises(FundingRequiredError) as exc_info:
            gd.create_task(**TASK_KWARGS)

        assert exc_info.value.onboarding_url == "https://getterdone.ai/agent-owner"

    def test_plain_insufficient_balance_surfaces_needed_and_available(
        self, mocker: Any
    ) -> None:
        """A bare 402 (no token) should still surface needed/available so
        callers don't need to parse the error string."""
        err = _build_http_error(
            402,
            {
                "success": False,
                "error": "Insufficient balance: need $26.40, have $0.00",
                "needed": 26.40,
                "available": 0,
            },
        )
        mocker.patch("urllib.request.urlopen", side_effect=err)
        gd = self._make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        with pytest.raises(InsufficientBalanceError) as exc_info:
            gd.create_task(**TASK_KWARGS)

        exc = exc_info.value
        assert exc.needed == 26.40
        assert exc.available == 0
        assert exc.funding_token is None
        assert exc.recommended_draw_amount() is None
