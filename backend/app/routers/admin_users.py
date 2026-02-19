# backend/app/routers/admin_users.py
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel, EmailStr
import csv
import io
from datetime import datetime

from app.dependencies import get_current_user
from app.services.auth_service import auth_service
from app.utils.common import hash_password

# 🟢 IMPORT STORES COLLECTION FOR LOOKUPS
from app.db.mongo import stores_col

router = APIRouter(tags=["Admin"])


# -----------------------------
# Schemas
# -----------------------------
class CreateUserIn(BaseModel):
    email: EmailStr
    # 🟢 CHANGED: Int Tenant ID -> String Waayu ID
    waayu_rest_id: str
    role: str = "STORE_ADMIN"


# -----------------------------
# Helpers
# -----------------------------
def _require_admin(user):
    if user.get("role") not in {"SUPER_ADMIN", "ADMIN"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


def _get_admin_id(user):
    if "id" in user:
        return str(user["id"])
    if "_id" in user:
        return str(user["_id"])
    if "sub" in user:
        return str(user["sub"])
    return "unknown_admin"


# -----------------------------
# 1. Create Single User
# -----------------------------
@router.post("/users", status_code=201)
async def create_user(
    payload: CreateUserIn,
    current_user=Depends(get_current_user),
):
    _require_admin(current_user)

    # 1. Check if user exists
    existing = await auth_service.get_user_by_email(payload.email)
    if existing:
        raise HTTPException(400, "User with this email already exists")

    # 🟢 2. VALIDATE RESTAURANT EXISTENCE
    # We look up the restaurant by the human-readable 'waayuRestId'
    restaurant = await stores_col.find_one({"waayuRestId": payload.waayu_rest_id})

    if not restaurant:
        raise HTTPException(
            400, f"Restaurant with Waayu ID '{payload.waayu_rest_id}' not found"
        )

    restaurant_oid = restaurant["_id"]  # The internal ObjectId

    # 3. STATIC PASSWORD LOGIC
    static_password = "Test1234!"

    # 4. Prepare Document
    user_doc = {
        "email": payload.email.lower().strip(),
        "password_hash": hash_password(static_password),
        # 🟢 LINKING FIELDS
        "restaurant_oid": restaurant_oid,  # Internal Link (ObjectId)
        "waayu_rest_id": payload.waayu_rest_id,  # Human Readable Link (String)
        "tenant_id": 0,  # Legacy Fallback
        "role": payload.role,
        "store_ids": [],
        "is_active": True,
        "force_password_change": True,
        "pwd_version": 0,
        "created_at": datetime.utcnow(),
        "created_by": _get_admin_id(current_user),
    }

    # 5. Save
    user_id = await auth_service.create_user(user_doc)

    return {
        "user_id": str(user_id),
        "email": payload.email,
        "temp_password": static_password,
        "message": f"User created. Linked to Restaurant {payload.waayu_rest_id}",
    }


# -----------------------------
# 2. Bulk Upload Users
# -----------------------------
@router.post("/users/bulk-upload")
async def bulk_create_users(
    file: UploadFile = File(...), current_user=Depends(get_current_user)
):
    _require_admin(current_user)

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are allowed")

    content = await file.read()
    try:
        decoded = content.decode("utf-8")
        reader = csv.DictReader(io.StringIO(decoded))
    except Exception:
        raise HTTPException(400, "Invalid CSV format")

    results = []
    admin_id = _get_admin_id(current_user)
    static_password = "Waayu@1234"

    for row in reader:
        # Safe extraction
        email = (row.get("email") or "").strip().lower()

        # 🟢 Support both column names for flexibility
        waayu_id = (row.get("waayu_rest_id") or row.get("tenant_id") or "").strip()

        # Validation: Skip invalid rows
        if not email or not waayu_id:
            results.append(
                {
                    "email": email or "Unknown",
                    "status": "Skipped (Missing Email or ID)",
                    "password": "",
                }
            )
            continue

        # Check existence
        existing = await auth_service.get_user_by_email(email)
        if existing:
            results.append(
                {"email": email, "status": "Skipped (Already Exists)", "password": ""}
            )
            continue

        # 🟢 VALIDATE RESTAURANT LOOKUP
        restaurant = await stores_col.find_one({"waayuRestId": waayu_id})
        if not restaurant:
            results.append(
                {
                    "email": email,
                    "status": f"Skipped (Invalid Waayu ID: {waayu_id})",
                    "password": "",
                }
            )
            continue

        # Create User
        try:
            user_doc = {
                "email": email,
                "password_hash": hash_password(static_password),
                # 🟢 LINKING FIELDS
                "restaurant_oid": restaurant["_id"],
                "waayu_rest_id": waayu_id,
                "tenant_id": 0,
                "role": "STORE_ADMIN",
                "store_ids": [],
                "is_active": True,
                "force_password_change": True,
                "pwd_version": 0,
                "created_at": datetime.utcnow(),
                "created_by": admin_id,
            }

            await auth_service.create_user(user_doc)

            results.append(
                {"email": email, "status": "Created", "password": static_password}
            )
        except Exception as e:
            results.append(
                {"email": email, "status": f"Error: {str(e)}", "password": ""}
            )

    return {"summary": results}
