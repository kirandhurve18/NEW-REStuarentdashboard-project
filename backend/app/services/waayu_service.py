# backend/app/services/waayu_service.py
from app.db.mongo import orders_col, waayu_settlements_col
from datetime import datetime
import logging

log = logging.getLogger("waayu_settlement")


async def process_waayu_settlement_logic(record: dict) -> str:
    """
    Core Logic:
    1. Check duplicates.
    2. Find Order in DB (Robust ID Match).
    3. Validate Amount (Tolerance < 1.0).
    4. Update Order & Insert Audit Record.
    """
    # 1. Extract & Sanitize Data
    raw_id = str(record.get("Waayu Order ID", "")).strip()
    payout_amount = float(record.get("Payout Amount", 0))
    utr = record.get("Transaction ID")
    date_str = record.get("Payout Date (DD/MM/YYYY)")

    if not raw_id:
        return "FAILED_NO_ID"

    try:
        settlement_date = datetime.strptime(date_str, "%d/%m/%Y")
    except Exception:
        settlement_date = datetime.utcnow()

    # 2. Idempotency Check
    exists = await waayu_settlements_col.find_one({"waayu_order_id": raw_id})
    if exists:
        return "SKIPPED_DUPLICATE"

    # 3. Find Order (Robust Match Strategy)
    # We check ALL possible ID fields to ensure 0% miss rate
    order = await orders_col.find_one(
        {
            "$or": [
                {"order_id": raw_id},
                {"unique_id": raw_id},
                {"dpOrderId": raw_id},  # Standard ONDC ID
                {"ondcOrderId": raw_id},  # Alternative ONDC ID
                {"payout.ondcOrderId": raw_id},  # Nested check
            ]
        }
    )

    status_log = "FAILED_NOT_FOUND"

    if order:
        # Get the Net Value stored in DB
        # Priority: explicit net_payout > pricing.orderTotal (since Waayu is 0% comm)
        pricing = order.get("pricing", {}) or {}
        db_net = float(order.get("net_payout") or pricing.get("orderTotal", 0))

        diff = abs(db_net - payout_amount)

        # 4. Financial Truth Check
        if diff <= 1.0:
            status_log = "SETTLED"
            update_data = {
                "settlement_status": "SETTLED",  # 🟢 CRITICAL: This field must be respected by API
                "settlement_date": settlement_date,
                "settlement_utr": utr,
                "payout_remark": "Waayu Internal Auto-Settled",
                "reconciliation_notes": "Matched via Internal Logic",
                "payoutDone": True,  # Flag for frontend
                "payment.status": "Paid",
            }
        else:
            status_log = "DISPUTE"
            update_data = {
                "settlement_status": "DISPUTE",
                "settlement_date": settlement_date,
                "settlement_utr": utr,
                "reconciliation_notes": f"Mismatch: DB {db_net} vs Waayu {payout_amount}",
            }

        # 5. Update Order
        await orders_col.update_one({"_id": order["_id"]}, {"$set": update_data})

    # 6. Save Audit Record
    record["processed_at"] = datetime.utcnow()
    record["reconciliation_status"] = status_log
    record["waayu_order_id"] = raw_id  # Ensure we save the sanitized ID

    try:
        await waayu_settlements_col.insert_one(record)
    except Exception:
        pass

    return status_log
