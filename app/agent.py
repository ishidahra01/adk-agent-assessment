# ruff: noqa
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

import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from google.adk.agents import LlmAgent
from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App, ResumabilityConfig
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.events.event import Event, EventActions
from google.adk.models import Gemini
from google.adk.tools import FunctionTool
from google.adk.workflow import FunctionNode, Workflow
from google.genai import Client, types
from pydantic import BaseModel, Field

from app.callbacks import (
    guardrail_before_model,
    init_session_state,
    log_after_tool,
    log_before_tool,
)
from app.tools.shipping_tools import (
    calculate_shipping_rate,
    create_return_label,
    track_package,
)

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Strategic Model Routing Configuration
# -----------------------------------------------------------------------------
# - ROUTER_MODEL: Low-latency, cost-effective model for intent classification & routing
# - SPECIALIST_MODEL: Multi-capability model for domain tools, logic, and customer care
# - CLAIMS_MODEL: High-reasoning model for complex claims, disputes, and fraud analysis
ROUTER_MODEL = "gemini-2.5-flash-lite"
SPECIALIST_MODEL = "gemini-3.8-flash"
CLAIMS_MODEL = "gemini-2.5-pro"


class QueryClassification(BaseModel):
    """Structured classification output indicating whether a query relates to shipping services."""

    is_shipping_related: bool = Field(
        description="True if the inquiry is related to shipping (rates, tracking, delivery, returns, packaging, customs, or parcel logistics); False otherwise."
    )
    reason: str = Field(
        default="",
        description="Brief justification for why the inquiry is classified as shipping-related or unrelated.",
    )


SHIPPING_KEYWORDS = [
    r"\bship(ping|ped|s|ment|ments)?\b",
    r"\btrack(ing|ed|s)?\b",
    r"\bpackage(s)?\b",
    r"\bparcel(s)?\b",
    r"\bdeliver(y|ies|ed|ing|s)?\b",
    r"\brate(s)?\b",
    r"\breturn(s|ed|ing)?\b",
    r"\brefund(s|ed|ing)?\b",
    r"\bcourier(s)?\b",
    r"\btransit\b",
    r"\bfreight\b",
    r"\bcustoms\b",
    r"\bpostage\b",
    r"\bpickup\b",
    r"\bdropoff\b",
    r"\border\b",
    r"\brma\b",
    r"\blost package\b",
    r"\bexchange(s)?\b",
    r"\bbox(es)?\b",
    r"\bsend(ing)?\b",
    r"\bmail(ing|ed|s)?\b",
    r"\bcost\b",
]

JAPANESE_SHIPPING_KEYWORDS = [
    r"追跡",
    r"配達",
    r"配送",
    r"荷物",
    r"送料",
    r"運賃",
    r"返品",
    r"返金",
    r"発送",
    r"宅配",
    r"届(?:く|い|か|け)?",
    r"再配達",
    r"集荷",
    r"梱包",
    r"関税",
    r"不在票",
]

SHIPPING_PATTERN = re.compile("|".join(SHIPPING_KEYWORDS), re.IGNORECASE)
JAPANESE_SHIPPING_PATTERN = re.compile("|".join(JAPANESE_SHIPPING_KEYWORDS))


def _is_shipping_query_heuristic(text: str) -> bool:
    """Heuristic fallback to identify shipping-related inquiries in English or Japanese."""
    return bool(SHIPPING_PATTERN.search(text)) or bool(
        JAPANESE_SHIPPING_PATTERN.search(text)
    )


def _extract_query_text(node_input: Any) -> str:
    """Extract plain text from various node input types."""
    if isinstance(node_input, str):
        return node_input
    if isinstance(node_input, types.Content):
        return " ".join(part.text for part in node_input.parts if part.text)
    if isinstance(node_input, dict):
        return str(node_input.get("text", node_input))
    return str(node_input)


async def classify_query(node_input: Any) -> Event:
    """First stage node: Classifies incoming query using the fast strategic ROUTER_MODEL.

    Uses Gemini structured output via ROUTER_MODEL (gemini-2.5-flash-lite) for speed and cost efficiency,
    falling back to domain regex heuristics if offline or unconfigured.
    """
    query_text = _extract_query_text(node_input)
    is_shipping: bool | None = None

    try:
        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in (
            "true",
            "1",
            "yes",
        )
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
        api_key = os.getenv("GEMINI_API_KEY")

        if (use_vertex and project) or api_key:
            client = Client(
                vertexai=use_vertex,
                project=project if use_vertex else None,
                location=location if use_vertex else None,
                api_key=api_key,
            )
            prompt = (
                "You are an intent classification assistant for a shipping company. "
                "Classify whether the following customer inquiry is related to shipping "
                "(rates, tracking, delivery status, transit times, returns, packaging, customs) "
                "or unrelated (general chit-chat, poetry, jokes, weather, coding, etc.).\n\n"
                f'Customer inquiry: "{query_text}"'
            )
            response = await client.aio.models.generate_content(
                model=ROUTER_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=QueryClassification,
                    temperature=0.0,
                ),
            )
            if response.parsed:
                is_shipping = response.parsed.is_shipping_related
            elif response.text:
                data = json.loads(response.text)
                is_shipping = data.get("is_shipping_related", False)
    except Exception as e:
        logger.warning(
            "Router model classification failed, using heuristic fallback: %s", e
        )

    if is_shipping is None:
        is_shipping = _is_shipping_query_heuristic(query_text)

    route = "shipping" if is_shipping else "unrelated"
    return Event(
        output=query_text,
        actions=EventActions(
            route=route,
            state_delta={"last_inquiry": query_text, "classified_route": route},
        ),
    )


