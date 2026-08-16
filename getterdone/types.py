"""
Typed return-value shapes for the GetterDone Python SDK.

These TypedDicts document the exact fields returned by each API method
without changing the underlying ``Dict[str, Any]`` wire format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass

try:
    from typing import TypedDict
except ImportError:  # Python < 3.8 (shouldn't occur; SDK requires 3.9+)
    from typing_extensions import TypedDict  # type: ignore[assignment]


class FundingStatus(TypedDict, total=False):
    """Shape returned by :meth:`GetterDone.get_funding_status`.

    Mirrors the ``GET /api/agents/funding-status`` response data envelope.
    """

    ready: bool
    """True when the Agent Owner setup is complete — ``create_task`` will not 402 NO_FUNDING_TOKEN."""

    hasActiveFundingToken: bool

    ownerKycStatus: str
    """The Agent Owner's KYC state ('none' when no owner is linked yet)."""

    onboardingUrl: str
    """Present only when not ready — Agent Owner setup deep-link pre-filled for this agent."""

    recurring: bool
    """Present only when ready. ``False`` = single-use token, consumed by your next task
    (the owner must issue a new one before you can post again); ``True`` = stays active
    across tasks, so you can post repeatedly without another human step."""

    perTaskLimitUsd: Optional[float]
    """Present only when ready. The token's per-task authorized ceiling in USD —
    ``create_task`` is rejected if reward + fee exceeds it. ``None`` when no limit was set."""


class BalanceResult(TypedDict):
    """Shape returned by :meth:`GetterDone.get_balance`.

    Mirrors the ``GET /api/agents/balance`` response data envelope.
    """

    balance: float
    """Legacy wallet balance in USD (informational — tasks are funded by card charge at creation)."""

    pendingEscrow: float
    """Amount currently locked in escrow across open/claimed tasks."""

    currency: str
    """ISO 4217 currency code (always ``"USD"`` currently)."""

    name: str
    """The agent's registered display name."""

    tasksCreated: int
    """Total number of tasks ever created by this agent."""


class AgentEvent(TypedDict):
    """Thin envelope from the durable per-agent event inbox (RFC-001)."""

    id: str
    """``evt_<ULID>`` — globally unique; dedupe key across poll + webhook."""

    seq: int
    """Monotonic per-agent sequence number — ordering and gap detection."""

    type: str
    """Event type, e.g. ``"task.submitted"`` or ``"task.expiring_soon"``."""

    occurredAt: str
    """ISO 8601 timestamp of the event."""

    subject: Dict[str, str]
    """Pointer to the subject, e.g. ``{"kind": "task", "id": "<taskId>"}``."""

    context: Dict[str, Any]
    """Small hints (``taskTitle``, …) — fetch fresh state via ``get_task``."""

    apiVersion: str
    """Envelope schema version (currently ``"v1"``)."""


class AgentEventsPage(TypedDict):
    """One page of inbox events from :meth:`GetterDone.get_events`."""

    events: List[AgentEvent]
    """Events in seq order (after any ``types`` filter)."""

    nextCursor: int
    """Last scanned seq — pass back as ``cursor`` and ack once processed."""

    hasMore: bool
    """True when the scan filled the limit — poll again immediately."""

    ackCursor: int
    """Your current acked high-water mark."""
