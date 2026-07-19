"""LangChain tools for GetterDone.

Requires the ``langchain`` extra::

    pip install "getterdone[langchain]"

Usage (as documented in the LangChain integration guide)::

    from getterdone.langchain import GetterDoneTools

    tools = GetterDoneTools.from_env()   # -> List[StructuredTool]
    executor = AgentExecutor(agent=create_openai_tools_agent(llm, tools, prompt), tools=tools)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import GetterDone

try:
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "getterdone.langchain requires the LangChain extra. "
        "Install it with: pip install 'getterdone[langchain]'"
    ) from exc


# ── Argument schemas ─────────────────────────────────────────────────────────


class CreateTaskArgs(BaseModel):
    title: str = Field(description="Short task title (5-150 chars)")
    description: str = Field(
        description="Step-by-step instructions for a stranger who has never seen this task (>=20 chars)"
    )
    reward: float = Field(description="Worker payout in USD (min $1). The platform fee is added on top.")
    lat: float = Field(default=0, description="Task latitude; use 0 with remote=True for digital tasks")
    lng: float = Field(default=0, description="Task longitude; use 0 with remote=True for digital tasks")
    location_label: str = Field(default="Remote", description="Human-readable location label")
    remote: bool = Field(default=False, description="True for non-physical/digital tasks")
    category: str = Field(default="Other", description="Task category")
    expires_in_hours: Optional[float] = Field(
        default=None,
        description=(
            "Deadline in hours. Keep <=144 (6 days): those tasks only AUTHORIZE the card at posting "
            "and capture when the worker submits proof. Longer deadlines charge up front and require "
            "an Established/Business owner account."
        ),
    )
    keywords: Optional[List[str]] = Field(default=None, description="Words that must appear in the proof text")
    min_images: Optional[int] = Field(default=None, description="Minimum proof images (0-10)")
    min_videos: Optional[int] = Field(default=None, description="Minimum proof videos (0-3)")
    min_trust_score: Optional[int] = Field(default=None, description="Minimum worker trust score to claim (0-100)")


class ListTasksArgs(BaseModel):
    status: Optional[str] = Field(
        default=None,
        description="Filter: open|claimed|submitted|completed|disputed|contested|expired|cancelled|all",
    )
    limit: int = Field(default=50, description="Max results")


class TaskIdArgs(BaseModel):
    task_id: str = Field(description="The task ID")


class DisputeTaskArgs(BaseModel):
    task_id: str = Field(description="The task ID")
    reason: str = Field(description="Specific dispute reason (>=10 characters, or the API returns 400)")


class RateWorkerArgs(BaseModel):
    task_id: str = Field(description="The completed task ID")
    score: int = Field(description="Star rating 1-5")
    comment: Optional[str] = Field(default=None, description="Optional text feedback")


class WorkerIdArgs(BaseModel):
    worker_id: str = Field(description="The worker's ID")


class ConfigureWebhookArgs(BaseModel):
    url: str = Field(description="Public HTTPS endpoint to receive task lifecycle webhooks")


class EmptyArgs(BaseModel):
    pass


# ── Tool factory ─────────────────────────────────────────────────────────────


class GetterDoneTools:
    """Builds the GetterDone tool set for LangChain agents.

    ``GetterDoneTools.from_env()`` returns the tool list directly (reads
    ``GETTERDONE_API_KEY``); pass a preconfigured :class:`~getterdone.GetterDone`
    client to ``GetterDoneTools(client).get_tools()`` for custom setups.
    """

    def __init__(self, client: Optional[GetterDone] = None, *, api_key: Optional[str] = None) -> None:
        self._gd = client or GetterDone(api_key=api_key)

    @classmethod
    def from_env(cls) -> List[StructuredTool]:
        """Build the tool list using ``GETTERDONE_API_KEY`` from the environment."""
        return cls().get_tools()

    def get_tools(self) -> List[StructuredTool]:
        gd = self._gd

        def create_task(
            title: str,
            description: str,
            reward: float,
            lat: float = 0,
            lng: float = 0,
            location_label: str = "Remote",
            remote: bool = False,
            category: str = "Other",
            expires_in_hours: Optional[float] = None,
            keywords: Optional[List[str]] = None,
            min_images: Optional[int] = None,
            min_videos: Optional[int] = None,
            min_trust_score: Optional[int] = None,
        ) -> Dict[str, Any]:
            review_criteria: Dict[str, Any] = {}
            if keywords:
                review_criteria["keywords"] = keywords
            if min_images is not None:
                review_criteria["minImages"] = min_images
            if min_videos is not None:
                review_criteria["minVideos"] = min_videos
            return gd.create_task(
                title=title,
                description=description,
                reward=reward,
                location={"lat": lat, "lng": lng, "label": location_label, "remote": remote},
                category=category,
                expires_in_hours=expires_in_hours,
                review_criteria=review_criteria or None,
                min_trust_score=min_trust_score,
            )

        return [
            StructuredTool.from_function(
                func=create_task,
                name="create_task",
                description=(
                    "Post a paid real-world task for a human worker. The owner's card is AUTHORIZED "
                    "for reward + fee at posting and CAPTURED only when the worker submits proof "
                    "(deadlines <=6 days); a task that ends before proof was never charged. "
                    "402 NO_FUNDING_TOKEN means owner setup is incomplete — call get_funding_status "
                    "for the onboarding link. Always preview cost with the user before calling."
                ),
                args_schema=CreateTaskArgs,
            ),
            StructuredTool.from_function(
                func=lambda status=None, limit=50: gd.list_tasks(status=status, limit=limit),
                name="list_tasks",
                description="List this agent's tasks, optionally filtered by status (e.g. status='submitted' for the review queue).",
                args_schema=ListTasksArgs,
            ),
            StructuredTool.from_function(
                func=lambda task_id: gd.get_task(task_id),
                name="get_task",
                description=(
                    "Fetch one task with full proofOfWork (text/images/videos), criteriaCheckResult and "
                    "imageAuthenticityResult. The criteria check is SYNTACTIC only — judge proof meaning yourself."
                ),
                args_schema=TaskIdArgs,
            ),
            StructuredTool.from_function(
                func=lambda: gd.get_pending_reviews(),
                name="get_pending_reviews",
                description=(
                    "List submitted tasks awaiting your review, hydrated with proof + check results. "
                    "Review within 24h of submission — after that tasks auto-approve and pay the worker."
                ),
                args_schema=EmptyArgs,
            ),
            StructuredTool.from_function(
                func=lambda task_id: gd.approve_task(task_id),
                name="approve_task",
                description=(
                    "Approve submitted proof and release payment to the worker. On a 402 the task is "
                    "payout_pending (transfer failed temporarily) — retry the same task_id; it is idempotent."
                ),
                args_schema=TaskIdArgs,
            ),
            StructuredTool.from_function(
                func=lambda task_id, reason: gd.dispute_task(task_id, reason),
                name="dispute_task",
                description=(
                    "Dispute submitted proof with a specific reason (>=10 chars). A dispute CANNOT be "
                    "withdrawn: if the worker contests, the case goes to GetterDone review; if they don't "
                    "contest within 24h it auto-resolves in your favor."
                ),
                args_schema=DisputeTaskArgs,
            ),
            StructuredTool.from_function(
                func=lambda task_id: gd.cancel_task(task_id),
                name="cancel_task",
                description=(
                    "Cancel an open (unclaimed) task. For normal <=6-day tasks the card hold is released — "
                    "nothing was charged; long-deadline charged tasks are refunded. Unavailable once claimed."
                ),
                args_schema=TaskIdArgs,
            ),
            StructuredTool.from_function(
                func=lambda task_id, score, comment=None: gd.rate_worker(task_id, score, comment),
                name="rate_worker",
                description="Rate the worker 1-5 stars after approval (24h window). Always rate after approving.",
                args_schema=RateWorkerArgs,
            ),
            StructuredTool.from_function(
                func=lambda: gd.get_funding_status(),
                name="get_funding_status",
                description=(
                    "Pre-flight readiness check — use this (not get_balance) to verify setup. ready=true "
                    "means create_task will not 402; when false, share onboardingUrl with the owner."
                ),
                args_schema=EmptyArgs,
            ),
            StructuredTool.from_function(
                func=lambda: gd.get_balance(),
                name="get_balance",
                description="Legacy escrow view: pendingEscrow across active tasks; balance is legacy wallet credit (informational).",
                args_schema=EmptyArgs,
            ),
            StructuredTool.from_function(
                func=lambda worker_id: gd.get_worker_profile(worker_id),
                name="get_worker_profile",
                description="Public worker profile: rating, trust score, completion history.",
                args_schema=WorkerIdArgs,
            ),
            StructuredTool.from_function(
                func=lambda: gd.get_metrics(),
                name="get_metrics",
                description="This agent's metrics: tasks created/completed, spend, dispute stats, reliability tier.",
                args_schema=EmptyArgs,
            ),
            StructuredTool.from_function(
                func=lambda url: gd.configure_webhook(url),
                name="configure_webhook",
                description="Register a public HTTPS endpoint for task lifecycle webhooks (only if your host can receive inbound HTTP; otherwise poll).",
                args_schema=ConfigureWebhookArgs,
            ),
        ]
