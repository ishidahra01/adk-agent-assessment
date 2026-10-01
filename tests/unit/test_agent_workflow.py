# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import pytest
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.workflow import Workflow
from google.genai import types

from app.agent import (
    _is_shipping_query_heuristic,
    classify_query,
    decline_node,
    root_agent,
)


def test_workflow_structure() -> None:
    """Verify that root_agent is a valid Workflow with the expected nodes and edges."""
    assert isinstance(root_agent, Workflow)
    assert root_agent.name == "customer_support_agent"

    # Verify nodes in the graph
    node_names = {node.name for node in root_agent.graph.nodes}
    assert "__START__" in node_names
    assert "query_classifier" in node_names
    assert "shipping_faq_agent" in node_names
    assert "decline_node" in node_names

    # Verify edges and routes
    edges = [
        (edge.from_node.name, edge.to_node.name, edge.route)
        for edge in root_agent.graph.edges
    ]
    assert ("__START__", "query_classifier", None) in edges
    assert ("query_classifier", "shipping_faq_agent", "shipping") in edges
    assert ("query_classifier", "decline_node", "unrelated") in edges


def test_shipping_faq_agent_tools() -> None:
    """Verify that shipping_faq_agent has tools configured for tracking, rates, and returns."""
    faq_agent = next(
        node for node in root_agent.graph.nodes if node.name == "shipping_faq_agent"
    )
    tool_names = {
        getattr(t, "name", getattr(t, "__name__", str(t))) for t in faq_agent.tools
    }
    assert "track_package" in tool_names
    assert "calculate_shipping_rate" in tool_names
    assert "create_return_label" in tool_names

    # Verify HITL (Human-in-the-Loop) confirmation hook on return_label_tool
    return_tool = next(
        t for t in faq_agent.tools if getattr(t, "name", "") == "create_return_label"
    )
    assert return_tool._require_confirmation is not None
    assert return_tool._require_confirmation("ORD-1", "Package arrived damaged") is True
    assert return_tool._require_confirmation("ORD-2", "Size too small") is False


@pytest.mark.parametrize(
    "query,expected",
    [
        ("Where is my package right now?", True),
        ("What are your overnight shipping rates?", True),
        ("Can I return a damaged delivery?", True),
        ("How do I track parcel 99123456789?", True),
        ("What is the cost to send a box to Chicago?", True),
        ("How can I change the delivery address for an in-transit parcel?", True),
        ("Tell me how to write a Python script for web scraping", False),
        ("What is the weather in Tokyo?", False),
        ("Write a poem about the ocean", False),
        ("Who won the 1998 world cup?", False),
    ],
)
def test_shipping_classification_heuristic(query: str, expected: bool) -> None:
    """Verify that shipping-related and unrelated queries are accurately classified."""
    assert _is_shipping_query_heuristic(query) == expected


@pytest.mark.asyncio
async def test_classify_query_node() -> None:
    """Test the classify_query node execution and route emission."""
    shipping_event = await classify_query("Where is my shipment?")
    assert shipping_event.actions.route == "shipping"

    unrelated_event = await classify_query("Can you help me bake a cake?")
    assert unrelated_event.actions.route == "unrelated"


def test_decline_node_output() -> None:
    """Test that the decline node produces polite content mentioning shipping topics."""
    event = decline_node("Can you write a poem?")
    assert event.content is not None
    assert event.content.parts is not None
    assert event.content.role == "model"
    text = "".join(part.text for part in event.content.parts if part.text)
    assert "shipping" in text.lower()
    assert "tracking" in text.lower() or "rates" in text.lower()


def test_workflow_execution_unrelated_query() -> None:
    """Test end-to-end workflow execution when given an unrelated query."""
    session_service = InMemorySessionService()
    session = session_service.create_session_sync(
        user_id="test_user", app_name="test_app"
    )
    runner = Runner(
        agent=root_agent, session_service=session_service, app_name="test_app"
    )

    msg = types.Content(
        role="user",
        parts=[types.Part.from_text(text="What is the capital of France?")],
    )
    events = list(
        runner.run(
            new_message=msg,
            user_id="test_user",
            session_id=session.id,
        )
    )

    # Verify that a response was generated by the decline node
    model_texts = [
        "".join(p.text for p in e.content.parts if p.text)
        for e in events
        if e.content and e.content.parts and e.content.role == "model"
    ]
    assert len(model_texts) > 0
    full_response = " ".join(model_texts)
    assert "shipping" in full_response.lower()
