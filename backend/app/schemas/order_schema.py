# backend/app/schemas/order_schema.py
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class OrderOut(BaseModel):
    id: str = Field(alias="_id")
    order_id: str = Field(alias="dpOrderId")  # Fallback handled in logic
    date: datetime = Field(alias="orderDate")
    platform: str
    status: str
    order_online_offline_type: str = "Online"

    # Financials
    item_total: float
    gst_amount: float
    platform_fee: float
    net_payout: float
    settlement_status: str

    # Context (Can be null if list view doesn't load them)
    items: Optional[List[Dict[str, Any]]] = None
    customer: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}
