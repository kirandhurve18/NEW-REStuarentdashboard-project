from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from typing import List, Optional
from datetime import datetime

from app.dependencies import get_current_user
from app.services.settlement_service import settlement_service
from app.utils.csv_parser import SettlementParser
from app.utils.logger import setup_logger

router = APIRouter(tags=["Settlements"])
log = setup_logger("settlements_router")


# ---------------------------------------------------------
# 1. READ SETTLEMENTS
# ---------------------------------------------------------
@router.get("/", response_model=List[dict])
async def get_settlements(
    platform: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
):
    """
    Fetches verified settlement data (Waayu + Zomato + Swiggy).
    """
    try:
        rest_oid = current_user.get("restaurant_oid")
        if not rest_oid:
            return []

        # Date Filtering
        s_date, e_date = None, None
        if start_date and end_date:
            try:
                s_date = datetime.fromisoformat(start_date.replace("Z", ""))
                e_date = datetime.fromisoformat(end_date.replace("Z", ""))
            except ValueError:
                pass

        results = await settlement_service.get_settlements(
            restaurant_oid=rest_oid,
            start_date=s_date,
            end_date=e_date,
            platform=platform,
            limit=limit,
            skip=(page - 1) * limit,
        )

        return results

    except Exception as e:
        log.error(f"Error fetching settlements: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")


# ---------------------------------------------------------
# 2. UPLOAD SETTLEMENT (Internal Processing)
# ---------------------------------------------------------
@router.post("/upload")
async def upload_settlement_csv(
    file: UploadFile = File(...),
    platform: str = Form(...),  # Matches curl: --form 'platform="zomato"'
    current_user: dict = Depends(get_current_user),
):
    """
    Receives the Settlement CSV/Excel, parses it, matches it with Live Orders,
    and updates the Commission Rates automatically.
    """
    rest_oid = current_user.get("restaurant_oid")
    if not rest_oid:
        raise HTTPException(status_code=400, detail="User not linked to a restaurant")

    platform_clean = platform.lower().strip()
    if platform_clean not in ["swiggy", "zomato", "waayu"]:
        raise HTTPException(
            status_code=400, detail="Platform must be 'swiggy', 'zomato', or 'waayu'"
        )

    log.info(f"📥 Receiving {platform_clean} Settlement for {rest_oid}...")

    try:
        # 1. READ FILE CONTENT
        content = await file.read()

        # 2. PARSE (Using our 100% Accurate Parser)
        parsed_data = SettlementParser.parse_file(content, file.filename)

        if not parsed_data:
            raise HTTPException(
                status_code=400, detail="Could not parse any valid rows from file."
            )

        # 3. SYNC & LEARN (One Step)
        # This function now saves to DB AND auto-updates commission rates internally.
        stats = await settlement_service.sync_payouts(
            restaurant_oid=rest_oid, platform=platform_clean, data=parsed_data
        )

        # 🟢 REMOVED Step 4: 'update_commission_rates' is now automatic inside sync_payouts

        return {
            "status": "SUCCESS",
            "message": f"Processed {len(parsed_data)} rows. Commissions updated.",
            "stats": stats,
        }

    except Exception as e:
        log.error(f"❌ Upload Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
