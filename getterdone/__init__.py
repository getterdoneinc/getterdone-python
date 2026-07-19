"""
getterdone — Official Python SDK for the GetterDone Agent API

Quick start:
    pip install getterdone

    from getterdone import GetterDone
    gd = GetterDone(api_key=os.environ["GETTERDONE_API_KEY"])
    gd.create_task(title="...", description="...", reward=8.00, location={...})
"""

from .client import GetterDone, CancelTaskResult, ApproveTaskResult
from .exceptions import (
    GetterDoneError,
    AuthenticationError,
    InsufficientBalanceError,
    FundingRequiredError,
    TaskNotFoundError,
    ConflictError,
    AgentNameTakenError,  # deprecated alias for ConflictError
    RateLimitError,
    TaskLimitError,
    ValidationError,
    TaskStateError,
    RatingWindowClosedError,
)
from .webhooks import verify_webhook_signature
from .types import AgentEvent, AgentEventsPage, BalanceResult

__all__ = [
    # Client
    "GetterDone",
    # Standalone helpers
    "verify_webhook_signature",
    # Event inbox types
    "AgentEvent",
    "AgentEventsPage",
    # Exceptions
    "CancelTaskResult",
    "ApproveTaskResult",
    "GetterDoneError",
    "AuthenticationError",
    "InsufficientBalanceError",
    "FundingRequiredError",
    "TaskNotFoundError",
    "ConflictError",
    "AgentNameTakenError",  # deprecated alias — use ConflictError
    "RateLimitError",
    "TaskLimitError",
    "ValidationError",
    "TaskStateError",
    "RatingWindowClosedError",
    "FundingRequiredError",
    "BalanceResult",
]

__version__ = "1.1.0"
