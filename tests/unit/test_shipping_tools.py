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

"""Unit tests for customer support shipping tools, Pydantic schemas, and guided recovery."""

from unittest.mock import MagicMock

from app.tools.shipping_tools import (
    ReturnLabelResult,
    ShippingRateResult,
    TrackingResult,
    calculate_shipping_rate,
    create_return_label,
    track_package,
)


def _mock_tool_context() -> MagicMock:
    ctx = MagicMock()
    ctx.state = {}
    return ctx


def test_track_package_known_shipment() -> None:
    """Test tracking an existing shipment returning a structured Pydantic TrackingResult."""
    ctx = _mock_tool_context()
    result = track_package("TRACK12345678", tool_context=ctx)

    assert isinstance(result, TrackingResult)
    assert result.success is True
    assert result.tracking_number == "TRACK12345678"
    assert result.shipping_status == "DELIVERED"
    assert result.signed_by == "J. Doe"
    assert len(result.recent_events) == 4
    # Check session state persistence
    assert ctx.state.get("last_tracking_number") == "TRACK12345678"
    assert ctx.state.get("last_package_status") == "DELIVERED"


def test_track_package_unknown_shipment_fallback() -> None:
    """Test tracking an arbitrary shipment number with fallback."""
    ctx = _mock_tool_context()
    result = track_package("XYZ99887766", tool_context=ctx)

    assert isinstance(result, TrackingResult)
    assert result.success is True
    assert result.tracking_number == "XYZ99887766"
    assert result.shipping_status == "IN_TRANSIT"
    assert ctx.state.get("last_tracking_number") == "XYZ99887766"


def test_track_package_guided_error_recovery() -> None:
    """Test guided error recovery when tracking number is too short or invalid."""
    ctx = _mock_tool_context()
    result = track_package("AB", tool_context=ctx)

    assert isinstance(result, TrackingResult)
    assert result.success is False
    assert result.error is not None
    assert result.recovery_guidance is not None
    assert "at least 8" in result.recovery_guidance.lower()


def test_calculate_shipping_rate_domestic_ground() -> None:
    """Test standard ground rate calculation within the same country."""
    ctx = _mock_tool_context()
    result = calculate_shipping_rate(
        origin_country="USA",
        destination_country="USA",
        weight_kg=2.5,
        service_tier="standard",
        tool_context=ctx,
    )

    assert isinstance(result, ShippingRateResult)
    assert result.success is True
    assert result.service_tier == "Standard Ground"
    assert result.international is False
    assert result.currency == "USD"
    # Base: 8.0 + (2.5 * 2.5) = 8.0 + 6.25 = 14.25
    assert result.total_estimated_cost == 14.25
    assert ctx.state.get("last_quote_cost") == 14.25


def test_calculate_shipping_rate_international_express() -> None:
    """Test international priority express calculation."""
    ctx = _mock_tool_context()
    result = calculate_shipping_rate(
        origin_country="Japan",
        destination_country="USA",
        weight_kg=3.0,
        service_tier="express",
        tool_context=ctx,
    )

    assert isinstance(result, ShippingRateResult)
    assert result.success is True
    assert result.service_tier == "Priority Express"
    assert result.international is True
    # Base: 28.0 + (3.0 * 8.0) = 28.0 + 24.0 = 52.0
    assert result.total_estimated_cost == 52.00
    assert ctx.state.get("last_quote_cost") == 52.00


def test_calculate_shipping_rate_guided_error_recovery() -> None:
    """Test guided recovery when weight is negative or exceeds freight limits."""
    ctx = _mock_tool_context()
    neg_result = calculate_shipping_rate("USA", "USA", -5.0, "standard", ctx)
    assert neg_result.success is False
    assert neg_result.error is not None
    assert "greater than 0" in neg_result.error
    assert neg_result.recovery_guidance is not None

    heavy_result = calculate_shipping_rate("USA", "USA", 250.0, "standard", ctx)
    assert heavy_result.success is False
    assert heavy_result.recovery_guidance is not None
    assert "freight" in heavy_result.recovery_guidance.lower()


def test_create_return_label_standard() -> None:
    """Test return label generation and RMA assignment for standard returns."""
    ctx = _mock_tool_context()
    result = create_return_label(
        order_id="ORD-2026-8812",
        reason="Wrong size requested",
        tool_context=ctx,
    )

    assert isinstance(result, ReturnLabelResult)
    assert result.success is True
    assert result.order_id == "ORD-2026-8812"
    assert result.return_status == "APPROVED"
    assert result.requires_human_review is False
    assert result.rma_number.startswith("RMA-2026-")
    assert "https://shipping.example.com/returns/label/" in result.label_download_url
    assert ctx.state.get("last_rma_number") == result.rma_number
    assert ctx.state.get("last_return_order_id") == "ORD-2026-8812"


def test_create_return_label_high_stakes_claim() -> None:
    """Test return label generation for damaged goods triggering human review flag."""
    ctx = _mock_tool_context()
    result = create_return_label(
        order_id="ORD-2026-9999",
        reason="Item arrived crushed and damaged",
        tool_context=ctx,
    )

    assert isinstance(result, ReturnLabelResult)
    assert result.success is True
    assert result.requires_human_review is True
    assert result.return_status == "APPROVED_PENDING_INSPECTION"
    assert "claims specialist" in result.instructions.lower()
