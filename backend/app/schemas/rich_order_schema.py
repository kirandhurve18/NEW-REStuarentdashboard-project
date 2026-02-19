# backend/app/schemas/rich_order_schema.py

from pydantic import BaseModel
from typing import List, Optional, Union, Dict, Any
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. SUB-MODELS (The "Rich" Details)
# -----------------------------------------------------------------------------


class OrderItem(BaseModel):
    item_id: str
    name: str
    price: float
    quantity: int
    final_price: float
    is_vegetarian: Optional[bool] = None
    addons: List[str] = []


class CustomerDetails(BaseModel):
    name: Optional[str] = "Guest"
    phone: Optional[str] = None
    address: Optional[str] = None
    coordinates: Optional[Dict[str, float]] = None


class OrderTimeline(BaseModel):
    placed_at: datetime
    accepted_at: Optional[datetime] = None
    cooking_started_at: Optional[datetime] = None
    ready_for_pickup_at: Optional[datetime] = None
    dispatched_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None


# -----------------------------------------------------------------------------
# 2. THE MASTER INPUT SCHEMA (Ingest Payload)
# -----------------------------------------------------------------------------
class RichOrderIngest(BaseModel):
    # --- ANCHOR FIELDS (Matches your current simple data) ---
    external_id: str
    platform: str
    status: Union[str, int]  # Supports "5", 5, "COMPLETED"
    total_amount: float  # Gross Bill (Cash collected)
    created_at: datetime

    # --- OPTIONAL OVERRIDES (For precise calculation) ---
    tax_amount: Optional[float] = None
    platform_fee: Optional[float] = None
    order_type: Optional[str] = None

    # --- RICH CONTEXT (New fields for Real Data / AI) ---
    # These default to empty/None so your current dummy data script won't break.
    items: List[OrderItem] = []
    customer: Optional[CustomerDetails] = None
    timeline: Optional[OrderTimeline] = None

    # Extra Financial Granularity (From SQL columns)
    delivery_charges: float = 0.0
    packaging_charges: float = 0.0
    discount_amount: float = 0.0

    # Audit Trail
    source_raw: Optional[Dict[str, Any]] = None
