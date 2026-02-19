# backend/app/services/settlement_service.py

from typing import List, Dict, Any, Optional
from bson import ObjectId
from datetime import datetime
from app.db.mongo import payouts_col, stores_col, orders_col
from app.utils.logger import setup_logger

log = setup_logger("settlement_service")


class SettlementService:
    """
    Handles Financial Data Retrieval, Ingestion, and Auto-Learning.
    """

    async def get_settlements(
        self,
        restaurant_oid: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        platform: Optional[str] = None,
        limit: int = 50,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        Fetches verified settlements from the 'payoutorders' collection.
        """
        if not restaurant_oid:
            return []

        query = {"restaurantRef": ObjectId(restaurant_oid)}

        if start_date and end_date:
            query["payout.payoutDate"] = {"$gte": start_date, "$lte": end_date}

        if platform:
            query["platform"] = platform.lower()

        cursor = (
            payouts_col.find(query)
            .sort("payout.payoutDate", -1)
            .skip(skip)
            .limit(limit)
        )
        results = await cursor.to_list(length=limit)

        # Convert ObjectId to string for JSON serialization
        for r in results:
            if "_id" in r:
                r["_id"] = str(r["_id"])
            if "restaurantRef" in r:
                r["restaurantRef"] = str(r["restaurantRef"])

        return results

    # app/services/settlement_service.py

    async def sync_payouts(
        self, restaurant_oid: str, platform: str, data: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """
        Ingests parsed settlement rows AND Auto-Learns Commission Rates.
        """
        inserted = 0
        updated = 0
        matched_orders = 0

        # 🟢 Variables for Auto-Learning Commission (Batch Average)
        batch_total_sales = 0.0
        batch_total_fee = 0.0

        for row in data:
            order_id = row["order_id"]

            # Extract Financials for Learning
            sales = float(row.get("item_total", 0) or 0)
            fee = float(row.get("platform_fee", 0) or 0)

            # Accumulate if valid
            if sales > 0:
                batch_total_sales += sales
                batch_total_fee += fee

            # 1. Prepare Payout Document
            payout_doc = {
                "restaurantRef": ObjectId(restaurant_oid),
                "ondcOrderId": order_id,
                "orderDate": datetime.utcnow(),
                "orderStatus": row.get("status", "settled"),
                "platform": platform.lower(),
                "customerPayable": {
                    "itemTotal": row["item_total"],
                    "orderTotal": row["net_amount"] + row["platform_fee"],
                },
                "platformFees": {
                    "commission": row["platform_fee"],
                    "serviceFee": 0,
                },
                "payout": {
                    "netPayout": row["net_amount"],
                    "payoutStatus": "paid",
                    "payoutDate": datetime.utcnow(),
                    "utr": row.get("utr", "N/A"),
                },
                "last_updated": datetime.utcnow(),
            }

            # 2. Upsert into Payouts
            res = await payouts_col.update_one(
                {"ondcOrderId": order_id, "platform": platform.lower()},
                {"$set": payout_doc},
                upsert=True,
            )

            # 🟢 CRITICAL FIX: Robustly resolve the Payout ID
            payout_id = res.upserted_id

            if payout_id:
                inserted += 1
            else:
                updated += 1
                # If updated, upserted_id is None, so we MUST fetch the existing ID
                existing_doc = await payouts_col.find_one(
                    {"ondcOrderId": order_id, "platform": platform.lower()}, {"_id": 1}
                )
                if existing_doc:
                    payout_id = existing_doc["_id"]

            # 3. LINK TO LIVE ORDERS (Now with Reference!)
            if payout_id:
                link_res = await orders_col.update_one(
                    {"dpOrderId": order_id},
                    {
                        "$set": {
                            "payoutDone": True,
                            "payment.status": "Paid",
                            "payoutOrderRef": payout_id,  # 🟢 THE MISSING LINK
                        }
                    },
                )
                if link_res.modified_count > 0:
                    matched_orders += 1

        # 4. TRIGGER AUTO-LEARNING
        if batch_total_sales > 0:
            await self._update_commission_from_batch(
                restaurant_oid, platform, batch_total_sales, batch_total_fee
            )

        log.info(
            f"✅ Synced {platform} for {restaurant_oid}: +{inserted}, ~{updated}, Linked: {matched_orders}"
        )
        return {
            "inserted": inserted,
            "updated": updated,
            "linked_orders": matched_orders,
        }

    async def _update_commission_from_batch(
        self, restaurant_oid: str, platform: str, total_sales: float, total_fee: float
    ):
        """
        Internal: Calculates weighted average commission from the batch and updates Store Config.
        """
        if total_sales <= 0:
            return

        # Calculate % (e.g., 23.54)
        calc_pct = round((total_fee / total_sales) * 100, 2)

        # Sanity Check (10% to 45%) - prevents bad data from ruining config
        if 10 <= calc_pct <= 45:
            # Construct Dynamic Key (e.g., commercials.zomato_commission)
            platform_key = platform.lower()
            config_key = f"commercials.{platform_key}_commission"

            await stores_col.update_one(
                {"_id": ObjectId(restaurant_oid)},
                {"$set": {config_key: calc_pct}},
                upsert=True,
            )
            log.info(f"🧠 Auto-Learned Commission for {platform}: {calc_pct}%")


settlement_service = SettlementService()
