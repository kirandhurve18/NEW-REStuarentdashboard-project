# backend/app/schemas/waayu_schema.py
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime


class WaayuSettlementRecord(BaseModel):
    waayu_order_id: str = Field(..., alias="Waayu Order ID")
    payout_amount: float = Field(..., alias="Payout Amount")
    transaction_id: str = Field(..., alias="Transaction ID")
    payout_date_str: str = Field(..., alias="Payout Date (DD/MM/YYYY)")
    payment_status: str = Field(..., alias="Payment Status")

    # Internal fields filled after processing
    processed_at: Optional[datetime] = None
    reconciliation_status: Optional[str] = None

    @validator("payout_amount", pre=True)
    def clean_amount(cls, v):
        if isinstance(v, str):
            # Remove commas and handle empty strings
            clean_str = v.replace(",", "").strip()
            return float(clean_str) if clean_str else 0.0
        return v

    @validator("payout_date_str")
    def validate_date_format(cls, v):
        # We don't convert to datetime object here to keep the schema simple,
        # but we validate the format matches the CSV
        try:
            datetime.strptime(v, "%d/%m/%Y")
            return v
        except ValueError:
            raise ValueError("Date must be in DD/MM/YYYY format")
