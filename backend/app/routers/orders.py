from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timedelta

from app.db.mongo import orders_col, stores_col
from app.dependencies import get_current_user
from app.utils.logger import setup_logger
from app.models.order_model import OrderModel

router = APIRouter(tags=["Orders"])
log = setup_logger("orders_router")


@router.get("/orders", response_model=List[OrderModel])
async def get_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = None,
    platform: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    search: Optional[str] = None,
    current_user: dict = Depends(get_current_user),
):
    """
    Fetches LIVE orders via aggregation.
    - Joins 'orderitems' for item details.
    - Joins 'payoutorders' for exact settlement data.
    - Falls back to 'restaurants' config for estimated commissions.
    """
    try:
        # 1. Auth & Context
        rest_oid_str = current_user.get("restaurant_oid")
        if not rest_oid_str:
            return []

        restaurant_id = ObjectId(rest_oid_str)

        # 2. Build Filter Query
        match_query = {"restaurant": restaurant_id}

        # Date Filter: Use inputs or default to Last 30 Days
        if start_date and end_date:
            try:
                # Handle 'Z' suffix or simple ISO format
                s_date = datetime.fromisoformat(start_date.replace("Z", ""))
                e_date = datetime.fromisoformat(end_date.replace("Z", ""))
                match_query["orderDate"] = {"$gte": s_date, "$lte": e_date}
            except ValueError:
                pass
        else:
            # Default to last 30 days if no filter provided
            now = datetime.utcnow()
            match_query["orderDate"] = {"$gte": now - timedelta(days=30)}

        # Status Filter (Map Dashboard Status -> Live Schema)
        if status:
            s_upper = status.upper()
            if s_upper == "COMPLETED":
                match_query["status.orderStatus"] = {
                    "$in": ["delivered", "COMPLETED", "closed"]
                }
            elif s_upper == "CANCELLED":
                match_query["status.orderStatus"] = {
                    "$in": ["cancelled", "rejected", "CANCELLED"]
                }
            else:
                match_query["status.orderStatus"] = {
                    "$regex": f"^{status}",
                    "$options": "i",
                }

        if platform:
            match_query["platform"] = platform.lower()

        if search:
            match_query["$or"] = [
                {"dpOrderId": {"$regex": search, "$options": "i"}},
                {"customer.receiverName": {"$regex": search, "$options": "i"}},
                {"ondcOrderId": {"$regex": search, "$options": "i"}},
            ]

        # 3. Fetch Config for Commission Learning (Fallback)
        restaurant_config = await stores_col.find_one(
            {"_id": restaurant_id}, {"commercials": 1}
        )
        commercials = (
            restaurant_config.get("commercials", {}) if restaurant_config else {}
        )

        swiggy_pct = float(commercials.get("swiggy_commission", 24.0))
        zomato_pct = float(commercials.get("zomato_commission", 24.0))

        # 4. Aggregation Pipeline
        pipeline = [
            {"$match": match_query},
            {"$sort": {"orderDate": -1}},
            {"$skip": (page - 1) * limit},
            {"$limit": limit},
            # JOIN 1: Items (orderitems)
            {
                "$lookup": {
                    "from": "orderitems",
                    "localField": "_id",
                    "foreignField": "orderId",
                    "as": "items_data",
                }
            },
            # JOIN 2: Payout Truth (payoutorders)
            {
                "$lookup": {
                    "from": "payoutorders",
                    "localField": "payoutOrderRef",
                    "foreignField": "_id",
                    "as": "payout_data",
                }
            },
            # TRANSFORM: Flatten & Project necessary fields
            {
                "$project": {
                    "_id": {"$toString": "$_id"},
                    "dpOrderId": "$dpOrderId",
                    "ondcOrderId": "$ondcOrderId",
                    "orderDate": "$orderDate",
                    "platform": "$platform",
                    "status": "$status",  # Passed as object, Model flattens it
                    "onlineOffline": "$onlineOffline",
                    "pricing": "$pricing",  # Passed as object, Model flattens it
                    "payoutDone": "$payoutDone",
                    # Payout Info (Array -> Single Object)
                    "payout_info": {"$arrayElemAt": ["$payout_data", 0]},
                    # Flatten Items for UI
                    "items": {
                        "$map": {
                            "input": "$items_data",
                            "as": "item",
                            "in": {
                                "name": "$$item.product.title",
                                "quantity": "$$item.quantity",
                                "price": "$$item.pricing.finalPrice",
                                "addons": "$$item.customization.addons",
                            },
                        }
                    },
                    "customer": {
                        "name": "$customer.receiverName",
                        "phone": "$customer.receiverMobile",
                    },
                }
            },
        ]

        raw_orders = await orders_col.aggregate(pipeline).to_list(length=limit)

        # 5. Commission Logic (Hybrid)
        final_response = []
        for doc in raw_orders:
            # Extract basic financials
            pricing = doc.get("pricing", {}) or {}
            item_total = float(pricing.get("subtotal", 0.0) or 0.0)
            gross_total = float(pricing.get("orderTotal", 0.0) or 0.0)

            payout_info = doc.get("payout_info")
            platform_lower = str(doc.get("platform", "")).lower()

            platform_fee = 0.0
            net_payout = 0.0
            settlement_status = "PENDING"

            # A) TRUTH: Payout Order Exists
            if payout_info:
                # Use exact values from settlement
                fees = payout_info.get("platformFees", {})
                platform_fee = (
                    float(fees.get("commission", 0))
                    + float(fees.get("serviceFee", 0))
                    + float(fees.get("paymentGatewayFee", 0))
                )

                payout_details = payout_info.get("payout", {})
                if payout_details.get("payoutStatus") == "paid":
                    settlement_status = "SETTLED"
                    net_payout = float(payout_details.get("settlementAmount", 0))
                else:
                    # Pending but we know the deductions
                    cust_payable = float(
                        payout_info.get("customerPayable", {}).get("orderTotal", 0)
                    )
                    deductions = float(
                        payout_info.get("adjustments", {}).get("deductions", 0)
                    )
                    net_payout = cust_payable - platform_fee - deductions

            # B) ESTIMATE: Fallback to Config
            else:
                est_pct = 0.0
                if "swiggy" in platform_lower:
                    est_pct = swiggy_pct
                elif "zomato" in platform_lower:
                    est_pct = zomato_pct

                # Formula: (Subtotal * %) + GST on Comm (18%)
                base_comm = item_total * (est_pct / 100.0)
                tax_on_comm = base_comm * 0.18
                platform_fee = base_comm + tax_on_comm

                # Net = Gross - Fees
                net_payout = gross_total - platform_fee
            # --- PRIORITY 1: Check if already Settled Internally (Waayu) ---
            # This ensures we respect the "SETTLED" status from waayu_service.py
            stored_status = doc.get("settlement_status")
            if stored_status in ["SETTLED", "DISPUTE"]:
                settlement_status = stored_status
                # If settled, trust the stored net_payout if available
                if doc.get("net_payout"):
                    net_payout = float(doc.get("net_payout"))
                else:
                    # Waayu is 0% commission, so Net = Gross
                    net_payout = gross_total

            # --- PRIORITY 2: Check Payout Order (Zomato/Swiggy CSV) ---
            elif payout_info:
                fees = payout_info.get("platformFees", {})
                platform_fee = (
                    float(fees.get("commission", 0))
                    + float(fees.get("serviceFee", 0))
                    + float(fees.get("paymentGatewayFee", 0))
                )

                payout_details = payout_info.get("payout", {})
                if payout_details.get("payoutStatus") == "paid":
                    settlement_status = "SETTLED"
                    net_payout = float(payout_details.get("netPayout", 0))
                    # Fallback if CSV netPayout is missing
                    if net_payout == 0:
                        net_payout = float(payout_details.get("settlementAmount", 0))
                else:
                    # Pending but we know the deductions
                    cust_payable = float(
                        payout_info.get("customerPayable", {}).get("orderTotal", 0)
                    )
                    deductions = float(
                        payout_info.get("adjustments", {}).get("deductions", 0)
                    )
                    net_payout = cust_payable - platform_fee - deductions

            # --- PRIORITY 3: Estimate (Fallback) ---
            else:
                est_pct = 0.0
                if "swiggy" in platform_lower:
                    est_pct = swiggy_pct
                elif "zomato" in platform_lower:
                    est_pct = zomato_pct
                elif "waayu" in platform_lower:
                    est_pct = 0.0  # 🟢 Explicit 0% for Waayu

                # Formula: (Subtotal * %) + GST on Comm (18%)
                if est_pct > 0:
                    base_comm = item_total * (est_pct / 100.0)
                    tax_on_comm = base_comm * 0.18
                    platform_fee = base_comm + tax_on_comm
                else:
                    platform_fee = 0.0

                # Net = Gross - Fees
                net_payout = gross_total - platform_fee

            # Inject calculated fields
            doc["platform_fee"] = round(platform_fee, 2)
            doc["net_payout"] = round(net_payout, 2)
            doc["settlement_status"] = settlement_status

            # Map ID fallback for Model
            if not doc.get("dpOrderId") and doc.get("ondcOrderId"):
                doc["dpOrderId"] = doc["ondcOrderId"]

            final_response.append(doc)

        return final_response

    except Exception as e:
        log.error(f"Error fetching orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))
