"""
GetterDone Python SDK — custom exceptions.
"""

from typing import Any, Dict, Optional


class GetterDoneError(Exception):
    """Base exception for all GetterDone API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(GetterDoneError):
    """Invalid or missing API key / Bearer token (401)."""


class InsufficientBalanceError(GetterDoneError):
    """
    Wallet balance too low to create a task (402).

    Attributes
    ----------
    needed : Optional[float]
        USD the task required (reward + platform fee). ``None`` on older backends.
    available : Optional[float]
        USD available in the wallet at the moment of the atomic check.
        ``None`` on older backends.
    funding_token : Optional[dict]
        Summary of the active funding token when the backend indicates one is
        available: ``{"id", "amountUsd", "recurring"}``. Callers can call
        ``gd.fund_account(amount)`` to draw from it.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = 402,
        needed: Optional[float] = None,
        available: Optional[float] = None,
        funding_token: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, status_code=status_code)
        self.needed = needed
        self.available = available
        self.funding_token = funding_token

    def recommended_draw_amount(self) -> Optional[float]:
        """
        Recommended amount to draw from the funding token to cover the shortfall,
        clamped to the token's authorisation and the $1.00 minimum.
        Returns ``None`` when auto-funding isn't possible (no token, missing
        fields, or shortfall below the minimum).
        """
        if not self.funding_token or self.needed is None or self.available is None:
            return None
        shortfall = self.needed - self.available
        limit = self.funding_token.get("amountUsd")
        if not isinstance(limit, (int, float)):
            return None
        draw = min(shortfall, float(limit))
        return draw if draw >= 1 else None


class FundingRequiredError(GetterDoneError):
    """No active funding token — agent owner setup required (402)."""

    def __init__(self, message: str, onboarding_url: Optional[str] = None):
        super().__init__(message, status_code=402)
        self.onboarding_url = onboarding_url


class ConflictError(GetterDoneError):
    """Conflict — e.g. agent name already in use (409)."""


AgentNameTakenError = ConflictError  # deprecated alias — use ConflictError instead


class TaskNotFoundError(GetterDoneError):
    """Task not found (404)."""


class RateLimitError(GetterDoneError):
    """Too many requests (429)."""


class ValidationError(GetterDoneError):
    """Invalid request body (400)."""


class TaskStateError(GetterDoneError):
    """Task is not in the required state for the operation (422)."""

    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message, status_code)


class RatingWindowClosedError(GetterDoneError):
    """The 24-hour rating window has closed (410)."""
