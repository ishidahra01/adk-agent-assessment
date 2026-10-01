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

"""Shipping customer support tools for tracking, rate calculation, and returns.

Features explicit Pydantic output schemas and guided error recovery for LLM tool use.
"""

import logging
import re
from typing import Any

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TransitEvent(BaseModel):
    """A single tracking milestone in a shipment's journey."""

    timestamp: str = Field(description="ISO 8601 timestamp of the tracking scan.")
    location: str = Field(description="Facility or city location of the scan.")
    description: str = Field(description="Human-readable event description.")


class TrackingResult(BaseModel):
    """Structured response for package tracking queries with guided recovery."""

    success: bool = Field(
        description="True if tracking search was successful, False otherwise."
    )
    tracking_number: str = Field(
        default="", description="The package tracking identifier."
    )
    shipping_status: str = Field(
        default="",
        description="Current shipment status: DELIVERED, IN_TRANSIT, OUT_FOR_DELIVERY, or EXCEPTION.",
    )
    carrier: str = Field(default="", description="Logistics carrier name.")
    estimated_delivery: str | None = Field(
        default=None, description="Estimated or actual delivery timestamp."
    )
    signed_by: str | None = Field(
        default=None, description="Name of person who signed for delivery if available."
    )
    origin: str = Field(default="", description="Origin dispatch facility.")
    destination: str = Field(
        default="", description="Final recipient destination city/country."
    )
    recent_events: list[TransitEvent] = Field(
        default_factory=list, description="Chronological list of transit events."
    )
    error: str | None = Field(
        default=None, description="Error message if the tracking lookup failed."
    )
    recovery_guidance: str | None = Field(
        default=None,
        description="Instructions to the assistant on how to guide the customer to recover from an error.",
    )


class ShippingRateResult(BaseModel):
    """Structured response for shipping rate calculation with guided recovery."""

    success: bool = Field(
        description="True if rate calculation succeeded, False otherwise."
    )
    origin: str = Field(default="", description="Origin country or dispatch hub.")
    destination: str = Field(
        default="", description="Destination country or delivery hub."
    )
    weight_kg: float = Field(default=0.0, description="Package weight in kilograms.")
    service_tier: str = Field(default="", description="Calculated service level name.")
    currency: str = Field(default="USD", description="Currency ISO code.")
    base_rate: float = Field(
        default=0.0, description="Base shipping fee before weight add-ons."
    )
    weight_surcharge: float = Field(
        default=0.0, description="Weight-based additional cost."
    )
    total_estimated_cost: float = Field(
        default=0.0, description="Total estimated shipping cost in specified currency."
    )
    estimated_transit_time: str = Field(
        default="", description="Estimated transit window (e.g., '2-3 business days')."
    )
    international: bool = Field(
        default=False, description="True if shipment crosses international borders."
    )
    error: str | None = Field(
        default=None, description="Error message if rate calculation failed."
    )
    recovery_guidance: str | None = Field(
        default=None,
        description="Instructions to the assistant on how to prompt the user for valid shipping parameters.",
    )


class ReturnLabelResult(BaseModel):
    """Structured response for return label creation with guided recovery and validation."""

    success: bool = Field(
        description="True if return authorization succeeded, False otherwise."
    )
    order_id: str = Field(default="", description="The customer order identifier.")
    rma_number: str = Field(
        default="", description="Return Merchandise Authorization code."
    )
    return_status: str = Field(default="", description="Status of the RMA approval.")
    reason: str = Field(
        default="", description="Reason for return provided by the customer."
    )
    return_center: str = Field(
        default="", description="Designated return processing facility."
    )
    label_download_url: str = Field(
        default="", description="Secure URL to download the prepaid shipping PDF label."
    )
    qr_code_dropoff: str = Field(
        default="", description="QR code link for smartphone-based kiosk drop-offs."
    )
    policy_window_days: int = Field(
        default=30, description="Number of days allowed under the return policy."
    )
    instructions: str = Field(
        default="",
        description="Step-by-step instructions for packaging and returning items.",
    )
    requires_human_review: bool = Field(
        default=False,
        description="True if the claim involves high-stakes damage/claim requiring supervisor approval.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if label generation could not be completed.",
    )
    recovery_guidance: str | None = Field(
        default=None,
        description="Instructions to the assistant on how to assist the customer when return creation fails.",
    )


