from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# ------------------------------------------------------------
# 🟢 1. VIEW SCHEMAS (Reading from 'payoutorders')
# ------------------------------------------------------------


class BreakdownSchema(BaseModel):
    """Details for the tooltip (Commission, Tax, etc.)"""

    commission: float = 0.0
    tax: float = 0.0
    deductions: float = 0.0


class SettlementOut(BaseModel):
    """
    Represents a single verified settlement from 'payoutorders'.
    Mapped from SettlementService.get_settlements()
    """

    id: str
    order_id: str
    platform: str
    order_date: Optional[datetime] = None

    # Settlement Details
    settlement_date: Optional[datetime] = None
    status: str = "PENDING"
    transaction_id: str = "N/A"

    # Financials
    order_amount: float = 0.0  # Customer Paid
    net_payout: float = 0.0  # Bank Received
    platform_fees: float = 0.0  # Total Deductions

    # Nested breakdown for UI hover details
    breakdown: Optional[BreakdownSchema] = None

    class Config:
        populate_by_name = True
        json_encoders = {datetime: lambda v: v.isoformat()}


# ------------------------------------------------------------
# 🟡 2. LEGACY/UPLOAD SCHEMAS (Optional)
# Keep these ONLY if you still have an endpoint to upload CSVs manually.
# If 'payoutorders' is populated automatically by the backend, you can remove these.
# ------------------------------------------------------------


class SettlementRowError(BaseModel):
    row_index: int
    order_id: str
    reason: str
    csv_net: float
    db_net: float


class SettlementSummary(BaseModel):
    total_rows: int
    processed: int
    matched_and_settled: int
    mismatches: int
    not_found_in_db: int
    errors: List[SettlementRowError]
