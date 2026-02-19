# backend/app/routers/kpi_routes.py
from fastapi import APIRouter, Depends, Query
from typing import Optional#, Dict, Any
from datetime import datetime, timedelta

from app.dependencies import get_current_user
from app.services.kpi_service import kpi_service
from app.utils.logger import setup_logger

router = APIRouter(tags=["KPIs"])
log = setup_logger("kpi_routes")


def parse_dates(start_date: Optional[str], end_date: Optional[str]):
    """Helper to parse ISO strings from frontend to datetime objects."""
    now = datetime.utcnow()
    s_dt = now - timedelta(days=30)  # Default to 30 days
    e_dt = now

    if start_date and end_date:
        try:
            # Handle "2026-02-10T00:00:00.000Z" format
            s_dt = datetime.fromisoformat(start_date.replace("Z", ""))
            e_dt = datetime.fromisoformat(end_date.replace("Z", ""))
        except ValueError:
            pass
    return s_dt, e_dt


# ---------------------------------------------------------
# 1. FINANCIAL KPI (Matches Frontend /financial)
# ---------------------------------------------------------
@router.get("/financial")
async def financial(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """
    Aggregates Gross Sales, Net Payouts, Commissions, and Taxes.
    """
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return kpi_service._empty_financials()

    s_dt, e_dt = parse_dates(start_date, end_date)
    return await kpi_service.financial_kpis(rest_oid, s_dt, e_dt)


# ---------------------------------------------------------
# 2. NON-FINANCIAL KPI (Matches Frontend /non-financial)
# ---------------------------------------------------------
@router.get("/non-financial")
async def non_financial(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """
    Aggregates Top Items, Platform Mix, and Order Status Counts.
    """
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return kpi_service._empty_non_financials()

    s_dt, e_dt = parse_dates(start_date, end_date)
    return await kpi_service.non_financial_kpis(rest_oid, s_dt, e_dt)


# ---------------------------------------------------------
# 3. CASHFLOW KPI (Matches Frontend /cashflow)
# ---------------------------------------------------------
@router.get("/cashflow")
async def cashflow(
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    """
    Aggregates Settled Payouts vs Unsettled Estimates.
    """
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return kpi_service._empty_cashflow()

    s_dt, e_dt = parse_dates(start_date, end_date)
    return await kpi_service.cashflow_kpis(rest_oid, s_dt, e_dt)


# ---------------------------------------------------------
# 4. DAILY TARGET (Matches Frontend Header)
# ---------------------------------------------------------
@router.get("/daily-target")
async def daily_target(user: dict = Depends(get_current_user)):
    """
    Get live progress against today's target.
    """
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return {"achieved": 0, "target": 0, "percentage": 0}

    return await kpi_service.get_todays_target_status(rest_oid)
