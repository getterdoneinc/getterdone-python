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
    # Present only when ready. Spendable platform credit in USD — a task whose
    # reward + fee fits entirely inside it is funded by credit (no card charge).
    platformCreditUsd: Optional[float]
    """Present only when ready. The token's per-task authorized ceiling in USD —
    ``create_task`` is rejected if reward + fee exceeds it. ``None`` when no limit was set."""

    sandbox: bool
    """Present (``True``) for a sandbox agent — always ready; nothing is charged and a
    simulated worker responds. The day-budget keys below replace the card and token."""

    dailyBudgetUsd: float
    """Sandbox only. Pretend spend allowed per UTC day (reward + fee), currently 200."""

    remainingUsd: float
    """Sandbox only. Budget left today — a task that does not fit returns 402 ``SANDBOX_BUDGET_EXHAUSTED``."""

    createdToday: int
    """Sandbox only. Tasks created today against ``dailyTaskCap``."""

    dailyTaskCap: int
    """Sandbox only. Task creations allowed per UTC day, currently 20 (429 ``SANDBOX_DAILY_CAP`` beyond it)."""

    resetsAt: str
    """Sandbox only. ISO timestamp of the next UTC midnight, when the budget and cap reset."""


class _SandboxBalanceFields(TypedDict, total=False):
    """Keys present only when the agent is a sandbox agent (see :class:`BalanceResult`)."""

    sandbox: bool
    """``True`` for a sandbox agent — no wallet or secured funds; the day budget is the only number that moves."""

    dailyBudgetUsd: float
    """Pretend spend allowed per UTC day (reward + fee), currently 200."""

    remainingUsd: float
    """Budget left today."""

    createdToday: int
    """Tasks created today against ``dailyTaskCap``."""

    dailyTaskCap: int
    """Task creations allowed per UTC day, currently 20."""

    resetsAt: str
    """ISO timestamp of the next UTC midnight, when the budget and cap reset."""


class BalanceResult(_SandboxBalanceFields):
    """Shape returned by :meth:`GetterDone.get_balance`.

    Mirrors the ``GET /api/agents/balance`` response data envelope. For a sandbox
    agent ``balance`` and ``pendingEscrow`` are absent and the optional sandbox
    keys (``sandbox``, ``dailyBudgetUsd``, ``remainingUsd``, ``createdToday``,
    ``dailyTaskCap``, ``resetsAt``) are present instead.
    """

    balance: float
    """Legacy wallet balance in USD (informational — tasks are funded by card charge at creation). Absent for a sandbox agent."""

    pendingEscrow: float
    """Funds currently secured across open/claimed tasks (field name kept for API compatibility). Absent for a sandbox agent."""

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
