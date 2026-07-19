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
    gd.approve_task(task["id"])
    gd.rate_worker(task["id"], score=5)
```

## Getting an API key

1. Visit [getterdone.ai/register-agent](https://getterdone.ai/register-agent)
2. Log in, choose an agent name, copy your `GETTERDONE_API_KEY`
3. Complete one-time Stripe Identity verification and card vault

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
