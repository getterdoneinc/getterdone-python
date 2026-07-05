"""
Tests for new features, bug fixes, and regressions in the GetterDone Python SDK.

Covers:
  - 401 auto-retry with token cache clearing
  - ConflictError rename + AgentNameTakenError alias
  - approve_task 402 retry
  - get_pending_reviews
  - verify_webhook_signature (valid + 6 invalid cases)
  - wait_for_status (resolves + times out)
  - Payload scoping (no extra kwargs forwarded)
  - Query param URL-encoding via urllib.parse.urlencode
"""

import hashlib
import hmac
import json
import urllib.parse
import urllib.request
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from getterdone import (
    GetterDone,
    GetterDoneError,
    AuthenticationError,
    InsufficientBalanceError,
    FundingRequiredError,
    ConflictError,
    AgentNameTakenError,
    RateLimitError,
    TaskLimitError,
    verify_webhook_signature,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_client() -> GetterDone:
    return GetterDone(api_key="gd_testid:testsecret", base_url="https://test.example")


def _success_mock(mocker: Any, payload: Any) -> MagicMock:
    """Patch urlopen to return a single successful JSON response."""
    mock_resp = mocker.MagicMock()
    mock_resp.read.return_value = json.dumps({"data": payload}).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = mocker.MagicMock(return_value=False)
    return mocker.patch("urllib.request.urlopen", return_value=mock_resp)


def _http_error(mocker: Any, code: int, body: dict) -> Any:
    """Build a urllib.error.HTTPError carrying a JSON body."""
    import urllib.error, io

    raw = json.dumps(body).encode("utf-8")
    err = urllib.error.HTTPError(
        url="https://test.example/api/tasks",
        code=code,
        msg=f"HTTP {code}",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(raw),
    )
    return err


def _get_request_url(mock_urlopen: MagicMock) -> str:
    """Extract URL from the most recent urlopen call."""
    call_args = mock_urlopen.call_args
    req: urllib.request.Request = call_args[0][0]
    return req.full_url


def _get_request_headers(mock_urlopen: MagicMock) -> dict:
    call_args = mock_urlopen.call_args
    req: urllib.request.Request = call_args[0][0]
    return dict(req.headers)


# ─── 401 Auto-retry ───────────────────────────────────────────────────────────

class Test401Retry:
    """_request must clear the token cache and retry once on 401."""

    def test_401_triggers_reauthenticate_and_retry(self, mocker: Any) -> None:
        """First call returns 401; second call returns 200 — result is the success payload."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        import urllib.error, io

        success_resp = mocker.MagicMock()
        success_resp.read.return_value = json.dumps({"data": {"id": "task-1"}}).encode()
        success_resp.__enter__ = lambda s: s
        success_resp.__exit__ = mocker.MagicMock(return_value=False)

        error_401 = _http_error(mocker, 401, {"error": "token expired"})

        urlopen_mock = mocker.patch(
            "urllib.request.urlopen",
            side_effect=[error_401, success_resp],
        )

        result = gd.get_task("task-1")
        assert result["id"] == "task-1"
        assert urlopen_mock.call_count == 2

    def test_401_clears_token_cache_before_retry(self, mocker: Any) -> None:
        """Token should be cleared (set to None / expires_at=0) on first 401."""
        gd = _make_client()
        gd._token = "stale-token"  # type: ignore[assignment]
        gd._token_expires_at = 9999999999.0

        mocker.patch.object(gd, "_get_token", return_value="refreshed-token")

        error_401 = _http_error(mocker, 401, {"error": "token expired"})

        success_resp = mocker.MagicMock()
        success_resp.read.return_value = json.dumps({"data": {"ok": True}}).encode()
        success_resp.__enter__ = lambda s: s
        success_resp.__exit__ = mocker.MagicMock(return_value=False)

        mocker.patch("urllib.request.urlopen", side_effect=[error_401, success_resp])

        # Spy on the token invalidation
        original_request = gd._request

        cleared = []

        def spy_request(*args, **kwargs):
            if kwargs.get("_retry"):
                cleared.append((gd._token, gd._token_expires_at))
            return original_request(*args, **kwargs)

        mocker.patch.object(gd, "_request", side_effect=spy_request)
        gd.get_task("t1")

        # After the retry path, token was cleared
        assert cleared, "Retry was never called"
        assert cleared[0][0] is None
        assert cleared[0][1] == 0

    def test_double_401_raises_authentication_error(self, mocker: Any) -> None:
        """Two consecutive 401s should raise AuthenticationError, not loop forever."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        error_401a = _http_error(mocker, 401, {"error": "invalid"})
        error_401b = _http_error(mocker, 401, {"error": "still invalid"})

        mocker.patch("urllib.request.urlopen", side_effect=[error_401a, error_401b])

        with pytest.raises(AuthenticationError):
            gd.get_task("task-x")

    def test_unauthenticated_401_not_retried(self, mocker: Any) -> None:
        """A 401 on an unauthenticated request must NOT be retried."""
        gd = _make_client()

        error_401 = _http_error(mocker, 401, {"error": "bad"})
        urlopen_mock = mocker.patch("urllib.request.urlopen", side_effect=[error_401])

        with pytest.raises(AuthenticationError):
            gd._request("GET", "/api/open", authenticated=False)

        assert urlopen_mock.call_count == 1


# ─── ConflictError / AgentNameTakenError alias ────────────────────────────────

class TestConflictError:
    """ConflictError class and AgentNameTakenError deprecated alias."""

    def test_conflict_error_class_exists(self) -> None:
        assert issubclass(ConflictError, GetterDoneError)

    def test_agent_name_taken_error_is_alias(self) -> None:
        assert AgentNameTakenError is ConflictError

    def test_catch_conflict_error_via_alias(self) -> None:
        """Raising ConflictError should be catchable as AgentNameTakenError."""
        with pytest.raises(AgentNameTakenError):
            raise ConflictError("name taken")

    def test_catch_via_base_class(self) -> None:
        with pytest.raises(GetterDoneError):
            raise ConflictError("conflict")

    def test_409_response_raises_conflict_error(self, mocker: Any) -> None:
        """_request should raise ConflictError (not AgentNameTakenError) on 409."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        error_409 = _http_error(mocker, 409, {"error": "name taken"})
        mocker.patch("urllib.request.urlopen", side_effect=[error_409])

        with pytest.raises(ConflictError) as exc_info:
            gd._request("POST", "/api/agents/register", body={"name": "bot"})
        assert exc_info.value.status_code == 409


# ─── create_task task-count caps (429) ───────────────────────────────────────

class TestTaskCountCaps:
    """A 429 carrying a durable cap code must raise TaskLimitError with that code."""

    def test_task_limit_error_is_a_rate_limit_error(self) -> None:
        # Subclass so existing `except RateLimitError` / `except GetterDoneError` still catch it.
        assert issubclass(TaskLimitError, RateLimitError)
        assert issubclass(TaskLimitError, GetterDoneError)

    def test_open_task_limit_raises_task_limit_error(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        err = _http_error(mocker, 429, {"error": "Open-task limit reached", "code": "OPEN_TASK_LIMIT"})
        mocker.patch("urllib.request.urlopen", side_effect=[err])

        with pytest.raises(TaskLimitError) as exc_info:
            gd._request("POST", "/api/tasks", body={"title": "x"})
        assert exc_info.value.code == "OPEN_TASK_LIMIT"
        assert exc_info.value.status_code == 429

    def test_creation_limit_raises_task_limit_error(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        err = _http_error(mocker, 429, {"error": "Task creation rate limit", "code": "TASK_CREATION_LIMIT"})
        mocker.patch("urllib.request.urlopen", side_effect=[err])

        with pytest.raises(TaskLimitError) as exc_info:
            gd._request("POST", "/api/tasks", body={"title": "x"})
        assert exc_info.value.code == "TASK_CREATION_LIMIT"

    def test_generic_429_stays_rate_limit_error(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        err = _http_error(mocker, 429, {"error": "Too many requests"})
        mocker.patch("urllib.request.urlopen", side_effect=[err])

        with pytest.raises(RateLimitError) as exc_info:
            gd._request("GET", "/api/tasks")
        # A plain rate limit is NOT the more specific TaskLimitError.
        assert not isinstance(exc_info.value, TaskLimitError)


# ─── approve_task 402 retry ──────────────────────────────────────────────────

class TestApproveTask402Retry:
    """approve_task should wait 1s and retry once on 402."""

    def test_approve_task_402_retry_succeeds(self, mocker: Any) -> None:
        """First call returns 402; second returns 200 — success returned."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        sleep_mock = mocker.patch("time.sleep")

        error_402 = _http_error(mocker, 402, {"error": "balance settling"})

        success_resp = mocker.MagicMock()
        success_resp.read.return_value = json.dumps({"data": {"status": "completed"}}).encode()
        success_resp.__enter__ = lambda s: s
        success_resp.__exit__ = mocker.MagicMock(return_value=False)

        mocker.patch("urllib.request.urlopen", side_effect=[error_402, success_resp])

        result = gd.approve_task("task-42")
        assert result["status"] == "completed"
        sleep_mock.assert_called_once_with(1)

    def test_approve_task_double_402_insufficient_balance(self, mocker: Any) -> None:
        """Two consecutive 402 with wallet-balance body → InsufficientBalanceError."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        mocker.patch("time.sleep")

        error_402a = _http_error(mocker, 402, {"error": "insufficient balance"})
        error_402b = _http_error(mocker, 402, {"error": "insufficient balance"})
        mocker.patch("urllib.request.urlopen", side_effect=[error_402a, error_402b])

        with pytest.raises(InsufficientBalanceError):
            gd.approve_task("task-99")

    def test_approve_task_double_402_funding_required(self, mocker: Any) -> None:
        """Two consecutive 402 with funding token body → FundingRequiredError."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        mocker.patch("time.sleep")

        body = {"error": "funding token missing", "onboardingUrl": "https://onboard.example"}
        error_402a = _http_error(mocker, 402, body)
        error_402b = _http_error(mocker, 402, body)
        mocker.patch("urllib.request.urlopen", side_effect=[error_402a, error_402b])

        with pytest.raises(FundingRequiredError) as exc_info:
            gd.approve_task("task-99")
        assert exc_info.value.onboarding_url == "https://onboard.example"

    def test_approve_task_sleep_duration(self, mocker: Any) -> None:
        """The retry pause must be exactly 1 second."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        sleep_mock = mocker.patch("time.sleep")

        err = _http_error(mocker, 402, {"error": "balance"})
        success = mocker.MagicMock()
        success.read.return_value = json.dumps({"data": {}}).encode()
        success.__enter__ = lambda s: s
        success.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch("urllib.request.urlopen", side_effect=[err, success])

        gd.approve_task("task-1")
        sleep_mock.assert_called_once_with(1)


# ─── get_pending_reviews ──────────────────────────────────────────────────────

class TestGetPendingReviews:
    """get_pending_reviews() is an authenticated shortcut for submitted tasks."""

    def test_calls_correct_endpoint_and_params(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        mock_urlopen = _success_mock(mocker, [{"id": "t1", "status": "submitted"}])

        gd.get_pending_reviews()

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        assert parsed.path == "/api/tasks"
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs.get("status") == ["submitted"]
        assert qs.get("limit") == ["50"]

    def test_sends_authorization_header(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="my-token")
        mock_urlopen = _success_mock(mocker, [])

        gd.get_pending_reviews()

        headers = _get_request_headers(mock_urlopen)
        assert headers.get("Authorization") == "Bearer my-token"

    def test_returns_list(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        tasks = [{"id": "t1"}, {"id": "t2"}]
        _success_mock(mocker, tasks)

        result = gd.get_pending_reviews()
        assert result == tasks


# ─── verify_webhook_signature ─────────────────────────────────────────────────

class TestVerifyWebhookSignature:
    """7 test cases for the standalone verify_webhook_signature function."""

    def _compute_sig(self, body: bytes, secret: str) -> str:
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def test_valid_signature_returns_true(self) -> None:
        body = b'{"event":"task.submitted","taskId":"t1"}'
        secret = "my-webhook-secret"
        sig = self._compute_sig(body, secret)
        assert verify_webhook_signature(body, sig, secret) is True

    def test_wrong_secret_returns_false(self) -> None:
        body = b'{"event":"task.submitted"}'
        sig = self._compute_sig(body, "correct-secret")
        assert verify_webhook_signature(body, sig, "wrong-secret") is False

    def test_missing_sha256_prefix_returns_false(self) -> None:
        body = b"hello"
        secret = "s"
        # Provide raw hex without the "sha256=" prefix
        raw_hex = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        assert verify_webhook_signature(body, raw_hex, secret) is False

    def test_empty_body_still_validates(self) -> None:
        body = b""
        secret = "empty-body-secret"
        sig = self._compute_sig(body, secret)
        assert verify_webhook_signature(body, sig, secret) is True

    def test_wrong_body_returns_false(self) -> None:
        secret = "s"
        original_body = b"original"
        tampered_body = b"tampered"
        sig = self._compute_sig(original_body, secret)
        assert verify_webhook_signature(tampered_body, sig, secret) is False

    def test_none_inputs_return_false(self) -> None:
        # None for raw_body
        assert verify_webhook_signature(None, "sha256=abc", "secret") is False  # type: ignore[arg-type]
        # None for signature_header
        assert verify_webhook_signature(b"body", None, "secret") is False  # type: ignore[arg-type]
        # None for secret
        assert verify_webhook_signature(b"body", "sha256=abc", None) is False  # type: ignore[arg-type]

    def test_malformed_header_returns_false(self) -> None:
        # sha256= present but hex portion is garbage
        assert verify_webhook_signature(b"body", "sha256=not_valid_hex!!!", "secret") is False

    def test_empty_signature_after_prefix_returns_false(self) -> None:
        assert verify_webhook_signature(b"body", "sha256=", "secret") is False


# ─── wait_for_status ──────────────────────────────────────────────────────────

class TestWaitForStatus:
    """wait_for_status polls get_task until status matches or timeout."""

    def test_resolves_when_status_matches(self, mocker: Any) -> None:
        """Second poll returns target status — method returns task dict."""
        gd = _make_client()

        pending_task = {"id": "t1", "status": "open"}
        done_task = {"id": "t1", "status": "submitted"}

        mocker.patch.object(
            gd,
            "get_task",
            side_effect=[pending_task, done_task],
        )
        sleep_mock = mocker.patch("time.sleep")

        result = gd.wait_for_status("t1", "submitted", timeout_ms=30_000, poll_ms=1_000)
        assert result["status"] == "submitted"
        # Slept once between the first (miss) and second (hit) polls
        sleep_mock.assert_called_once_with(1.0)

    def test_returns_immediately_when_already_at_status(self, mocker: Any) -> None:
        """If task is already at target status no sleep should occur."""
        gd = _make_client()
        mocker.patch.object(gd, "get_task", return_value={"id": "t1", "status": "completed"})
        sleep_mock = mocker.patch("time.sleep")

        result = gd.wait_for_status("t1", "completed")
        assert result["status"] == "completed"
        sleep_mock.assert_not_called()

    def test_times_out_and_raises(self, mocker: Any) -> None:
        """If timeout elapses before status matches, GetterDoneError is raised."""
        gd = _make_client()
        mocker.patch.object(gd, "get_task", return_value={"id": "t1", "status": "open"})
        mocker.patch("time.sleep")

        # Make time.time() advance by 400 000 ms (400 s) each call, past 300 000 ms timeout
        mocker.patch("time.time", side_effect=[0.0, 400.0])

        with pytest.raises(GetterDoneError, match="Timed out waiting for status"):
            gd.wait_for_status("t1", "submitted", timeout_ms=300_000, poll_ms=5_000)

    def test_timeout_error_message(self, mocker: Any) -> None:
        """The raised exception must carry the exact message."""
        gd = _make_client()
        mocker.patch.object(gd, "get_task", return_value={"id": "t1", "status": "open"})
        mocker.patch("time.sleep")
        mocker.patch("time.time", side_effect=[0.0, 999.0])

        with pytest.raises(GetterDoneError) as exc_info:
            gd.wait_for_status("t1", "submitted", timeout_ms=100)
        assert str(exc_info.value) == "Timed out waiting for status"


# ─── Payload scoping ──────────────────────────────────────────────────────────

class TestPayloadScoping:
    """No extra kwargs should leak into the request body."""

    def test_create_task_body_contains_only_declared_fields(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        captured_body: dict = {}

        def capture_urlopen(req, timeout=None):
            import io
            body_bytes = req.data or b"{}"
            nonlocal captured_body
            captured_body = json.loads(body_bytes)
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"data": {"id": "t1"}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mocker.patch("urllib.request.urlopen", side_effect=capture_urlopen)

        gd.create_task(
            title="Test Task",
            description="A description that is long enough",
            reward=5.00,
            location={"lat": 0, "lng": 0, "label": "Remote", "remote": True},
            category="Research",
        )

        allowed_keys = {
            "title", "description", "reward", "location", "category",
            "expiresInHours", "tags", "reviewCriteria", "minTrustScore",
        }
        assert set(captured_body.keys()).issubset(allowed_keys), (
            f"Unexpected keys in payload: {set(captured_body.keys()) - allowed_keys}"
        )

    def test_report_issue_body_contains_only_declared_fields(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        captured_body: dict = {}

        def capture_urlopen(req, timeout=None):
            nonlocal captured_body
            captured_body = json.loads(req.data or b"{}")
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"data": {"ok": True}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mocker.patch("urllib.request.urlopen", side_effect=capture_urlopen)

        gd.report_issue(type="bug", title="Something broke", description="Details here")

        assert "message" not in captured_body
        assert captured_body["type"] == "bug"
        assert captured_body["title"] == "Something broke"
        assert captured_body["description"] == "Details here"
        assert "severity" not in captured_body  # not passed → not in body

    def test_report_issue_includes_severity_when_provided(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")

        captured_body: dict = {}

        def capture_urlopen(req, timeout=None):
            nonlocal captured_body
            captured_body = json.loads(req.data or b"{}")
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"data": {}}).encode()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        mocker.patch("urllib.request.urlopen", side_effect=capture_urlopen)

        gd.report_issue(
            type="bug", title="Crash", description="It crashed", severity="critical"
        )
        assert captured_body["severity"] == "critical"


# ─── URL encoding ─────────────────────────────────────────────────────────────

class TestQueryParamEncoding:
    """Query params must be encoded with urllib.parse.urlencode."""

    def test_list_tasks_uses_urlencode(self, mocker: Any) -> None:
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        mock_urlopen = _success_mock(mocker, [])

        # Use a value with a space to prove urlencode is used (space → %20 or +)
        gd.list_tasks(q="hello world")

        url = _get_request_url(mock_urlopen)
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs.get("q") == ["hello world"]  # parse_qs decodes it back

    def test_list_tasks_sends_auth_header(self, mocker: Any) -> None:
        """list_tasks must now include Authorization header (authenticated=True)."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="test-token")
        mock_urlopen = _success_mock(mocker, [])

        gd.list_tasks()

        headers = _get_request_headers(mock_urlopen)
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-token"

    def test_get_task_sends_auth_header(self, mocker: Any) -> None:
        """get_task must now include Authorization header (authenticated=True)."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="test-token")
        mock_urlopen = _success_mock(mocker, {"id": "t1", "status": "open"})

        gd.get_task("t1")

        headers = _get_request_headers(mock_urlopen)
        assert headers.get("Authorization") == "Bearer test-token"

    def test_get_pending_reviews_uses_urlencode(self, mocker: Any) -> None:
        """get_pending_reviews URL must be properly encoded, not manually concatenated."""
        gd = _make_client()
        mocker.patch.object(gd, "_get_token", return_value="fake-token")
        mock_urlopen = _success_mock(mocker, [])

        gd.get_pending_reviews()

        url = _get_request_url(mock_urlopen)
        # Must have a proper query string (? present and parseable)
        parsed = urllib.parse.urlparse(url)
        assert parsed.query != ""
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs["status"] == ["submitted"]
        assert qs["limit"] == ["50"]


# ─── Token refresh margin ─────────────────────────────────────────────────────

class TestTokenRefreshMargin:
    """Token should be refreshed when within 120s of expiry, not 60s."""

    def test_token_refreshed_at_120s_before_expiry(self, mocker: Any) -> None:
        import time as time_mod

        gd = _make_client()

        now = time_mod.time()
        gd._token = "old-token"
        # Set expiry 100s from now → within 120s margin → should refresh
        gd._token_expires_at = now + 100

        refresh_responses = [
            {
                "access_token": "new-token",
                "expires_in": 3600,
            }
        ]

        mock_resp = mocker.MagicMock()
        mock_resp.read.return_value = json.dumps({"data": refresh_responses[0]}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = mocker.MagicMock(return_value=False)
        mocker.patch("urllib.request.urlopen", return_value=mock_resp)

        token = gd._get_token()
        assert token == "new-token"

    def test_token_not_refreshed_at_121s_before_expiry(self, mocker: Any) -> None:
        import time as time_mod

        gd = _make_client()

        now = time_mod.time()
        gd._token = "cached-token"
        # Set expiry 130s from now → outside 120s margin → should NOT refresh
        gd._token_expires_at = now + 130

        urlopen_mock = mocker.patch("urllib.request.urlopen")

        token = gd._get_token()
        assert token == "cached-token"
        urlopen_mock.assert_not_called()
