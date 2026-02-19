# backend/app/routers/stores.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime

from app.dependencies import get_current_user
from app.db.mongo import stores_col, db  # Maps to "restaurants"

router = APIRouter(tags=["Stores"])

# 🟢 DEFINE HISTORY COLLECTION (For "Time Travel" Audit Logs)
store_history_col = db["store_config_history"]


# -----------------------------
# INPUT MODELS (Requests)
# -----------------------------
class FixedCostUpdate(BaseModel):
    rent: float = 0
    salaries: float = 0
    electricity: float = 0
    maintenance: float = 0
    miscellaneous: float = 0


class TargetUpdate(BaseModel):
    weekday_target: float
    weekend_target: float


class CommercialsUpdate(BaseModel):
    zomato_commission: float = 24.0
    swiggy_commission: float = 24.0
    # 🟢 NEW: Food Cost Slider Value (0-100)
    food_cost_percentage: float = 30.0


# -----------------------------
# HELPER: HISTORY SNAPSHOT
# -----------------------------
async def save_store_history(rest_id, change_type, old_data, new_data, user_id):
    """
    Saves a golden record of configuration changes.
    Matches your 'Time Travel' requirement for configs.
    """
    snapshot = {
        "restaurant_oid": rest_id,
        "change_type": change_type,  # e.g. "commercials_update"
        "modified_by": user_id,
        "modified_at": datetime.utcnow(),
        "changes": {"old": old_data, "new": new_data},
    }
    await store_history_col.insert_one(snapshot)


# -----------------------------
# ENDPOINTS
# -----------------------------


@router.get("/")
async def list_stores(user: dict = Depends(get_current_user)):
    """
    List the single active restaurant linked to this user.
    """
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return {"stores": []}

    # Query Live 'restaurants' collection
    store = await stores_col.find_one(
        {"_id": ObjectId(rest_oid)},
        {"storeName": 1, "address": 1, "mobile": 1, "email": 1, "waayuRestId": 1},
    )

    if not store:
        return {"stores": []}

    # Map Live DB fields to Dashboard fields
    address_obj = store.get("address", {})
    full_address = (
        address_obj.get("fullAddress")
        if isinstance(address_obj, dict)
        else str(address_obj)
    )

    formatted_store = {
        "tenant_id": store.get("waayuRestId"),  # Live String ID
        "store_name": store.get("storeName"),
        "address": full_address,
        "phone": store.get("mobile"),
        "email": store.get("email"),
    }

    return {"stores": [formatted_store]}


@router.get("/fixed-costs")
async def get_fixed_costs(user: dict = Depends(get_current_user)):
    """Get the current fixed costs configuration from Live DB"""
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return {}

    store = await stores_col.find_one(
        {"_id": ObjectId(rest_oid)}, {"fixedCosts": 1, "_id": 0}
    )

    # Map Live DB 'fixedCosts' (CamelCase) -> Response (snake_case)
    fc = store.get("fixedCosts", {}) if store else {}

    return {
        "rent": fc.get("rent", 0),
        "salaries": fc.get("salaries", 0),
        "electricity": fc.get("electricity", 0),
        "maintenance": fc.get("maintenance", 0),
        "miscellaneous": fc.get("miscellaneous", 0),
    }


@router.put("/fixed-costs")
async def update_fixed_costs(
    payload: FixedCostUpdate, user: dict = Depends(get_current_user)
):
    """Update fixed costs in Live DB"""
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        raise HTTPException(
            status_code=400, detail="User not linked to a live restaurant"
        )

    # Update 'fixedCosts' field in restaurants collection
    # We use .dict() to convert the Pydantic model to a standard dictionary
    await stores_col.update_one(
        {"_id": ObjectId(rest_oid)},
        {"$set": {"fixedCosts": payload.dict()}},
        upsert=True,
    )

    return {"message": "Fixed costs updated successfully", "data": payload}


@router.get("/targets")
async def get_targets(user: dict = Depends(get_current_user)):
    """Get the current daily targets from Live DB"""
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return {"weekday_target": 10000, "weekend_target": 15000}

    store = await stores_col.find_one(
        {"_id": ObjectId(rest_oid)}, {"dailyTargets": 1, "_id": 0}
    )

    # Map Live DB 'dailyTargets' (weekday/weekend) -> Response (weekday_target/weekend_target)
    dt = store.get("dailyTargets", {}) if store else {}

    return {
        "weekday_target": dt.get("weekday", 10000.0),
        "weekend_target": dt.get("weekend", 15000.0),
    }


@router.put("/targets")
async def update_targets(payload: TargetUpdate, user: dict = Depends(get_current_user)):
    """Update daily targets in Live DB"""
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        raise HTTPException(
            status_code=400, detail="User not linked to a live restaurant"
        )

    # Manual Mapping: Input (snake_case) -> DB (simple keys)
    db_payload = {"weekday": payload.weekday_target, "weekend": payload.weekend_target}

    await stores_col.update_one(
        {"_id": ObjectId(rest_oid)},
        {"$set": {"dailyTargets": db_payload}},
        upsert=True,
    )

    return {"message": "Targets updated successfully", "data": payload}


@router.get("/commercials")
async def get_commercials(user: dict = Depends(get_current_user)):
    """Get commission percentages AND food cost percentage"""
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        return {
            "zomato_commission": 24,
            "swiggy_commission": 24,
            "food_cost_percentage": 30,
        }

    store = await stores_col.find_one({"_id": ObjectId(rest_oid)}, {"commercials": 1})
    comm = store.get("commercials", {}) if store else {}

    return {
        "zomato_commission": comm.get("zomato_commission", 24),
        "swiggy_commission": comm.get("swiggy_commission", 24),
        # 🟢 NEW: Return saved food cost (Default 30)
        "food_cost_percentage": comm.get("food_cost_percentage", 30),
    }


@router.put("/commercials")
async def update_commercials(
    payload: CommercialsUpdate, user: dict = Depends(get_current_user)
):
    """
    Update commission percentages & Food Cost slider manually.
    Saves snapshot to History (No Regrets Policy).
    """
    rest_oid = user.get("restaurant_oid")
    if not rest_oid:
        raise HTTPException(status_code=400, detail="No restaurant linked")

    rest_id_obj = ObjectId(rest_oid)

    # 1. Fetch OLD state for History (Time Travel)
    old_doc = await stores_col.find_one({"_id": rest_id_obj}, {"commercials": 1})
    old_data = old_doc.get("commercials", {}) if old_doc else {}

    # 2. Update DB
    new_data = payload.dict()
    await stores_col.update_one(
        {"_id": rest_id_obj},
        {"$set": {"commercials": new_data}},
        upsert=True,
    )

    # 3. 🟢 SAVE HISTORY
    await save_store_history(
        rest_id_obj,
        "commercials_update",
        old_data,
        new_data,
        user.get("sub"),  # User ID
    )

    return {"message": "Commissions & Food Cost updated", "data": new_data}
