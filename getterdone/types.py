"""
Typed return-value shapes for the GetterDone Python SDK.

These TypedDicts document the exact fields returned by each API method
without changing the underlying ``Dict[str, Any]`` wire format.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

try:
    from typing import TypedDict
except ImportError:  # Python < 3.8 (shouldn't occur; SDK requires 3.9+)
    from typing_extensions import TypedDict  # type: ignore[assignment]


class BalanceResult(TypedDict):
    """Shape returned by :meth:`GetterDone.get_balance`.

    Mirrors the ``GET /api/agents/balance`` response data envelope.
    """

    balance: float
    """Available wallet balance in USD."""

    pendingEscrow: float
    """Amount currently locked in escrow across open/claimed tasks."""

    currency: str
    """ISO 4217 currency code (always ``"USD"`` currently)."""

    name: str
    """The agent's registered display name."""

    tasksCreated: int
    """Total number of tasks ever created by this agent."""