# Sample records for deterministic demo/test evaluation
SAMPLE_TRACKING_DB: dict[str, dict[str, Any]] = {
    "TRACK12345678": {
        "status": "DELIVERED",
        "delivery_date": "2026-09-29T14:32:00Z",
        "signed_by": "J. Doe",
        "origin": "San Francisco, CA, USA",
        "destination": "New York, NY, USA",
        "carrier": "Global Logistics Express",
        "events": [
            {
                "timestamp": "2026-09-27T08:00:00Z",
                "location": "San Francisco, CA",
                "description": "Package picked up",
            },
            {
                "timestamp": "2026-09-28T11:20:00Z",
                "location": "Chicago, IL",
                "description": "In transit at sorting facility",
            },
            {
                "timestamp": "2026-09-29T08:15:00Z",
                "location": "New York, NY",
                "description": "Out for delivery",
            },
            {
                "timestamp": "2026-09-29T14:32:00Z",
                "location": "New York, NY",
                "description": "Delivered to front door",
            },
        ],
    },
    "TRACK87654321": {
        "status": "IN_TRANSIT",
        "delivery_date": "2026-10-02T17:00:00Z",
        "signed_by": None,
        "origin": "Tokyo, Japan",
        "destination": "Seattle, WA, USA",
        "carrier": "Global Logistics Express",
        "events": [
            {
                "timestamp": "2026-09-29T10:00:00Z",
                "location": "Tokyo Hub",
                "description": "Export customs cleared",
            },
            {
                "timestamp": "2026-09-30T03:00:00Z",
                "location": "Tokyo Narita Airport",
                "description": "Departed international gateway",
            },
        ],
    },
    "TRACK99999999": {
        "status": "OUT_FOR_DELIVERY",
        "delivery_date": "2026-09-30T19:00:00Z",
        "signed_by": None,
        "origin": "London, UK",
        "destination": "Manchester, UK",
        "carrier": "Global Logistics Express",
        "events": [
            {
                "timestamp": "2026-09-29T16:00:00Z",
                "location": "London Depot",
                "description": "Processed at local hub",
            },
            {
                "timestamp": "2026-09-30T07:45:00Z",
                "location": "Manchester Depot",
                "description": "Loaded onto delivery vehicle",
            },
        ],
    },
}


def track_package(
    tracking_number: str,
    tool_context: ToolContext,
) -> TrackingResult:
    """Retrieves real-time tracking information, status, and transit history for a shipment.

    Args:
        tracking_number: The unique tracking identifier for the shipment (e.g., TRACK12345678).

    Returns:
        A TrackingResult model with delivery status, milestones, and guided error handling.
    """
    try:
        if not tracking_number or not isinstance(tracking_number, str):
            return TrackingResult(
                success=False,
                error="Missing tracking number.",
                recovery_guidance="Please politely ask the customer to provide a valid tracking number (e.g., 'TRACK12345678').",
            )

        clean_tracking = tracking_number.strip().upper()

        # Guided format validation
        if len(clean_tracking) < 6:
            return TrackingResult(
                success=False,
                tracking_number=clean_tracking,
                error=f"Tracking number '{clean_tracking}' is too short.",
                recovery_guidance="Inform the customer that standard parcel tracking numbers are at least 8 alphanumeric characters, and ask them to verify the receipt or shipping confirmation email.",
            )

        if clean_tracking in SAMPLE_TRACKING_DB:
            record = SAMPLE_TRACKING_DB[clean_tracking]
        else:
            # Deterministic fallback simulation for arbitrary tracking numbers
            record = {
                "status": "IN_TRANSIT",
                "delivery_date": "2026-10-03T18:00:00Z",
                "signed_by": None,
                "origin": "Regional Distribution Center",
                "destination": "Customer Destination",
                "carrier": "Global Logistics Express",
                "events": [
                    {
                        "timestamp": "2026-09-29T09:00:00Z",
                        "location": "Origin Hub",
                        "description": "Shipment picked up",
                    },
                    {
                        "timestamp": "2026-09-30T05:30:00Z",
                        "location": "Intermediate Hub",
                        "description": "In transit to sorting facility",
                    },
                ],
            }

        raw_events = record.get("events")
        transit_events = (
            [TransitEvent(**ev) for ev in raw_events if isinstance(ev, dict)]
            if isinstance(raw_events, list)
            else []
        )

        # Persist context into session state for natural multi-turn follow-ups
        if tool_context and hasattr(tool_context, "state"):
            tool_context.state["last_tracking_number"] = clean_tracking
            tool_context.state["last_package_status"] = record["status"]

        return TrackingResult(
            success=True,
            tracking_number=clean_tracking,
            shipping_status=record["status"],
            carrier=record["carrier"],
            estimated_delivery=record["delivery_date"],
            signed_by=record["signed_by"],
            origin=record["origin"],
            destination=record["destination"],
            recent_events=transit_events,
        )

    except Exception as e:
        logger.error(
            "Error executing track_package for '%s': %s",
            tracking_number,
            e,
            exc_info=True,
        )
        return TrackingResult(
            success=False,
            tracking_number=str(tracking_number),
            error=f"Internal tracking service error: {e}",
            recovery_guidance="Apologize for the technical glitch, reassure the customer that their package is safe, and invite them to retry in a few moments or provide an alternative order number.",
        )


