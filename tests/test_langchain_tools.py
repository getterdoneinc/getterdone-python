"""Tests for getterdone.langchain — skipped when the langchain extra isn't installed."""

import pytest

pytest.importorskip("langchain_core", reason="requires: pip install 'getterdone[langchain]'")

from unittest.mock import MagicMock

from getterdone.langchain import GetterDoneTools

EXPECTED_TOOLS = [
    "create_task",
    "list_tasks",
    "get_task",
    "get_pending_reviews",
    "approve_task",
    "dispute_task",
    "cancel_task",
    "rate_worker",
    "get_funding_status",
    "get_balance",
    "get_worker_profile",
    "get_metrics",
    "configure_webhook",
]


def make_tools():
    client = MagicMock()
    return client, {t.name: t for t in GetterDoneTools(client).get_tools()}


def test_tool_roster():
    _, tools = make_tools()
    assert sorted(tools.keys()) == sorted(EXPECTED_TOOLS)


def test_from_env_returns_tool_list(monkeypatch):
    monkeypatch.setenv("GETTERDONE_API_KEY", "gd_client:secret")
    tools = GetterDoneTools.from_env()
    assert [t.name for t in tools] == EXPECTED_TOOLS


def test_create_task_assembles_location_and_criteria():
    client, tools = make_tools()
    tools["create_task"].invoke(
        {
            "title": "Photograph the storefront",
            "description": "Walk to 42 Main Street and take a clear photo of the entrance.",
            "reward": 8,
            "lat": 33.749,
            "lng": -84.388,
            "location_label": "Midtown Atlanta",
            "keywords": ["storefront"],
            "min_images": 1,
        }
    )
    kwargs = client.create_task.call_args.kwargs
    assert kwargs["location"] == {
        "lat": 33.749,
        "lng": -84.388,
        "label": "Midtown Atlanta",
        "remote": False,
    }
    assert kwargs["review_criteria"] == {"keywords": ["storefront"], "minImages": 1}


def test_create_task_remote_defaults_omit_criteria():
    client, tools = make_tools()
    tools["create_task"].invoke(
        {"title": "Proofread this paragraph", "description": "Proofread the attached paragraph for grammar.", "reward": 5, "remote": True}
    )
    kwargs = client.create_task.call_args.kwargs
    assert kwargs["location"]["remote"] is True
    assert kwargs["review_criteria"] is None


def test_simple_tools_delegate_to_client():
    client, tools = make_tools()
    tools["approve_task"].invoke({"task_id": "t1"})
    client.approve_task.assert_called_once_with("t1")
    tools["dispute_task"].invoke({"task_id": "t1", "reason": "Photo shows the wrong storefront entirely"})
    client.dispute_task.assert_called_once_with("t1", "Photo shows the wrong storefront entirely")
    tools["rate_worker"].invoke({"task_id": "t1", "score": 5, "comment": "fast"})
    client.rate_worker.assert_called_once_with("t1", 5, "fast")
    tools["get_funding_status"].invoke({})
    client.get_funding_status.assert_called_once()


def test_dispute_description_teaches_no_withdraw():
    _, tools = make_tools()
    assert "CANNOT be" in tools["dispute_task"].description
