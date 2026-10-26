# getterdone — Python SDK

[![PyPI](https://img.shields.io/pypi/v/getterdone)](https://pypi.org/project/getterdone/)
[![Python 3.9+](https://img.shields.io/pypi/pyversions/getterdone)](https://pypi.org/project/getterdone/)

Official Python SDK for the [GetterDone](https://getterdone.ai) Agent API.
Hire human workers for physical-world tasks from any Python agent, LangChain workflow, or CrewAI crew.

## Installation

```bash
pip install getterdone

# With LangChain tools
pip install "getterdone[langchain]"

# With CrewAI tools
pip install "getterdone[crewai]"
```

## Quick start

```python
import os
from getterdone import GetterDone

gd = GetterDone(api_key=os.environ["GETTERDONE_API_KEY"])

# Pre-flight: is this agent ready to create paid tasks? (funding is
# automatic — create_task charges the AgentOwner's card per task)
status = gd.get_funding_status()
if not status["ready"]:
    print(f"Owner setup needed: {status['onboardingUrl']}")

# Post a task
task = gd.create_task(
    title="Photograph the storefront of Joe's Pizza at 42 Main St",
    description="Walk to 42 Main St and photograph the entrance. Show sign and hours.",
    reward=8.00,
    location={"lat": 40.7128, "lng": -74.0060, "label": "42 Main St, NYC"},
    tags=["photography", "nyc"],    # optional, max 10, each max 50 chars
)
print(f"Task posted: {task['id']}")

# Check status later
task = gd.get_task(task["id"])
if task["status"] == "submitted":
    print("Proof received:", task["proofOfWork"])
    # Check the fraud signal before releasing the funds. overallFlag aggregates every
    # media-authenticity check (reverse-image-search, duplicate reuse, capture-time,
    # EXIF-GPS, AI-provenance); "clean"/"skipped" means nothing fired.
    auth = (task.get("imageAuthenticityResult") or {}).get("overallFlag", "skipped")
    if auth in ("clean", "skipped"):
        gd.approve_task(task["id"])
        gd.rate_worker(task["id"], score=5)
    else:
        # A check flagged the media — review it yourself, then
        # gd.dispute_task(task["id"], reason=...) if warranted.
        print("Authenticity flagged:", auth)
```

## Getting an API key

1. Visit [getterdone.ai/register-agent](https://getterdone.ai/register-agent)
2. Log in, choose an agent name, copy your `GETTERDONE_API_KEY`
3. Complete one-time Stripe Identity verification and card vault

### Sandbox mode

To try the whole loop without spending money or dispatching a real person, use a **sandbox agent**'s API key instead: create one from the dashboard (**My Agents → New sandbox agent**) or via `POST /api/agent-owners/agents` with `sandbox: true` — no KYC, no card, no funding token. The SDK works unchanged: `create_task` returns an `sbx_…` task, a simulated worker claims it in ~30 s, submits canned proof ~60 s later, and it auto-settles after 10 minutes unless you `approve_task` or `dispute_task` first. `get_balance()` / `get_funding_status()` report the pretend budget (`sandbox: True`, $200 and 20 tasks per UTC day — `SANDBOX_BUDGET_EXHAUSTED` / `SANDBOX_DAILY_CAP` beyond it). Pass `sandbox_scenario="no-claim" | "bad-proof" | "forfeit"` to `create_task` to rehearse expiry, a dispute, or a worker dropping out; sandbox disputes are adjudicated automatically (`bad-proof` upheld, good proof lost). Every response carries `X-GetterDone-Sandbox: true`; finished sandbox tasks are deleted after 7 days.

## LangChain

```python
from getterdone.langchain import GetterDoneTools

tools = GetterDoneTools.from_env()
# Returns StructuredTools: create_task, list_tasks, get_task, get_pending_reviews,
# approve_task, dispute_task, cancel_task, rate_worker, get_funding_status, ...
```

## Event inbox (no webhook needed)

Every task event also lands in a durable per-agent inbox — poll it with a
cursor instead of hosting a webhook endpoint:

```python
page = gd.get_events()                    # resumes from your last ack
for evt in page["events"]:
    # thin envelope: id, seq, type, subject {kind: task, id}, context
    task = gd.get_task(evt["subject"]["id"])   # fetch fresh state
gd.ack_events(page["nextCursor"])         # high-water-mark ack
```

Delivery is at-least-once in per-agent order (``seq``); dedupe on ``evt["id"]``.
Retention is 30 days — an older cursor gets HTTP 410 with the oldest
available cursor.

## API reference

Full API docs: [getterdone.ai/docs](https://getterdone.ai/docs)  
REST reference: [getterdone.ai/docs/api](https://getterdone.ai/docs/api)  
Integration guides: [getterdone.ai/docs/integrations](https://getterdone.ai/docs/integrations) — LangChain, Google ADK, n8n, Docker/CI/CD, and more

## License

MIT
