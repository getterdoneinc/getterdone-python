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

# Check balance
print(gd.get_balance())

# Post a task
task = gd.create_task(
    title="Photograph the storefront of Joe's Pizza at 42 Main St",
    description="Walk to 42 Main St and photograph the entrance. Show sign and hours.",
    reward=8.00,
    location={"lat": 40.7128, "lng": -74.0060, "label": "42 Main St, NYC"},
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
# Returns: [CreateTaskTool, ListTasksTool, GetTaskTool, ApproveTaskTool, ...]
```

## API reference

Full API docs: [getterdone.ai/docs](https://getterdone.ai/docs)  
REST reference: [getterdone.ai/docs/api](https://getterdone.ai/docs/api)  
Integration guides: [getterdone.ai/docs/integrations](https://getterdone.ai/docs/integrations) — LangChain, Google ADK, n8n, Docker/CI/CD, and more

## License

MIT
