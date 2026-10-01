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

"""Observability, structured logging, PII redaction, and background memory consolidation."""

import asyncio
import logging
import re
from collections.abc import MutableMapping
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import BaseTool, ToolContext
from google.genai import types

_background_tasks: set[asyncio.Task[Any]] = set()

# -----------------------------------------------------------------------------
# Dedicated Structured Logging with Cloud Logging Payload Compatibility
# -----------------------------------------------------------------------------


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """Dedicated structured logger adapter that injects standardized context metadata.

    Replaces raw json.dumps string formatting with proper structured log records,
    fully compatible with Google Cloud Logging and OpenTelemetry trace contexts.
    """

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra = kwargs.setdefault("extra", {})
        if isinstance(extra, dict):
            payload = extra.setdefault("json_fields", {})
            if isinstance(msg, dict):
                payload.update(msg)
                msg = msg.get("event", "structured_log_event")
            payload["service"] = "customer-support-agent"
            payload["environment"] = "production"
        return msg, kwargs


_base_logger = logging.getLogger("customer_support.structured")
logger = StructuredLoggerAdapter(_base_logger, {})

# -----------------------------------------------------------------------------
# PII (Personally Identifiable Information) Redaction Engine
# -----------------------------------------------------------------------------

EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,7}\b")
PHONE_REGEX = re.compile(
    r"\b(?:\+?(\d{1,3}))?[-. (]*(\d{2,4})[-. )]*(\d{3,4})[-. ]*(\d{3,4})\b"
)
CREDIT_CARD_REGEX = re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b|\b\d{15,16}\b")
SSN_OR_ID_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def redact_pii(data: Any) -> Any:
    """Recursively redacts sensitive PII (emails, phone numbers, payment details) from data.

    Supports strings, dictionaries, lists, and Pydantic models.
    """
    if isinstance(data, str):
        sanitized = EMAIL_REGEX.sub("[EMAIL_REDACTED]", data)
        sanitized = CREDIT_CARD_REGEX.sub("[CARD_REDACTED]", sanitized)
        sanitized = SSN_OR_ID_REGEX.sub("[GOV_ID_REDACTED]", sanitized)
        sanitized = PHONE_REGEX.sub("[PHONE_REDACTED]", sanitized)
        return sanitized

    if isinstance(data, dict):
        redacted_dict: dict[str, Any] = {}
        for k, v in data.items():
            # Sensitive key field masking
            if any(
                s in k.lower()
                for s in ["password", "secret", "token", "ssn", "credit_card", "cvv"]
            ):
                redacted_dict[k] = "[CONFIDENTIAL_REDACTED]"
            else:
                redacted_dict[k] = redact_pii(v)
        return redacted_dict

    if isinstance(data, list):
        return [redact_pii(item) for item in data]

    if hasattr(data, "model_dump"):
        return redact_pii(data.model_dump())

    return data


# -----------------------------------------------------------------------------
# Async Background Tasks for Memory Consolidation
# -----------------------------------------------------------------------------


async def consolidate_memory_async(
    session_id: str, state_snapshot: dict[str, Any]
) -> None:
    """Asynchronous background worker to consolidate conversation context and update memory.

    Performs non-blocking background consolidation of customer interaction trends,
    tracked parcel histories, and preference extraction without delaying chat turns.
    """
    try:
        # Simulate non-blocking async persistence / vector memory consolidation
        await asyncio.sleep(0.01)

        tracked = state_snapshot.get("tracked_shipments", [])
        interaction_count = state_snapshot.get("interaction_count", 0)

        # Consolidate user memory summary
        consolidated_summary = {
            "session_id": session_id,
            "total_turns": interaction_count,
            "total_packages_tracked": len(tracked),
            "recent_shipments": tracked[-5:],
            "consolidated": True,
        }

        safe_summary = redact_pii(consolidated_summary)
        logger.info(
            {
                "event": "background_memory_consolidation_completed",
                "summary": safe_summary,
            }
        )
    except Exception as e:
        logger.warning(
            {
                "event": "background_memory_consolidation_failed",
                "error": str(e),
            }
        )


# -----------------------------------------------------------------------------
# Prompt Injection & Security Guardrails
# -----------------------------------------------------------------------------

INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(
        r"reveal\s+(your\s+)?(system\s+prompt|hidden\s+instructions)", re.IGNORECASE
    ),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.IGNORECASE),
]


# -----------------------------------------------------------------------------
# Lifecycle Callbacks
# -----------------------------------------------------------------------------


async def init_session_state(callback_context: CallbackContext) -> None:
    """Initializes and enriches conversational session state for Context & Memory management."""
    state = callback_context.state

    if "interaction_count" not in state:
        state["interaction_count"] = 0
    state["interaction_count"] += 1

    if "tracked_shipments" not in state:
        state["tracked_shipments"] = []

    if "customer_profile" not in state:
        state["customer_profile"] = {
            "tier": "STANDARD",
            "preferred_language": "auto",
        }

    logger.info(
        {
            "event": "session_turn_started",
            "interaction_count": state["interaction_count"],
            "tracked_shipments_count": len(state["tracked_shipments"]),
        }
    )


async def guardrail_before_model(
    callback_context: CallbackContext, llm_request: LlmRequest
) -> LlmResponse | None:
    """Guardrail hook to inspect incoming prompt contents for prompt injection or abuse."""
    contents = llm_request.contents or []
    extracted_texts: list[str] = []
    for content in contents:
        if hasattr(content, "parts") and content.parts:
            for part in content.parts:
                if hasattr(part, "text") and part.text:
                    extracted_texts.append(part.text)

    combined_input = " ".join(extracted_texts)

    for pattern in INJECTION_PATTERNS:
        if pattern.search(combined_input):
            logger.warning(
                {
                    "event": "guardrail_triggered",
                    "reason": "prompt_injection_pattern_detected",
                    "sanitized_input": redact_pii(combined_input[:100]),
                }
            )
            safe_text = (
                "Security Notice: This request could not be processed as it violates safety guidelines. "
                "How can I assist you with your shipping inquiry?"
            )
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=safe_text)],
                )
            )

    return None


async def log_before_tool(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> dict[str, Any] | None:
    """Pre-execution hook: Logs sanitized tool invocation telemetry with PII redaction."""
    tool_name = getattr(tool, "name", str(tool))
    sanitized_args = redact_pii(args)

    logger.info(
        {
            "event": "tool_call_started",
            "tool_name": tool_name,
            "arguments": sanitized_args,
        }
    )
    return None


async def log_after_tool(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: Any,
) -> Any:
    """Post-execution hook: Records structured telemetry, updates state, and triggers async memory consolidation."""
    tool_name = getattr(tool, "name", str(tool))

    # Convert Pydantic or dict for inspection
    raw_response = (
        tool_response.model_dump()
        if hasattr(tool_response, "model_dump")
        else tool_response
    )

    if tool_name == "track_package" and isinstance(raw_response, dict):
        tracking_num = raw_response.get("tracking_number")
        if tracking_num and hasattr(tool_context, "state"):
            history = tool_context.state.setdefault("tracked_shipments", [])
            if tracking_num not in history:
                history.append(tracking_num)
            tool_context.state["last_tracked_shipment"] = raw_response

    # Trigger non-blocking async background memory consolidation
    session_id = getattr(getattr(tool_context, "session", None), "id", "local_session")
    state_obj: Any = getattr(tool_context, "state", None)
    state_copy: dict[str, Any] = {}
    if state_obj is not None:
        if hasattr(state_obj, "to_dict"):
            state_copy = state_obj.to_dict()
        elif isinstance(state_obj, dict):
            state_copy = state_obj.copy()
    task = asyncio.create_task(consolidate_memory_async(session_id, state_copy))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Sanitize response telemetry using PII redaction
    sanitized_resp = redact_pii(raw_response)
    is_success = (
        sanitized_resp.get("success", True)
        if isinstance(sanitized_resp, dict)
        else True
    )

    logger.info(
        {
            "event": "tool_call_completed",
            "tool_name": tool_name,
            "status": "success" if is_success else "failure",
            "has_recovery_guidance": bool(
                isinstance(sanitized_resp, dict)
                and sanitized_resp.get("recovery_guidance")
            ),
        }
    )

    return None
