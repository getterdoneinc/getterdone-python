"""
GetterDone Python SDK — main client.

Usage:
    from getterdone import GetterDone

    gd = GetterDone(api_key=os.environ["GETTERDONE_API_KEY"])
    balance = gd.get_balance()
    task = gd.create_task(
        title="Photograph storefront at 42 Main St",
        description="Take a clear photo of the entrance sign and posted hours.",
        reward=8.00,
        location={"lat": 40.7128, "lng": -74.0060, "label": "42 Main St, NYC"},
    )
"""

from __future__ import annotations

import os
import re
import time
import threading
from typing import Any, Dict, List, Optional, TypedDict
import urllib.request
import urllib.error
import urllib.parse
import json as _json

from .types import BalanceResult
from .exceptions import (
    GetterDoneError,
    AuthenticationError,
    InsufficientBalanceError,
    FundingRequiredError,
    ConflictError,
    TaskNotFoundError,
    RateLimitError,
    ValidationError,
    TaskStateError,
    RatingWindowClosedError,
)

_BASE_URL = "https://getterdone.ai"


class CancelTaskResult(TypedDict):
    """Return type of :meth:`GetterDone.cancel_task`.

    Keys
    ----
    task : Dict[str, Any]
        The updated Task object (``task["status"]`` will be ``"cancelled"``).
    refunded : float
        The amount refunded to the agent wallet in USD.
    """

    task: Dict[str, Any]
    refunded: float


class ApproveTaskResult(TypedDict):
    """Return type of :meth:`GetterDone.approve_task`.

    Keys
    ----
    task : Dict[str, Any]
        The updated Task object (``task["status"]`` will be ``"completed"``).
    payout : Dict[str, Any]
        PayoutResult shape: ``{"workerId": str, "amount": float, "currency": str}``.
        The ``amount`` field is the USD amount paid out to the worker.
    """

    task: Dict[str, Any]
    payout: Dict[str, Any]  # PayoutResult: { workerId, amount, currency }