def _is_japanese_text(text: str) -> bool:
    """Check if the text contains Japanese characters (Hiragana, Katakana, or Kanji)."""
    return bool(re.search(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", text))


def decline_node(node_input: Any) -> Event:
    """Terminal node: Politely declines off-topic inquiries and clarifies available shipping services."""
    query_text = _extract_query_text(node_input)
    if _is_japanese_text(query_text):
        message = (
            "お問い合わせいただきありがとうございます。恐れ入りますが、当窓口は配送料金、荷物の追跡、配達状況、返品リクエストなどの配送関連のお問い合わせ専用となっております。"
            "その他の内容につきましては対応いたしかねます。配送に関するご不明点がございましたら、お気軽にお申し付けください。"
        )
    else:
        message = (
            "Thank you for contacting customer support. However, I specialize exclusively in shipping inquiries, "
            "including shipping rates, package tracking, delivery schedules, and return requests. "
            "I am unable to assist with other topics. Please let me know how I can help with your shipment!"
        )
    return Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=message)],
        ),
        output=message,
    )


# -----------------------------------------------------------------------------
# Human-in-the-Loop (HITL) Validation Hook
# -----------------------------------------------------------------------------


def requires_supervisor_approval(order_id: str, reason: str, **kwargs: Any) -> bool:
    """Human-in-the-loop validation hook for high-stakes tool executions.

    Requires supervisor approval before issuing prepaid return labels for damaged goods,
    warranty claims, lost parcel disputes, or high-value claims.
    """
    sensitive_triggers = [
        "damage",
        "defect",
        "broken",
        "claim",
        "expensive",
        "fraud",
        "lost",
    ]
    reason_lower = (reason or "").lower()
    return any(trigger in reason_lower for trigger in sensitive_triggers)


# Wrap create_return_label with HITL confirmation hook
return_label_tool = FunctionTool(
    func=create_return_label,
    require_confirmation=requires_supervisor_approval,
)

# -----------------------------------------------------------------------------
# Specialist Customer Support Agent
# -----------------------------------------------------------------------------

shipping_faq_agent = LlmAgent(
    name="shipping_faq_agent",
    model=Gemini(
        model=SPECIALIST_MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    tools=[
        track_package,
        calculate_shipping_rate,
        return_label_tool,
    ],
    before_agent_callback=init_session_state,
    before_model_callback=guardrail_before_model,
    before_tool_callback=log_before_tool,
    after_tool_callback=log_after_tool,
    instruction="""You are a professional and courteous customer support representative for a premier shipping logistics service.
Your role is to assist customers with all their shipping-related questions clearly, accurately, and politely.
Always respond in the same language as the customer's inquiry (e.g., respond in natural, polite Japanese if the inquiry is in Japanese, English if in English).

CRITICAL TOOL USAGE RULES:
1. PACKAGE TRACKING:
   - When a customer provides a tracking number (e.g., TRACK12345678, alphanumeric code) or asks where their package is, YOU MUST ALWAYS CALL the `track_package(tracking_number)` tool first.
   - NEVER invent or speculate tracking details. Use the exact data returned by `track_package`.
   - If `error` or `recovery_guidance` is returned in the tool response, follow that guidance to help the customer fix their tracking input.
2. SHIPPING RATE CALCULATION:
   - When a customer asks for shipping prices, quotes, transit times, or rates between locations, YOU MUST CALL the `calculate_shipping_rate(origin_country, destination_country, weight_kg, service_tier)` tool.
   - If service level is not specified, default service_tier to 'standard'.
   - If weight is invalid, refer to the tool's `recovery_guidance` to guide the customer.
3. RETURNS & REFUNDS (HITL PROTECTED):
   - When a customer requests a return, replacement, or RMA label with an order ID, YOU MUST CALL the `create_return_label(order_id, reason)` tool.
   - Note that high-stakes returns (damaged items, claims) trigger human supervisor validation. Explain this courteously to the customer.

CONTEXT & MEMORY:
- You retain context and memory across conversational turns.
- If the customer asks follow-up questions referencing a previously tracked package or order (e.g., "Who signed for it?", "When will it arrive?", "What was the quote?"), look at the previous turn details and answer directly without asking them to repeat the tracking or order number.

Tone and Guidelines:
- Always respond in the customer's language with a polite and helpful tone.
- Empathize with customer issues and offer direct, actionable next steps.
- Use clear bullet points and headings for readability.
- When calling tools, explain the outcome naturally and professionally.
- Stay focused on shipping and logistics support.""",
)

classify_node = FunctionNode(
    func=classify_query,
    name="query_classifier",
)

decline_handler = FunctionNode(
    func=decline_node,
    name="decline_node",
)

root_agent = Workflow(
    name="customer_support_agent",
    description="A customer support graph workflow agent that classifies user inquiries into shipping vs unrelated topics and routes them to a shipping FAQ agent or a polite decline response.",
    edges=[
        ("START", classify_node),
        (
            classify_node,
            {"shipping": shipping_faq_agent, "unrelated": decline_handler},
        ),
    ],
)

# App configured with Resumability (HITL), History Compaction, and Context Caching
app = App(
    name="app",
    root_agent=root_agent,
    resumability_config=ResumabilityConfig(is_resumable=True),
    events_compaction_config=EventsCompactionConfig(
        token_threshold=16000,
        event_retention_size=6,
        summarizer=LlmEventSummarizer(llm=Gemini(model=ROUTER_MODEL)),
    ),
    context_cache_config=ContextCacheConfig(
        min_tokens=2048,
        ttl_seconds=1800,
    ),
)
