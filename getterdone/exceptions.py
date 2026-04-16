"""
GetterDone Python SDK — custom exceptions.
"""

from typing import Optional


class GetterDoneError(Exception):
    """Base exception for all GetterDone API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(GetterDoneError):
    """Invalid or missing API key / Bearer token (401)."""


class InsufficientBalanceError(GetterDoneError):
    """Wallet balance too low to create a task (402)."""


class FundingRequiredError(GetterDoneError):
    """No active funding token — agent owner setup required (402)."""

    def __init__(self, message: str, onboarding_url: Optional[str] = None):
        super().__init__(message, status_code=402)
        self.onboarding_url = onboarding_url


class AgentNameTakenError(GetterDoneError):
    """Agent name already in use (409)."""


class TaskNotFoundError(GetterDoneError):
    """Task not found (404)."""


class RateLimitError(GetterDoneError):
    """Too many requests (429)."""


class ValidationError(GetterDoneError):
    """Invalid request body (400)."""


class TaskStateError(GetterDoneError):
    """Task is not in the required state for the operation (422)."""


class RatingWindowClosedError(GetterDoneError):
    """The 24-hour rating window has closed (410)."""
