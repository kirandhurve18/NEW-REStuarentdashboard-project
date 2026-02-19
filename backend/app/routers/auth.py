# backend/app/routers/auth.py

from fastapi import (
    APIRouter,
    HTTPException,
    Response,
    Cookie,
    Depends,
)
from pydantic import BaseModel
import logging
from bson import ObjectId
from typing import Optional
from app.dependencies import get_current_user
from app.services.auth_service import auth_service
from app.utils.common import verify_password
from app.utils.jwt_handler import (
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
)
from app.config import (
    REFRESH_TOKEN_COOKIE_NAME,
    REFRESH_TOKEN_COOKIE_PATH,
    REFRESH_TOKEN_COOKIE_SECURE,
    REFRESH_TOKEN_COOKIE_SAMESITE,
)

router = APIRouter(tags=["Auth"])
log = logging.getLogger("app.auth.router")


# ----------------------------- Models -----------------------------


class LoginIn(BaseModel):
    email: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: Optional[str] = None
    new_password: str


# ----------------------------- Me -----------------------------


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {"user": user}


# ----------------------------- Change Password -----------------------------


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordIn,
    current_user=Depends(get_current_user),
):
    user = await auth_service.get_user_by_id(current_user["id"])

    if not user:
        raise HTTPException(404, "User not found")

    is_force_change = user.get("force_password_change", False)
    is_first_version = user.get("pwd_version", 0) == 0

    if is_force_change or is_first_version:
        pass
    else:
        if not payload.old_password:
            raise HTTPException(400, "Current password is required")

        if not verify_password(payload.old_password, user["password_hash"]):
            raise HTTPException(400, "Current password incorrect")

    await auth_service.update_password(user["_id"], payload.new_password)
    return {"ok": True}


# ----------------------------- Login -----------------------------


@router.post("/login", status_code=200)
async def login(
    payload: LoginIn,
    response: Response,
):
    user = await auth_service.authenticate(payload.email, payload.password)

    if not user:
        raise HTTPException(401, "Invalid credentials")

    if not user.get("is_active", True):
        raise HTTPException(403, "User inactive")

    # 🟢 NEW: Get claims with restaurant_oid instead of tenant_id
    claims = auth_service.sanitize_user_for_token(user)

    # Create Tokens
    access = create_access_token(subject=str(user["_id"]), extra=claims)
    refresh = create_refresh_token(subject=str(user["_id"]), extra=claims)

    await auth_service.save_refresh_hash(user["_id"], refresh)

    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=refresh,
        httponly=True,
        secure=REFRESH_TOKEN_COOKIE_SECURE,
        samesite=REFRESH_TOKEN_COOKIE_SAMESITE,
        path=REFRESH_TOKEN_COOKIE_PATH,
        max_age=60 * 60 * 24 * 30,
    )

    user_out = dict(user)
    user_out["_id"] = str(user_out["_id"])

    # 🟢 Updated Log: Showing Restaurant OID instead of Tenant ID
    print(
        f"✅ LOGIN SUCCESS: {user['email']} (RestOID: {claims.get('restaurant_oid')})"
    )

    return {
        "access_token": access,
        "user": claims | {"id": user_out["_id"]},
    }


# ----------------------------- Refresh -----------------------------
@router.post("/refresh")
async def refresh(
    response: Response,
    refresh_token: str = Cookie(None, alias=REFRESH_TOKEN_COOKIE_NAME),
):
    if not refresh_token:
        raise HTTPException(401, "Missing refresh token")

    try:
        payload = verify_refresh_token(refresh_token)
    except Exception:
        raise HTTPException(401, "Invalid refresh token")

    user_id = ObjectId(payload["sub"])

    if not await auth_service.verify_refresh_token(user_id, refresh_token):
        await auth_service.clear_refresh_hash(user_id)
        raise HTTPException(401, "Invalid refresh token")

    user = await auth_service.get_user_by_id(user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(403, "User inactive")

    # 🟢 NEW: Ensure refreshed token also gets the correct claims
    claims = auth_service.sanitize_user_for_token(user)

    new_access = create_access_token(subject=str(user["_id"]), extra=claims)
    new_refresh = create_refresh_token(subject=str(user["_id"]), extra=claims)

    await auth_service.save_refresh_hash(user_id, new_refresh)

    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        value=new_refresh,
        httponly=True,
        secure=REFRESH_TOKEN_COOKIE_SECURE,
        samesite=REFRESH_TOKEN_COOKIE_SAMESITE,
        path=REFRESH_TOKEN_COOKIE_PATH,
    )

    return {"access_token": new_access}


# ----------------------------- Logout -----------------------------


@router.post("/logout")
async def logout(response: Response, waayu_refresh: str = Cookie(None)):
    if waayu_refresh:
        try:
            payload = verify_refresh_token(waayu_refresh)
            await auth_service.clear_refresh_hash(ObjectId(payload["sub"]))
        except Exception:
            pass

    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_NAME,
        path=REFRESH_TOKEN_COOKIE_PATH,
    )
    return {"ok": True}