def calculate_shipping_rate(
    origin_country: str,
    destination_country: str,
    weight_kg: float,
    service_tier: str,
    tool_context: ToolContext,
) -> ShippingRateResult:
    """Calculates estimated shipping costs, surcharges, and transit times between countries.

    Args:
        origin_country: Country where shipment originates (e.g., 'USA', 'Japan', 'UK').
        destination_country: Country where shipment is delivered (e.g., 'USA', 'Germany', 'Japan').
        weight_kg: Total package weight in kilograms.
        service_tier: Desired service level: 'standard', 'express', or 'overnight'.

    Returns:
        A ShippingRateResult model with base rate, surcharge, total cost, and guided recovery.
    """
    try:
        # Input validation with guided error handling
        if not origin_country or not destination_country:
            return ShippingRateResult(
                success=False,
                error="Origin and destination countries must both be specified.",
                recovery_guidance="Politely ask the customer to clarify both the sending country and the destination country.",
            )

        try:
            numeric_weight = float(weight_kg)
        except (ValueError, TypeError):
            return ShippingRateResult(
                success=False,
                error=f"Invalid weight format: '{weight_kg}'.",
                recovery_guidance="Ask the customer for the estimated package weight as a number in kilograms (e.g., 2.5 kg).",
            )

        if numeric_weight <= 0:
            return ShippingRateResult(
                success=False,
                weight_kg=numeric_weight,
                error="Weight must be greater than 0 kg.",
                recovery_guidance="Inform the customer that packages must have a positive weight, and request an approximate parcel weight.",
            )

        if numeric_weight > 100.0:
            return ShippingRateResult(
                success=False,
                weight_kg=numeric_weight,
                error="Parcel exceeds the standard 100 kg weight limit.",
                recovery_guidance="Explain that shipments over 100 kg are classified as heavy freight. Guide the user to contact the specialized Freight & Cargo Logistics department.",
            )

        is_international = (
            origin_country.strip().lower() != destination_country.strip().lower()
        )
        tier_clean = service_tier.strip().lower() if service_tier else "standard"

        if "overnight" in tier_clean:
            base_rate = 45.0 if is_international else 25.0
            per_kg_rate = 12.0 if is_international else 6.0
            transit_days = "Next business day by 10:30 AM"
            tier_name = "Overnight Express"
        elif "express" in tier_clean or "priority" in tier_clean:
            base_rate = 28.0 if is_international else 15.0
            per_kg_rate = 8.0 if is_international else 4.0
            transit_days = "2-3 business days"
            tier_name = "Priority Express"
        else:
            base_rate = 15.0 if is_international else 8.0
            per_kg_rate = 5.0 if is_international else 2.5
            transit_days = (
                "5-7 business days" if is_international else "3-5 business days"
            )
            tier_name = "Standard Ground"

        weight_surcharge = round(numeric_weight * per_kg_rate, 2)
        total_cost = round(base_rate + weight_surcharge, 2)

        if tool_context and hasattr(tool_context, "state"):
            tool_context.state["last_quote_tier"] = tier_name
            tool_context.state["last_quote_cost"] = total_cost

        return ShippingRateResult(
            success=True,
            origin=origin_country.strip(),
            destination=destination_country.strip(),
            weight_kg=numeric_weight,
            service_tier=tier_name,
            currency="USD",
            base_rate=base_rate,
            weight_surcharge=weight_surcharge,
            total_estimated_cost=total_cost,
            estimated_transit_time=transit_days,
            international=is_international,
        )

    except Exception as e:
        logger.error("Error calculating shipping rate: %s", e, exc_info=True)
        return ShippingRateResult(
            success=False,
            error=f"Rate calculation error: {e}",
            recovery_guidance="Apologize to the customer and offer to check standard flat-rate options or calculate again with specific origin/destination addresses.",
        )


