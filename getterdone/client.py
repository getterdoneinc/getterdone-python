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
import time
import threading
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error
import json as _json

from .exceptions import (
    GetterDoneError,
    AuthenticationError,
    InsufficientBalanceError,
    FundingRequiredError,
    AgentNameTakenError,
    TaskNotFoundError,
    RateLimitError,
    ValidationError,
    TaskStateError,
    RatingWindowClosedError,
)

_BASE_URL = "https://getterdone.ai"


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
            if self._token and time.time() < self._token_expires_at - 60:
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
    ) -> Any:
        url = self._base_url + path
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
            url = f"{url}?{query}"

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
                msg = f"HTTP {e.code}"

            if e.code == 400:
                raise ValidationError(msg, status_code=400) from e
            if e.code == 401:
                raise AuthenticationError(msg, status_code=401) from e
            if e.code == 402:
                onboarding_url = payload.get("onboardingUrl") if "payload" in dir() else None
                if "funding token" in msg.lower():
                    raise FundingRequiredError(msg, onboarding_url=onboarding_url) from e
                raise InsufficientBalanceError(msg, status_code=402) from e
            if e.code == 404:
                raise TaskNotFoundError(msg, status_code=404) from e
            if e.code == 409:
                raise AgentNameTakenError(msg, status_code=409) from e
            if e.code == 410:
                raise RatingWindowClosedError(msg, status_code=410) from e
            if e.code == 422:
                raise TaskStateError(msg, status_code=422) from e
            if e.code == 429:
                raise RateLimitError(msg, status_code=429) from e
            raise GetterDoneError(msg, status_code=e.code) from e

    # ─── Agent ────────────────────────────────────────────────────────────────

    def get_balance(self) -> Dict[str, Any]:
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
        category: str = "General",
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
        category : str       One of: General, Research, Data Entry, Writing, Design,
                             Photography, Delivery, Shopping, Handyman, Errands,
                             Translation, Physical Task, Customer Service, Other
        expires_in_hours : float   Deadline in hours from now (0.5–720, default 24)
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
        return self._request("GET", "/api/tasks", params=params, authenticated=False)

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Return full task details including proof of work and authenticity check."""
        return self._request("GET", f"/api/tasks/{task_id}", authenticated=False)

    def approve_task(self, task_id: str) -> Dict[str, Any]:
        """
        Approve a submitted task and release payment to the worker.

        This action is **irreversible**. Always present proofOfWork to the user
        before calling this method.
        """
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

    def cancel_task(self, task_id: str) -> Dict[str, Any]:
        """
        Cancel an open task and refund all escrowed funds.

        Only tasks in ``open`` status (not yet claimed) can be canceled.
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
        message: str,
        issue_type: str = "other",
    ) -> Dict[str, Any]:
        """Submit a bug report or feature request to the platform team."""
        return self._request(
            "POST",
            "/api/platform/feedback",
            body={"type": issue_type, "message": message},
        )

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
