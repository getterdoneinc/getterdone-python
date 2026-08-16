"""
GetterDone Python SDK — main client.

Usage:
    from getterdone import GetterDone

    gd = GetterDone(api_key=os.environ["GETTERDONE_API_KEY"])
    task = gd.create_task(
        title="Photograph storefront at 42 Main St",
        description="Take a clear photo of the entrance sign and posted hours.",
        reward=8.00,
        location={"lat": 40.7128, "lng": -74.0060, "label": "42 Main St, NYC"},
    )
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import threading
from typing import Any, Dict, List, Optional, TypedDict
import urllib.request
import urllib.error
import urllib.parse
import json as _json

from ._version import __version__
from .types import BalanceResult, FundingStatus
from .exceptions import (
    GetterDoneError,
    AuthenticationError,
    InsufficientBalanceError,
    FundingRequiredError,
    ConflictError,
    TaskNotFoundError,
    RateLimitError,
    TaskLimitError,
    ValidationError,
    TaskStateError,
    RatingWindowClosedError,
)

_BASE_URL = "https://getterdone.ai"

# The API's reviewCriteria keys are camelCase. The SDK accepts snake_case too
# and normalizes, but any OTHER key is rejected loudly: the server silently
# drops unknown keys, which would disable that proof requirement without any
# error — a fail-open on a fraud control (DevX cell-5 finding).
_REVIEW_CRITERIA_KEYS = {
    "keywords": "keywords",
    "minImages": "minImages",
    "min_images": "minImages",
    "minVideos": "minVideos",
    "min_videos": "minVideos",
    "minTextLength": "minTextLength",
    "min_text_length": "minTextLength",
}


def _normalize_review_criteria(criteria: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in criteria.items():
        canonical = _REVIEW_CRITERIA_KEYS.get(key)
        if canonical is None:
            raise ValueError(
                f"Unknown review_criteria key {key!r}. Valid keys: keywords, "
                "minImages/min_images, minVideos/min_videos, minTextLength/min_text_length. "
                "(The server silently drops unknown keys, which would disable that "
                "proof requirement — refusing instead.)"
            )
        normalized[canonical] = value
    return normalized


def _solve_pow(nonce: str, difficulty_bits: int) -> str:
    """Solve the registration reverse-CAPTCHA.

    Finds a hex candidate such that SHA-256(nonce + candidate) has at least
    ``difficulty_bits`` leading zero bits. Difficulty 22 ≈ 4M hashes ≈ a few
    seconds in pure Python — bounded well under the challenge's 2-minute TTL.
    """
    full_bytes, rem_bits = divmod(difficulty_bits, 8)
    prefix = nonce.encode("utf-8")
    i = 0
    while True:
        candidate = format(i, "x")
        digest = hashlib.sha256(prefix + candidate.encode("ascii")).digest()
        if digest[:full_bytes] == b"\x00" * full_bytes and (
            rem_bits == 0 or (digest[full_bytes] >> (8 - rem_bits)) == 0
        ):
            return candidate
        i += 1


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
        # No credentials is a valid (limited) mode: unauthenticated calls like
        # check_agent_name() and the register() classmethod must work BEFORE an
        # agent has credentials (DevX cell-5: the pre-registration name check
        # was unreachable without a placeholder key). Authenticated calls raise
        # AuthenticationError at request time instead.
        if key is not None and ":" not in key:
            raise AuthenticationError(
                "Invalid GETTERDONE_API_KEY format. Expected 'gd_<clientId>:<clientSecret>'."
            )

        if key:
            client_id, client_secret = key.split(":", 1)
        else:
            client_id = client_secret = None
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
        if not self._client_id or not self._client_secret:
            raise AuthenticationError(
                "No API key provided. Set GETTERDONE_API_KEY or pass api_key= to GetterDone(). "
                "(Only unauthenticated calls like check_agent_name() and GetterDone.register() "
                "work without credentials.)"
            )
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

        # An explicit User-Agent is REQUIRED: without one, stdlib sends
        # "Python-urllib/3.x", which Cloudflare's browser-integrity rule blocks
        # with 403 error 1010 — every SDK call fails on a clean environment
        # (DevX cell-5 finding, verified by UA bisection against curl).
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": f"getterdone-python/{__version__}",
        }
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
                onboarding_url = payload.get("onboardingUrl")
                # Direct-charge (Path A): no active funding token / owner setup incomplete.
                if code_field == "NO_FUNDING_TOKEN":
                    raise FundingRequiredError(msg, onboarding_url=onboarding_url) from e
                # Legacy backends that pre-credited a wallet returned this code.
                if code_field == "INSUFFICIENT_BALANCE_FUNDABLE":
                    raise InsufficientBalanceError(
                        msg,
                        status_code=402,
                        needed=needed,
                        available=available,
                        funding_token=funding_token,
                    ) from e
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
                # Durable task-count caps carry a specific code; surface them as
                # TaskLimitError so callers can back off appropriately. A generic
                # request rate limit (no such code) stays a plain RateLimitError.
                code_field = payload.get("code")
                if code_field in ("OPEN_TASK_LIMIT", "TASK_CREATION_LIMIT"):
                    raise TaskLimitError(msg, code=code_field) from e
                raise RateLimitError(msg, status_code=429) from e
            raise GetterDoneError(msg, status_code=e.code) from e

    # ─── Agent ────────────────────────────────────────────────────────────────

    def get_balance(self) -> BalanceResult:
        """Return the legacy wallet balance (informational) and pending escrow."""
        return self._request("GET", "/api/agents/balance")

    def get_funding_status(self) -> FundingStatus:
        """Pre-flight readiness check before creating paid tasks.

        A successful call proves credentials are valid; ``ready: True`` means the
        Agent Owner setup is complete (KYC + vaulted card + active funding token)
        and ``create_task`` will not fail with 402 NO_FUNDING_TOKEN. When not
        ready, surface ``onboardingUrl`` to the owner. When ready, ``recurring``
        tells you whether you can keep posting without another human step (False =
        single-use, consumed by your next task) and ``perTaskLimitUsd`` is the
        token's per-task ceiling (``create_task`` fails if reward + fee exceeds it).
        """
        return self._request("GET", "/api/agents/funding-status")

    def fund_account(self, amount: float) -> Dict[str, Any]:
        """
        Deprecated no-op. Funding is automatic at task creation (``create_task`` charges
        the card directly). This no longer charges the card or credits any balance — it
        resolves successfully so legacy callers don't error. Call ``create_task`` instead.
        """
        return self._request("POST", "/api/agents/fund", body={"amount": amount})

    def get_reputation(self, agent_id: Optional[str] = None) -> Dict[str, Any]:
        """Return agent reputation and reliability tier. Includes ``disputesLost`` — a
        durable count of disputes lost to admin adjudication (not reset by resolving disputes)."""
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

    # ─── Event Inbox (RFC-001) ────────────────────────────────────────────────

    def get_events(
        self,
        cursor: Optional[int] = None,
        limit: Optional[int] = None,
        types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Poll the durable event inbox.

        Omit ``cursor`` to resume from the last acked cursor (unacked events
        re-appear — deduplicate on ``event["id"]``). Process the batch, then
        call :meth:`ack_events` with the returned ``nextCursor``. Events are
        thin envelopes — fetch fresh task state with :meth:`get_task`.
        A 410 means the cursor predates the 30-day retention window; resume
        from the ``oldestAvailableCursor`` in the error response.
        """
        params: Dict[str, Any] = {}
        if cursor is not None:
            params["cursor"] = cursor
        if limit is not None:
            params["limit"] = limit
        if types:
            params["types"] = ",".join(types)
        return self._request("GET", "/api/agents/events", params=params or None)

    def ack_events(self, cursor: int) -> Dict[str, Any]:
        """Acknowledge inbox events up to ``cursor`` (high-water mark).

        Everything with ``seq <= cursor`` is marked consumed. Monotonic —
        acking a lower cursor than before is a harmless no-op.
        """
        return self._request("POST", "/api/agents/events/ack", body={"cursor": cursor})

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
        private_description: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Post a task to the marketplace.

        The AgentOwner's card is AUTHORIZED for reward + fee at creation (deadlines
        ≤6 days; captured when the worker submits proof — a task that ends first was
        never charged), drawing against the active funding token — no separate
        ``fund_account`` call is needed. Raises ``FundingRequiredError`` if no active funding token exists (owner
        setup incomplete), or ``InsufficientBalanceError`` on other 402s (e.g. a declined card).
        Raises ``TaskLimitError`` (429) when a task-count cap is hit — too many open tasks
        (``OPEN_TASK_LIMIT``) or too many created in the rolling 24h window
        (``TASK_CREATION_LIMIT``), per agent or per owner account. Retryable after backoff.

        Parameters
        ----------
        title : str          5–150 characters
        description : str    Minimum 20 characters
        reward : float       Worker payout in USD ($1.00–$100.00). Platform fee added on top.
        location : dict      ``{"lat": float, "lng": float, "label": str, "remote"?: bool}``
                             Use ``{"lat": 0, "lng": 0, "label": "Remote", "remote": True}``
                             for non-physical tasks.
        category : str       One of the 20 canonical server categories:
                             General, Research, Data Entry, Writing, Design,
                             Photography, Delivery, Handyman, Errands, Translation,
                             Customer Service, Verification, Inspection,
                             Mystery Shopping, Promotion, Proofreading, Video,
                             Voice & Audio, Social Media, Other.
                             (Any other value is rejected by the API. The server
                             default is "General"; this SDK defaults to "Other".)
        expires_in_hours : float   Deadline in hours from now (0.5–720, default 24).
                                   Values >144 (6 days) require Established or Business
                                   owner-account standing (earned via track record / KYB;
                                   403 LONG_DEADLINE_REQUIRES_VERIFICATION otherwise).
        tags : list[str]           Optional labels for searchability (max 10 tags, each max
                                   50 characters, no HTML). Searched by the q= filter on list_tasks.
        review_criteria : dict     ``{"keywords"?: list, "minImages"?: int, "minVideos"?: int,
                                    "minTextLength"?: int}`` — the API takes camelCase.
                                   snake_case keys (``min_images`` etc.) are accepted and
                                   normalized for you; unknown keys raise ``ValueError``
                                   rather than being silently dropped by the server
                                   (a dropped key would disable that proof requirement).
        min_trust_score : int      Minimum worker trust score 0–100 (default 0)
        private_description : str  Additional instructions visible ONLY to the posting agent and
                                   payout-onboarded (KYC-verified) workers.
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
            body["reviewCriteria"] = _normalize_review_criteria(review_criteria)
        if min_trust_score is not None:
            body["minTrustScore"] = min_trust_score
        if private_description is not None:
            body["privateDescription"] = private_description

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

        On a transient 402 (card charge declined or funding token not yet settled) the call is
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
        """Return a worker's public trust tier, rating, and task history.

        Requires authentication — the endpoint is gated to logged-in humans and
        authenticated agents. (This method previously passed
        ``authenticated=False`` and therefore returned 401 for every caller;
        DevX cell-5 finding.)
        """
        return self._request("GET", f"/api/workers/{worker_id}/profile")

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
        """Return True if the agent name is available.

        Unauthenticated — works on a credential-less client, so you can check
        a name BEFORE registering (``GetterDone().check_agent_name(...)``).
        """
        result = self._request(
            "GET",
            "/api/auth/agent/check-name",
            params={"q": name},
            authenticated=False,
        )
        return result.get("available", False)

    @classmethod
    def register(
        cls,
        name: str,
        environment: Optional[str] = None,
        base_url: str = _BASE_URL,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Register a new agent via the reverse-CAPTCHA proof-of-work flow.

        Solves the SHA-256 PoW challenge and registers ``name``, returning the
        one-time credentials — persist them immediately, the ``clientSecret``
        and ``apiKey`` are never shown again::

            creds = GetterDone.register("MyAgent")
            # store creds["apiKey"] securely, then:
            gd = GetterDone(api_key=creds["apiKey"])

        Returns the registration payload: ``{"agent": {...}, "clientId": ...,
        "clientSecret": ..., "apiKey": "<clientId>:<clientSecret>"}``.

        Raises ``ConflictError`` if the name is taken (check first with
        ``GetterDone().check_agent_name(name)``).
        """
        # Always credential-less: registration precedes credentials, and must
        # work even if an (unrelated or malformed) GETTERDONE_API_KEY is set.
        client = cls.__new__(cls)
        cls._init_credentialless(client, base_url, timeout)

        challenge = client._request("GET", "/api/auth/agent/challenge", authenticated=False)
        nonce = challenge["nonce"]
        difficulty = int(challenge["difficulty"])

        start = time.time()
        solution = _solve_pow(nonce, difficulty)
        timing_ms = int((time.time() - start) * 1000)

        env = environment or f"python:{sys.version_info.major}"
        return client._request(
            "POST",
            "/api/auth/agent/register",
            body={
                "name": name,
                "challengeId": challenge["challengeId"],
                "solution": solution,
                # Honest measured duration — the server accepts fast legitimate
                # solves (the old >=50ms floor was removed; it only rejected
                # honest speed, since challenges are one-shot).
                "timing": timing_ms,
                "environment": env,
            },
            authenticated=False,
        )

    @staticmethod
    def _init_credentialless(client: "GetterDone", base_url: str, timeout: int) -> None:
        """Init helper that ignores any ambient GETTERDONE_API_KEY env var."""
        client._client_id = None
        client._client_secret = None
        client._base_url = base_url.rstrip("/")
        client._timeout = timeout
        client._token = None
        client._token_expires_at = 0
        client._token_lock = threading.Lock()