def create_return_label(
    order_id: str,
    reason: str,
    tool_context: ToolContext,
) -> ReturnLabelResult:
    """Generates a return merchandise authorization (RMA) number and prepaid return shipping label.

    Args:
        order_id: Customer's original order identifier (e.g., ORD-98765).
        reason: Stated reason for returning items (e.g., 'damaged', 'wrong item', 'defective', 'unwanted').

    Returns:
        A ReturnLabelResult model with RMA number, label link, instructions, and human review flag.
    """
    try:
        if not order_id or not isinstance(order_id, str):
            return ReturnLabelResult(
                success=False,
                error="Order identifier is required to generate a return.",
                recovery_guidance="Ask the customer to provide their original order ID (e.g., ORD-12345) from their purchase confirmation email.",
            )

        clean_order = order_id.strip().upper()
        if not re.match(r"^[A-Z0-9_-]{4,25}$", clean_order):
            return ReturnLabelResult(
                success=False,
                order_id=clean_order,
                error=f"Order ID '{clean_order}' is invalid.",
                recovery_guidance="Explain that valid order IDs consist of letters, numbers, and dashes (4-25 characters), and ask the user to double check.",
            )

        # Flag high-stakes returns (damaged items, high-value claims) for human approval hook
        requires_review = any(
            w in (reason or "").lower()
            for w in [
                "damage",
                "defect",
                "broken",
                "claim",
                "expensive",
                "lost",
                "fraud",
            ]
        )

        rma_number = f"RMA-2026-{abs(hash(clean_order)) % 900000 + 100000}"

        if tool_context and hasattr(tool_context, "state"):
            tool_context.state["last_rma_number"] = rma_number
            tool_context.state["last_return_order_id"] = clean_order

        instructions = (
            "Print the prepaid return label or present the mobile QR code at any authorized drop-off station. "
            "Pack items securely in original packaging and dispatch within 14 days of RMA issuance."
        )
        if requires_review:
            instructions += " Note: High-priority damaged item claims are routed to a human claims specialist for formal review within 24 hours."

        return ReturnLabelResult(
            success=True,
            order_id=clean_order,
            rma_number=rma_number,
            return_status="APPROVED_PENDING_INSPECTION"
            if requires_review
            else "APPROVED",
            reason=reason or "Customer requested return",
            return_center="Global Logistics Returns Facility, Dock 4, Tokyo Hub, 135-0064",
            label_download_url=f"https://shipping.example.com/returns/label/{rma_number}.pdf",
            qr_code_dropoff=f"https://shipping.example.com/returns/qr/{rma_number}.png",
            policy_window_days=30,
            instructions=instructions,
            requires_human_review=requires_review,
        )

    except Exception as e:
        logger.error(
            "Error creating return label for order '%s': %s", order_id, e, exc_info=True
        )
        return ReturnLabelResult(
            success=False,
            order_id=str(order_id),
            error=f"Failed to generate return label: {e}",
            recovery_guidance="Apologize for the delay and assure the customer that their return window will be honored. Advise them to contact direct support if urgent.",
        )
