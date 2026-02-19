# backend/app/services/kpi_service.py

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from calendar import monthrange
from bson import ObjectId

from app.db.mongo import orders_col, order_items_col, payouts_col, stores_col
from app.utils.logger import setup_logger

log = setup_logger("kpi_service")

# 🟢 DEFINE IST TIMEZONE (UTC + 5:30) for strict Indian context
IST = timezone(timedelta(hours=5, minutes=30))


class KPIService:
    """
    Production-Grade Analytics Engine (v2.2 - Final).
    - Fixed Cost Proration: Accurate to the day.
    - Commissions: Smart Hybrid (Real Payouts > Estimated on Aggregators ONLY).
    - Metrics: Includes Net Sales & Lost Revenue.
    """

    # ---------------------------------------------------------
    # 1. HELPERS
    # ---------------------------------------------------------
    def _calculate_exact_fixed_cost(
        self, monthly_cost: float, start: datetime, end: datetime
    ) -> float:
        """
        Prorates monthly fixed costs (Rent, Salaries) down to the selected date range.
        Accurate to the day, accounting for different month lengths.
        """
        if monthly_cost <= 0:
            return 0.0

        total_cost = 0.0
        current_date = start

        # Iterate through days to handle month boundaries strictly
        while current_date <= end:
            days_in_month = monthrange(current_date.year, current_date.month)[1]
            total_cost += monthly_cost / days_in_month
            current_date += timedelta(days=1)

        return round(total_cost, 2)

    def _build_match_stage(
        self,
        restaurant_oid: ObjectId,
        start: datetime,
        end: datetime,
        status_filter="COMPLETED",
    ) -> Dict[str, Any]:
        """
        Centralized query builder for Live Data.
        """
        query = {
            "restaurant": restaurant_oid,
            "orderDate": {"$gte": start, "$lte": end},
        }

        if status_filter == "COMPLETED":
            # 🟢 FIX: Added "Completed" (Title Case) and "Delivered" (Title Case)
            query["status.orderStatus"] = {
                "$in": [
                    "delivered",
                    "Delivered",
                    "COMPLETED",
                    "Completed",
                    "closed",
                    "Closed",
                    "Paid",
                    "paid",
                ]
            }
        elif status_filter == "CANCELLED":
            # 🟢 FIX: Added variations for Cancellation too
            query["status.orderStatus"] = {
                "$in": [
                    "Cancelled",
                    "cancelled",
                    "Rejected",
                    "rejected",
                    "void",
                    "Void",
                ]
            }

        return {"$match": query}

    def _calc_trend(self, curr: float, prev: float) -> float:
        """
        Calculates percentage change for dashboard arrows.
        """
        if prev == 0:
            return 100.0 if curr > 0 else 0.0
        return round(((curr - prev) / prev) * 100, 1)

    # ---------------------------------------------------------
    # 2. FINANCIAL KPI (The Profit Engine)
    # ---------------------------------------------------------
    async def financial_kpis(
        self, rest_oid_str: Optional[str], start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """
        Aggregates Financials with strict 'Dine-In Protection' logic.
        Returns Nested Structure: { current: {...}, trends: {...} } to match Financial.jsx.
        """
        if not rest_oid_str:
            # Frontend expects specific keys even if empty
            return {"current": {}, "trends": {}}

        rest_id = ObjectId(rest_oid_str)

        # 1. Calculate Metrics for the CURRENT Selected Range
        current_stats = await self._calculate_period_stats(
            rest_id, start_date, end_date
        )

        # 2. Calculate Metrics for the PREVIOUS Range (For Trends)
        # Logic: If user selects "Last 7 Days", we compare vs "Previous 7 Days"
        duration = end_date - start_date
        prev_start = start_date - duration
        prev_end = start_date
        prev_stats = await self._calculate_period_stats(rest_id, prev_start, prev_end)

        # 3. Calculate Percentage Trends (Green/Red Arrows)
        trends = {
            "revenue": self._calc_trend(
                current_stats["revenue"]["total_revenue"],
                prev_stats["revenue"]["total_revenue"],
            ),
            "net_profit": self._calc_trend(
                current_stats["profit"]["net_profit"],
                prev_stats["profit"]["net_profit"],
            ),
            "food_cost": self._calc_trend(
                current_stats["costs"]["food_cost"], prev_stats["costs"]["food_cost"]
            ),
            "platform_cost": self._calc_trend(
                current_stats["costs"]["platform_cost"],
                prev_stats["costs"]["platform_cost"],
            ),
            "online_rev": self._calc_trend(
                current_stats["revenue"]["online_revenue"],
                prev_stats["revenue"]["online_revenue"],
            ),
            "dinein_rev": self._calc_trend(
                current_stats["revenue"]["dinein_revenue"],
                prev_stats["revenue"]["dinein_revenue"],
            ),
        }

        return {"current": current_stats, "trends": trends}

    # ---------------------------------------------------------
    # UPDATED: _calculate_period_stats (Paranoid Robust Version)
    # ---------------------------------------------------------
    async def _calculate_period_stats(
        self, rest_id: ObjectId, start: datetime, end: datetime
    ) -> Dict[str, Any]:

        # A. Get Config
        store_doc = await stores_col.find_one({"_id": rest_id})
        fc_val = 0.0
        comm_cfg = {}

        if store_doc:
            # Fixed Costs Logic
            fc = store_doc.get("fixedCosts", {})
            monthly_total = sum(
                [
                    float(fc.get(k, 0))
                    for k in [
                        "rent",
                        "salaries",
                        "electricity",
                        "maintenance",
                        "miscellaneous",
                    ]
                ]
            )
            fc_val = self._calculate_exact_fixed_cost(monthly_total, start, end)
            comm_cfg = store_doc.get("commercials", {})

        # B. Live Order Aggregation (ROBUST CASE-INSENSITIVE + FALLBACKS)
        pipeline = [
            self._build_match_stage(rest_id, start, end, "COMPLETED"),
            {
                "$project": {
                    "pricing": 1,
                    "platform": 1,
                    # 🟢 NORMALIZE PLATFORM: Lowercase + Trim Spaces
                    "norm_platform": {"$toLower": {"$trim": {"input": "$platform"}}},
                    # 🟢 FALLBACK: If itemTotal is 0/null, use orderTotal
                    "calc_amount": {
                        "$ifNull": ["$pricing.itemTotal", "$pricing.orderTotal"]
                    },
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_revenue": {"$sum": "$pricing.orderTotal"},
                    # Channels
                    "online_revenue": {
                        "$sum": {
                            "$cond": [
                                {"$ne": ["$norm_platform", "offline"]},
                                "$pricing.orderTotal",
                                0,
                            ]
                        }
                    },
                    "dinein_revenue": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$norm_platform", "offline"]},
                                "$pricing.orderTotal",
                                0,
                            ]
                        }
                    },
                    # 🟢 FIX: Use Normalized Platform + Fallback Amount
                    "zomato_sales": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$norm_platform", "zomato"]},
                                "$calc_amount",  # Uses ItemTotal (or OrderTotal if missing)
                                0,
                            ]
                        }
                    },
                    "swiggy_sales": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$norm_platform", "swiggy"]},
                                "$calc_amount",
                                0,
                            ]
                        }
                    },
                }
            },
        ]

        res = await orders_col.aggregate(pipeline).to_list(1)
        data = res[0] if res else {}

        # C. Commission Logic

        # 1. Check Bank Payouts
        payout_pipeline = [
            {
                "$match": {
                    "restaurantRef": rest_id,
                    "payout.payoutDate": {"$gte": start, "$lte": end},
                    "payout.payoutStatus": "paid",
                }
            },
            {
                "$group": {
                    "_id": "$platform",
                    "real_commission": {"$sum": "$platformFees.commission"},
                }
            },
        ]
        payout_res = await payouts_col.aggregate(payout_pipeline).to_list(None)

        # Normalize Payout Keys
        real_costs = (
            {str(p["_id"]).lower().strip(): p["real_commission"] for p in payout_res}
            if payout_res
            else {}
        )

        platform_cost_zomato = 0.0
        platform_cost_swiggy = 0.0

        # --- ZOMATO CALCULATION ---
        if "zomato" in real_costs:
            platform_cost_zomato = real_costs["zomato"]
        else:
            # Fallback to Configured %
            zom_pct = float(
                comm_cfg.get(
                    "zomato_commission", comm_cfg.get("Zomato_commission", 24.0)
                )
            )
            platform_cost_zomato = data.get("zomato_sales", 0) * (zom_pct / 100.0)

        # --- SWIGGY CALCULATION ---
        if "swiggy" in real_costs:
            platform_cost_swiggy = real_costs["swiggy"]
        else:
            # Fallback to Configured %
            swig_pct = float(
                comm_cfg.get(
                    "swiggy_commission", comm_cfg.get("Swiggy_commission", 24.0)
                )
            )
            platform_cost_swiggy = data.get("swiggy_sales", 0) * (swig_pct / 100.0)

        total_platform_cost = platform_cost_zomato + platform_cost_swiggy

        # D. Food Cost Estimation (Dynamic)
        total_rev = data.get("total_revenue", 0)

        # 🟢 NEW: Get % from Config (Default 30%)
        fc_pct = float(comm_cfg.get("food_cost_percentage", 30))

        # Calculate Logic: (Revenue * %) / 100
        food_cost = total_rev * (fc_pct / 100.0)
        net_profit = total_rev - fc_val - total_platform_cost - food_cost

        return {
            "revenue": {
                "total_revenue": round(total_rev, 2),
                "online_revenue": round(data.get("online_revenue", 0), 2),
                "dinein_revenue": round(data.get("dinein_revenue", 0), 2),
            },
            "costs": {
                "fixed_cost": round(fc_val, 2),
                "platform_cost": round(total_platform_cost, 2),
                "food_cost": round(food_cost, 2),
                "platform_fee_breakdown": {
                    "Zomato": round(platform_cost_zomato, 2),
                    "Swiggy": round(platform_cost_swiggy, 2),
                },
            },
            "profit": {"net_profit": round(net_profit, 2)},
        }

    # ---------------------------------------------------------
    # 3. NON-FINANCIAL KPI (Growth Engine)
    # ---------------------------------------------------------
    async def non_financial_kpis(
        self, rest_oid_str: Optional[str], start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """
        Matches Frontend: /non-financial
        Returns ARRAYS [] for Recharts (Fixes White Screen).
        Includes: Hourly Trends, Platform Mix, and Lost Revenue.
        """
        if not rest_oid_str:
            return self._empty_non_financials()

        rest_id = ObjectId(rest_oid_str)
        match = self._build_match_stage(rest_id, start_date, end_date, "COMPLETED")

        # A. Platform Distribution (Frontend: platform_distribution)
        # 🟢 UPDATED: Now includes 'recent_orders' for the 'i' button Modal
        mix_pipeline = [
            match,
            # 1. Sort by Date Descending (Latest First)
            {"$sort": {"orderDate": -1}},
            {
                "$group": {
                    "_id": "$platform",
                    "order_count": {"$sum": 1},
                    "total_revenue": {"$sum": "$pricing.orderTotal"},
                    # 🟢 NEW: Push individual order details
                    "recent_orders": {
                        "$push": {
                            "order_id": "$dpOrderId",  # ID shown in modal
                            "amount": "$pricing.orderTotal",  # Amount shown in modal
                            "date": "$orderDate",  # For sorting/reference
                        }
                    },
                }
            },
            # 2. Limit array size to top 20 to keep response fast
            {"$addFields": {"recent_orders": {"$slice": ["$recent_orders", 20]}}},
        ]
        mix_res = await orders_col.aggregate(mix_pipeline).to_list(None)

        # B. Hourly Distribution (Frontend: hourly_distribution)
        # 🟢 NEW: Required for "Peak Traffic" Bar Chart
        hourly_pipeline = [
            match,
            {
                "$project": {
                    "hour": {
                        "$hour": {"date": "$orderDate", "timezone": "Asia/Kolkata"}
                    }
                }
            },
            {"$group": {"_id": "$hour", "orders": {"$sum": 1}}},
            {"$sort": {"_id": 1}},
        ]
        hourly_res = await orders_col.aggregate(hourly_pipeline).to_list(None)
        hourly_data = [{"hour": h["_id"], "orders": h["orders"]} for h in hourly_res]

        # C. Day Wise Revenue (Frontend: day_wise_revenue)
        # 🟢 NEW: Required for "Revenue Trend" Line Chart
        daily_pipeline = [
            match,
            {
                "$group": {
                    "_id": {
                        "$dateToString": {
                            "format": "%Y-%m-%d",
                            "date": "$orderDate",
                            "timezone": "Asia/Kolkata",
                        }
                    },
                    "daily_rev": {"$sum": "$pricing.orderTotal"},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        daily_res = await orders_col.aggregate(daily_pipeline).to_list(None)

        # D. Source Distribution (Frontend: source_distribution)
        # 🟢 NEW: Required for "Revenue Source" Pie Chart
        source_pipeline = [
            match,
            {
                "$group": {
                    "_id": {
                        "$cond": [
                            {"$eq": ["$platform", "offline"]},
                            "Dine-in",
                            "Online",
                        ]
                    },
                    "revenue": {"$sum": "$pricing.orderTotal"},
                }
            },
        ]
        source_res = await orders_col.aggregate(source_pipeline).to_list(None)

        # E. Top Items (Menu Engineering)
        item_pipeline = [
            match,
            {
                "$lookup": {
                    "from": order_items_col.name,
                    "localField": "_id",
                    "foreignField": "orderId",
                    "as": "items",
                }
            },
            {"$unwind": "$items"},
            {
                "$group": {
                    "_id": "$items.name",
                    "count": {"$sum": "$items.quantity"},  # 🟢 FIX: 'count' not 'qty'
                    "revenue": {"$sum": "$items.pricing.finalPrice"},
                }
            },
            {"$sort": {"count": -1}},
            {"$limit": 5},
        ]
        top_items = await orders_col.aggregate(item_pipeline).to_list(5)
        formatted_items = [
            {"name": i["_id"], "count": i["count"], "revenue": round(i["revenue"], 2)}
            for i in top_items
        ]

        # F. Lost Revenue (Opportunity Cost)
        lost_pipeline = [
            self._build_match_stage(rest_id, start_date, end_date, "CANCELLED"),
            {
                "$group": {
                    "_id": None,
                    "lost_amount": {"$sum": "$pricing.orderTotal"},
                    "count": {"$sum": 1},
                }
            },
        ]
        lost_res = await orders_col.aggregate(lost_pipeline).to_list(1)
        lost_data = lost_res[0] if lost_res else {"lost_amount": 0, "count": 0}

        return {
            "platform_distribution": mix_res,  # Array
            "hourly_distribution": hourly_data,  # Array
            "day_wise_revenue": daily_res,  # Array
            "source_distribution": source_res,  # Array
            "top_items": formatted_items,
            "lost_revenue": {
                "amount": round(lost_data["lost_amount"], 2),
                "count": lost_data["count"],
            },
        }

    # ---------------------------------------------------------
    # 4. CASHFLOW KPI (Learned Rates + Live Data)
    # ---------------------------------------------------------
    async def cashflow_kpis(
        self, rest_oid_str: Optional[str], start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """
        Matches Frontend: /cashflow
        """
        if not rest_oid_str:
            return self._empty_cashflow()

        rest_id = ObjectId(rest_oid_str)

        # 1. GET LEARNED COMMISSION RATES
        # ------------------------------------------------
        # We check if this restaurant has uploaded a sheet before.
        # If yes, we use that exact commission % (e.g., 23.5%).
        # If no, we use the industry standard 24%.
        store_doc = await stores_col.find_one({"_id": rest_id}, {"commission_rates": 1})
        rates = store_doc.get("commission_rates", {}) if store_doc else {}

        # 2. GET SALES (The "Expected" Income)
        # ------------------------------------------------
        sales_pipeline = [
            {
                "$match": {
                    "restaurant": rest_id,
                    "orderDate": {"$gte": start_date, "$lte": end_date},
                    # 🟢 FIX: Catch ALL status variations
                    "status.orderStatus": {
                        "$in": [
                            "delivered",
                            "Delivered",
                            "DELIVERED",
                            "completed",
                            "Completed",
                            "COMPLETED",
                            "closed",
                            "Closed",
                            "paid",
                            "Paid",
                        ]
                    },
                }
            },
            {
                "$group": {
                    "_id": "$platform",
                    "gross_sales": {"$sum": "$pricing.orderTotal"},
                    # For Waayu, verify settlement status internally
                    "waayu_settled": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$settlement_status", "SETTLED"]},
                                "$pricing.orderTotal",
                                0,
                            ]
                        }
                    },
                }
            },
        ]
        sales_data = await orders_col.aggregate(sales_pipeline).to_list(None)

        # 3. GET ACTUAL PAYOUTS (From CSV)
        # ------------------------------------------------
        payout_pipeline = [
            {
                "$match": {
                    "restaurantRef": rest_id,
                    "payout.payoutDate": {"$gte": start_date, "$lte": end_date},
                }
            },
            {
                "$group": {
                    "_id": {"plat": "$platform", "status": "$payout.payoutStatus"},
                    "val": {"$sum": "$payout.netPayout"},
                }
            },
        ]
        payout_data = await payouts_col.aggregate(payout_pipeline).to_list(None)

        # Helper to sum payout data
        def get_payout_val(plat_name, status):
            return sum(
                x["val"]
                for x in payout_data
                if str(x["_id"].get("plat")).lower() == plat_name.lower()
                and str(x["_id"].get("status")).lower() == status.lower()
            )

        # 4. CALCULATE FINAL NUMBERS
        # ------------------------------------------------
        total_receivable = 0.0
        received = 0.0
        outstanding_breakdown = {}

        for item in sales_data:
            plat = str(item["_id"]).lower()
            gross = item["gross_sales"]

            # --- A. DIRECT / POS (100% Cash) ---
            if plat in ["direct", "pos", "offline", "walk-in", "dine-in"]:
                total_receivable += gross
                received += gross  # Instant Cash

            # --- B. WAAYU (0% Comm, Internal Settlement) ---
            elif plat == "waayu":
                total_receivable += gross  # 0% Commission
                w_settled = item.get("waayu_settled", 0)
                received += w_settled

                gap = gross - w_settled
                if gap > 5:
                    outstanding_breakdown["Waayu"] = gap

            # --- C. ZOMATO / SWIGGY (Learned Logic) ---
            else:
                # Get learned rate (e.g. 22.5) or default to 24.0
                comm_pct = float(rates.get(plat, 24.0))

                # Calculate Expected Net
                # Formula: Sales * (100 - Commission) / 100
                expected_net = gross * ((100.0 - comm_pct) / 100.0)
                total_receivable += expected_net

                # Get Actuals from CSV
                actual_paid = get_payout_val(plat, "paid")
                actual_pending = get_payout_val(plat, "pending")
                received += actual_paid

                # Outstanding is the Gap OR the Confirmed Pending
                gap = max(0, expected_net - actual_paid)
                # If we have confirmed pending in CSV, use that. Else use the calculated gap.
                real_outstanding = max(gap, actual_pending)

                if real_outstanding > 5:
                    outstanding_breakdown[plat.title()] = real_outstanding

        return {
            "total_receivable": round(total_receivable, 2),
            "received": round(received, 2),
            "outstanding": round(sum(outstanding_breakdown.values()), 2),
            "outstanding_breakdown": {
                k: round(v, 2) for k, v in outstanding_breakdown.items()
            },
        }

    # ---------------------------------------------------------
    # 5. TARGETS & CHARTS (Visual Data)
    # ---------------------------------------------------------
    async def get_todays_target_status(
        self, rest_oid_str: Optional[str]
    ) -> Dict[str, Any]:
        """
        Matches Frontend: /daily-target
        Strict IST Calculation for "Today".
        """
        if not rest_oid_str:
            return {
                "achieved_amount": 0,
                "target_amount": 0,
                "percentage": 0,
                "remaining": 0,
            }

        rest_id = ObjectId(rest_oid_str)

        # 1. IST Logic
        now_ist = datetime.now(IST)
        start_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
        # Convert to UTC for Querying
        start_utc = start_ist.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = datetime.utcnow()

        # 2. Achieved Sales
        pipeline = [
            self._build_match_stage(rest_id, start_utc, end_utc, "COMPLETED"),
            {"$group": {"_id": None, "val": {"$sum": "$pricing.orderTotal"}}},
        ]
        res = await orders_col.aggregate(pipeline).to_list(1)
        achieved = res[0]["val"] if res else 0.0

        # 3. Dynamic Target
        store = await stores_col.find_one({"_id": rest_id}, {"dailyTargets": 1})
        target = 10000.0
        is_weekend = now_ist.weekday() >= 4  # Fri, Sat, Sun

        if store and "dailyTargets" in store:
            key = "weekend" if is_weekend else "weekday"
            # Handle potential string storage in DB
            raw = store["dailyTargets"].get(key, 10000)
            try:
                target = float(raw)
            except ValueError:
                target = 10000.0

        # 🟢 FRONTEND FIX: Use snake_case keys (achieved_amount) not simple keys
        return {
            "achieved_amount": round(achieved, 2),
            "target_amount": target,
            "percentage": round((achieved / target) * 100, 1) if target > 0 else 0,
            "is_weekend": is_weekend,
            "remaining": max(0, target - achieved),
        }

    async def get_sales_graph(
        self, rest_oid_str: Optional[str], start_date: datetime, end_date: datetime
    ) -> List[Dict[str, Any]]:
        """
        Matches Frontend: /sales-graph
        Generates daily sales trend for charts.
        """
        if not rest_oid_str:
            return []

        pipeline = [
            self._build_match_stage(
                ObjectId(rest_oid_str), start_date, end_date, "COMPLETED"
            ),
            {
                "$group": {
                    "_id": {
                        "$dateToString": {"format": "%Y-%m-%d", "date": "$orderDate"}
                    },
                    "sales": {"$sum": "$pricing.orderTotal"},
                    "orders": {"$sum": 1},
                }
            },
            {"$sort": {"_id": 1}},
        ]
        return await orders_col.aggregate(pipeline).to_list(None)

    async def get_tax_report(
        self, rest_oid_str: Optional[str], start_date: datetime, end_date: datetime
    ) -> Dict[str, Any]:
        """
        Matches Frontend: /tax-report
        GST Compliance Data Breakdown.
        """
        if not rest_oid_str:
            return {"total_gst": 0, "breakdown": {}}

        pipeline = [
            self._build_match_stage(
                ObjectId(rest_oid_str), start_date, end_date, "COMPLETED"
            ),
            {
                "$group": {
                    "_id": "$platform",
                    "tax_collected": {"$sum": "$pricing.tax"},
                    "taxable_value": {"$sum": "$pricing.subtotal"},
                }
            },
        ]

        raw = await orders_col.aggregate(pipeline).to_list(None)

        report = {"total_gst": 0.0, "breakdown": {}}
        for r in raw:
            platform = r["_id"] or "direct"
            report["breakdown"][platform] = {
                "tax": round(r["tax_collected"], 2),
                "sales": round(r["taxable_value"], 2),
            }
            report["total_gst"] += r["tax_collected"]

        report["total_gst"] = round(report["total_gst"], 2)
        return report

    # ---------------------------------------------------------
    # 6. HELPERS FOR EMPTY STATES
    # ---------------------------------------------------------
    def _empty_financials(self) -> Dict[str, Any]:
        # 🟢 FIX: Return Nested Structure to prevent React Crash
        return {"current": {}, "trends": {}}

    def _empty_non_financials(self) -> Dict[str, Any]:
        # 🟢 FIX: Return Arrays for Charts
        return {
            "platform_distribution": [],
            "hourly_distribution": [],
            "day_wise_revenue": [],
            "source_distribution": [],
            "top_items": [],
            "lost_revenue": {"amount": 0, "count": 0},
        }

    def _empty_cashflow(self) -> Dict[str, Any]:
        # 🟢 FIX: Return Exact Keys for Cashflow Page
        return {
            "total_receivable": 0,
            "received": 0,
            "outstanding": 0,
            "outstanding_breakdown": {},
        }


# Initialize Singleton
kpi_service = KPIService()
