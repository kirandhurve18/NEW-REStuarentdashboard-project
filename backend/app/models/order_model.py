# backend/app/models/order_model.py
from pydantic import BaseModel, Field, root_validator
from typing import Optional, List, Dict, Any
from datetime import datetime


class OrderModel(BaseModel):
    id: str = Field(alias="_id", default=None)

    # Map 'dpOrderId' (Live) -> 'order_id' (Dashboard)
    order_id: str = Field(alias="dpOrderId", default="N/A")

    # Live uses String ID (waayuRestId), not Int
    tenant_id: str = Field(default="0")

    # Map 'orderDate' -> 'date'
    date: datetime = Field(alias="orderDate", default_factory=datetime.utcnow)

    # Flattened Fields
    status: str = "PENDING"
    delivery_platform: str = Field(alias="platform", default="waayu")
    order_online_offline_type: str = "Online"

    # 🟢 Financials
    item_total: float = 0.0  # Mapped from pricing.subtotal
    gst_amount: float = 0.0  # Mapped from pricing.tax
    net_payout: float = 0.0  # Calculated or from Payout Ref
    platform_fee: float = 0.0  # Mapped from pricing.vendorCommission

    # 🟢 Settlement Info (Often missing in live neworders, filled via service)
    settlement_status: str = "PENDING"

    # 🟢 Context
    items: Optional[List[Dict[str, Any]]] = None  # Populated via $lookup
    customer: Optional[Dict[str, Any]] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}

    @root_validator(pre=True)
    def flatten_live_data(cls, values):
        """
        Adapts the Nested 'neworders' schema to the Flat Dashboard Schema
        """
        # 1. Flatten Status
        # Live: { "status": { "orderStatus": "COMPLETED" } }
        status_obj = values.get("status")
        if isinstance(status_obj, dict):
            values["status"] = status_obj.get("orderStatus", "PENDING")

        # 2. Flatten Financials
        # Live: { "pricing": { "subtotal": 100, "tax": 5 } }
        pricing = values.get("pricing")
        if isinstance(pricing, dict):
            values["item_total"] = float(pricing.get("subtotal", 0.0))
            values["gst_amount"] = float(pricing.get("tax", 0.0))
            values["platform_fee"] = float(pricing.get("vendorCommission", 0.0))

            # Logic: If payoutDone is True, assume Settled
            if values.get("payoutDone") is True:
                values["settlement_status"] = "SETTLED"

        # 3. Flatten Online/Offline
        # [cite_start]Live: 1=Online, 2=Offline [cite: 447]
        oo_val = values.get("onlineOffline")
        if oo_val == 2:
            values["order_online_offline_type"] = "Dine-in"
        else:
            values["order_online_offline_type"] = "Online"

        # 4. Handle ID fallback
        if not values.get("dpOrderId") and values.get("ondcOrderId"):
            values["dpOrderId"] = values["ondcOrderId"]

        return values
