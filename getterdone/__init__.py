"""
getterdone — Official Python SDK for the GetterDone Agent API

Quick start:
    pip install getterdone

    from getterdone import GetterDone
    gd = GetterDone(api_key=os.environ["GETTERDONE_API_KEY"])
    gd.create_task(title="...", description="...", reward=8.00, location={...})
"""

from .client import GetterDone
from .exceptions import (
    GetterDoneError,
    AuthenticationError,
    InsufficientBalanceError,
    TaskNotFoundError,
    AgentNameTakenError,
    RateLimitError,
    FundingRequiredError,
)

__all__ = [
    "GetterDone",
    "GetterDoneError",
    "AuthenticationError",
    "InsufficientBalanceError",
    "TaskNotFoundError",
    "AgentNameTakenError",
    "RateLimitError",
    "FundingRequiredError",
]

__version__ = "1.0.0"