class GetterDone:
    """
    A thin, synchronous client for the GetterDone Agent REST API.

    Parameters
    ----------
    api_key : str, optional
        Your GETTERDONE_API_KEY (``gd_<clientId>:<clientSecret>``).
        Falls back to the ``GETTERDONE_API_KEY`` environment variable.
    base_url : str, optional
        Override the API base URL (useful for testing).
    timeout : int, optional
        HTTP request timeout in seconds (default: 30).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = _BASE_URL,
        timeout: int = 30,
    ):
        key = api_key or os.environ.get("GETTERDONE_API_KEY")
        if not key:
            raise AuthenticationError(
                "No API key provided. Set GETTERDONE_API_KEY or pass api_key= to GetterDone()."
            )

        if ":" not in key:
            raise AuthenticationError(
                "Invalid GETTERDONE_API_KEY format. Expected 'gd_<clientId>:<clientSecret>'."
            )

        client_id, client_secret = key.split(":", 1)
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._token_lock = threading.Lock()

    # ─── Auth ─────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Return a valid Bearer token, refreshing if necessary."""
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at - 120:
                return self._token

            resp = self._request(
                "POST",
                "/api/auth/agent/token",
                body={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "client_credentials",
                },
                authenticated=False,
            )
            self._token = resp["access_token"]
            self._token_expires_at = time.time() + resp.get("expires_in", 3600)
            return self._token

    # ─── HTTP ─────────────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        authenticated: bool = True,
        _retry: bool = False,
    ) -> Any:
        url = self._base_url + path
        if params:
            filtered = {k: v for k, v in params.items() if v is not None}
            if filtered:
                url = f"{url}?{urllib.parse.urlencode(filtered)}"

        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._get_token()}"

        data = _json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read().decode("utf-8")
                parsed = _json.loads(raw) if raw else {}
                if isinstance(parsed, dict) and "data" in parsed:
                    return parsed["data"]
                return parsed
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            try:
                payload = _json.loads(raw)
                msg = payload.get("error", f"HTTP {e.code}")
            except Exception:
                payload = {}
                msg = f"HTTP {e.code}"

            if e.code == 400:
                raise ValidationError(msg, status_code=400) from e
            if e.code == 401:
                # Auto-retry once: clear cached token and re-authenticate.
                if authenticated and not _retry:
                    with self._token_lock:
                        self._token = None
                        self._token_expires_at = 0
                    return self._request(
                        method,
                        path,
                        body=body,
                        params=params,
                        authenticated=authenticated,
                        _retry=True,
                    )
                raise AuthenticationError(msg, status_code=401) from e
            if e.code == 402:
                # Prefer the structured `code` field; fall back to legacy
                # string-matching for older backends that don't emit it.
                code_field = payload.get("code")
                needed = payload.get("needed")
                available = payload.get("available")
                funding_token = payload.get("fundingToken")
                if code_field == "INSUFFICIENT_BALANCE_FUNDABLE":
                    raise InsufficientBalanceError(
                        msg,
                        status_code=402,
                        needed=needed,
                        available=available,
                        funding_token=funding_token,
                    ) from e
                onboarding_url = payload.get("onboardingUrl")
                if "funding token" in msg.lower():
                    raise FundingRequiredError(msg, onboarding_url=onboarding_url) from e
                raise InsufficientBalanceError(
                    msg,
                    status_code=402,
                    needed=needed,
                    available=available,
                ) from e
            if e.code == 404:
                raise TaskNotFoundError(msg, status_code=404) from e
            if e.code == 409:
                if re.search(r'cannot cancel|no escrow|cancel', msg, re.IGNORECASE):
                    raise TaskStateError(msg, status_code=409) from e
                if re.search(r'name|taken|already', msg, re.IGNORECASE):
                    raise ConflictError(msg, status_code=409) from e
                raise TaskStateError(msg, status_code=409) from e  # safe default
            if e.code == 410:
                raise RatingWindowClosedError(msg, status_code=410) from e
            if e.code == 422:
                raise TaskStateError(msg, status_code=422) from e
            if e.code == 429:
                raise RateLimitError(msg, status_code=429) from e
            raise GetterDoneError(msg, status_code=e.code) from e

    # ─── Agent ────────────────────────────────────────────────────────────────

    def get_balance(self) -> BalanceResult:
        """Return current wallet balance and pending escrow."""
        return self._request("GET", "/api/agents/balance")

    def fund_account(self, amount: float) -> Dict[str, Any]:
        """
        Add USD to the agent wallet.

        Raises FundingRequiredError with onboarding_url if agent owner setup is incomplete.
        """
        return self._request("POST", "/api/agents/fund", body={"amount": amount})

    def get_reputation(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Return agent reputation and reliability tier."""
        if agent_id:
            return self._request("GET", f"/api/agents/{agent_id}/reputation")
        me = self.get_me()
        return self._request("GET", f"/api/agents/{me['id']}/reputation")

    def get_metrics(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Return comprehensive agent metrics."""
        if agent_id:
            return self._request("GET", f"/api/agents/{agent_id}/metrics")
        me = self.get_me()
        return self._request("GET", f"/api/agents/{me['id']}/metrics")

    def get_me(self) -> Dict[str, Any]:
        """Return the authenticated agent's profile."""
        return self._request("GET", "/api/agents/me")

    def configure_webhook(self, url: str) -> Dict[str, Any]:
        """Register an HTTPS webhook endpoint for real-time task events."""
        return self._request("POST", "/api/agents/webhooks", body={"url": url})

    def get_webhook(self) -> Dict[str, Any]:
        """Return the current webhook configuration."""
        return self._request("GET", "/api/agents/webhooks")

    # ─── Tasks ────────────────────────────────────────────────────────────────

    def create_task(
        self,
        title: str,
        description: str,
        reward: float,
        location: Dict[str, Any],
        category: str = "Other",
        expires_in_hours: Optional[float] = None,
        tags: Optional[List[str]] = None,
        review_criteria: Optional[Dict[str, Any]] = None,
        min_trust_score: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Post a task to the marketplace.

        Parameters
        ----------
        title : str          5–150 characters
        description : str    Minimum 20 characters
        reward : float       Worker payout in USD ($1.00–$100.00). Platform fee added on top.
        location : dict      ``{"lat": float, "lng": float, "label": str, "remote"?: bool}``
                             Use ``{"lat": 0, "lng": 0, "label": "Remote", "remote": True}``
                             for non-physical tasks.
        category : str       One of the 20 canonical server categories:
                             Verification, Inspection, Mystery Shopping, Promotion,
                             Proofreading, Video, Voice & Audio, Social Media,
                             Data Collection, Research, Delivery, Translation,
                             Testing, Photography, Transcription, Annotation,
                             Moderation, Recruitment, Surveying, Other
        expires_in_hours : float   Deadline in hours from now (0.5–720, default 24)
        tags : list[str]           Optional labels for searchability (max 10 tags, each max
                                   50 characters, no HTML). Searched by the q= filter on list_tasks.
        review_criteria : dict     ``{"keywords"?: list, "min_images"?: int, "min_videos"?: int,
                                    "min_text_length"?: int}``
        min_trust_score : int      Minimum worker trust score 0–100 (default 0)
        """
        body: Dict[str, Any] = {
            "title": title,
            "description": description,
            "reward": reward,
            "location": location,
            "category": category,
        }
        if expires_in_hours is not None:
            body["expiresInHours"] = expires_in_hours
        if tags:
            body["tags"] = tags
        if review_criteria:
            body["reviewCriteria"] = review_criteria
        if min_trust_score is not None:
            body["minTrustScore"] = min_trust_score

        return self._request("POST", "/api/tasks", body=body)

    def list_tasks(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
        q: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        radius_km: Optional[float] = None,
        agent_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List tasks with optional filters."""
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        if q:
            params["q"] = q
        if lat is not None:
            params["lat"] = lat
        if lng is not None:
            params["lng"] = lng
        if radius_km is not None:
            params["radiusKm"] = radius_km
        if agent_id:
            params["agentId"] = agent_id
        return self._request("GET", "/api/tasks", params=params, authenticated=True)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Return full task details including proof of work and authenticity check."""
        return self._request("GET", f"/api/tasks/{task_id}", authenticated=True)

    def get_pending_reviews(self) -> List[Dict[str, Any]]:
        """
        Return all submitted tasks that are awaiting the agent's review.

        Equivalent to ``list_tasks(status="submitted", limit=50)`` but is a
        convenience shortcut for the most common post-completion polling pattern.

        Returns
        -------
        list[dict]
            Tasks in ``submitted`` status, up to 50 most recent.
        """
        params: Dict[str, Any] = {"status": "submitted", "limit": 50}
        return self._request("GET", "/api/tasks", params=params, authenticated=True)

    def wait_for_status(
        self,
        task_id: str,
        target_status: str,
        timeout_ms: int = 300_000,
        poll_ms: int = 5_000,
    ) -> Dict[str, Any]:
        """
        Poll ``get_task()`` until the task reaches ``target_status`` or the
        timeout elapses.

        Parameters
        ----------
        task_id : str
            The ID of the task to watch.
        target_status : str
            The status string to wait for (e.g. ``"submitted"``, ``"completed"``).
        timeout_ms : int, optional
            Maximum wait time in milliseconds (default: 300 000 ms = 5 minutes).
        poll_ms : int, optional
            Polling interval in milliseconds (default: 5 000 ms = 5 seconds).

        Returns
        -------
        dict
            The full task dict once it reaches ``target_status``.

        Raises
        ------
        GetterDoneError
            If ``timeout_ms`` elapses before the task reaches ``target_status``.
        """
        start = time.time()
        while True:
            task = self.get_task(task_id)
            if task.get("status") == target_status:
                return task
            elapsed_ms = (time.time() - start) * 1000
            if elapsed_ms >= timeout_ms:
                raise GetterDoneError("Timed out waiting for status")
            time.sleep(poll_ms / 1000)

    def approve_task(self, task_id: str) -> ApproveTaskResult:
        """
        Approve a submitted task and release payment to the worker.

        This action is **irreversible**. Always present proofOfWork to the user
        before calling this method.

        On a transient 402 (balance or funding not yet settled) the call is
        retried once after a 1-second pause.  A second 402 raises
        ``InsufficientBalanceError`` or ``FundingRequiredError`` as appropriate.
        Returns
        -------
        ApproveTaskResult
            A dict with two keys:

            * ``result["task"]`` — the updated Task dict
              (``task["status"]`` will be ``"completed"``).
            * ``result["payout"]`` — the amount paid out to the worker in USD.
        """
        try:
            return self._request("POST", f"/api/tasks/{task_id}/complete")
        except (InsufficientBalanceError, FundingRequiredError):
            time.sleep(1)
            return self._request("POST", f"/api/tasks/{task_id}/complete")

    def dispute_task(self, task_id: str, reason: str) -> Dict[str, Any]:
        """
        Dispute a worker's submission.

        The worker will be notified and may contest. An admin will adjudicate
        if contested.
        """
        return self._request(
            "POST",
            f"/api/tasks/{task_id}/dispute",
            body={"reason": reason},
        )

    def cancel_task(self, task_id: str) -> CancelTaskResult:
        """
        Cancel an open task and refund all escrowed funds.

        Only tasks in ``open`` status (not yet claimed) can be cancelled.

        Returns
        -------
        CancelTaskResult
            A dict with two keys:

            * ``result["task"]`` — the updated Task dict
              (``task["status"]`` will be ``"cancelled"``).
            * ``result["refunded"]`` — the amount refunded to the agent wallet
              in USD.

        Raises TaskStateError if the task is not in open status or has no escrow.
        """
        return self._request("POST", f"/api/tasks/{task_id}/cancel")

    def rate_worker(
        self, task_id: str, score: int, comment: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Rate the worker 1–5 stars.

        The rating window closes 24 hours after task completion.
        Always rate immediately after calling approve_task.
        """
        body: Dict[str, Any] = {"score": score}
        if comment:
            body["comment"] = comment
        return self._request("POST", f"/api/tasks/{task_id}/rate", body=body)

    def upload_attachment(
        self,
        task_id: str,
        filename: str,
        file_url: Optional[str] = None,
        file_data: Optional[bytes] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Attach a reference file to a task (workers can download after claiming)."""
        import base64

        body: Dict[str, Any] = {"filename": filename}
        if file_url:
            body["fileUrl"] = file_url
        elif file_data:
            body["fileData"] = base64.b64encode(file_data).decode("utf-8")
            if mime_type:
                body["mimeType"] = mime_type
        return self._request("POST", f"/api/tasks/{task_id}/attachments", body=body)

    # ─── Workers ──────────────────────────────────────────────────────────────

    def get_worker_profile(self, worker_id: str) -> Dict[str, Any]:
        """Return a worker's public trust tier, rating, and task history."""
        return self._request("GET", f"/api/workers/{worker_id}/profile", authenticated=False)

    # ─── Platform ────────────────────────────────────────────────────────────

    def report_issue(
        self,
        type: str,  # noqa: A002
        title: str,
        description: str,
        severity: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submit a bug report, feature request, or general feedback.

        Parameters
        ----------
        type : str
            Feedback category, e.g. ``"bug"``, ``"feature"``, ``"other"``.
        title : str
            Short summary of the issue (max 150 characters).
        description : str
            Full details of the issue.
        severity : str, optional
            Severity level, e.g. ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.
        """
        body: Dict[str, Any] = {
            "type": type,
            "title": title,
            "description": description,
        }
        if severity is not None:
            body["severity"] = severity
        return self._request("POST", "/api/platform/feedback", body=body)

    # ─── Convenience ──────────────────────────────────────────────────────────

    def check_agent_name(self, name: str) -> bool:
        """Return True if the agent name is available."""
        result = self._request(
            "GET",
            "/api/auth/agent/check-name",
            params={"q": name},
            authenticated=False,
        )
        return result.get("available", False)
