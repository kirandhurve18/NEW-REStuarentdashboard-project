# backend/app/dependencies.py
from fastapi import Header, HTTPException, status
from bson import ObjectId
from app.utils.jwt_handler import decode_access_token
from app.services.auth_service import auth_service
from app.utils.logger import setup_logger

log = setup_logger("auth_dep")


async def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        log.warning("Auth failed: Missing or invalid Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token",
        )

    token = authorization.replace("Bearer ", "").strip()

    try:
        payload = decode_access_token(token)
        # Log minimal info (User ID), never the full token
        user_id_str = payload.get("sub")

        if not user_id_str:
            log.warning("Auth failed: Token missing 'sub' claim")
            raise HTTPException(401, "Invalid token payload")

        user_id = ObjectId(user_id_str)

        # Verify user still exists and is active (DB Check)
        user = await auth_service.get_user_by_id(user_id)

        if not user:
            log.warning(f"Auth failed: User ID {user_id} not found in DB")
            raise HTTPException(401, "User not found")

        if not user.get("is_active", True):
            log.warning(f"Auth failed: User {user['email']} is inactive")
            raise HTTPException(403, "User inactive")

        # pwd_version check
        token_pwd_version = int(payload.get("pwd_version", 0))
        db_pwd_version = int(user.get("pwd_version", 0))

        if token_pwd_version != db_pwd_version:
            log.info(f"Token revoked: Version mismatch for {user['email']}")
            raise HTTPException(401, detail="TOKEN_EXPIRED")

        # 🟢 CONSTRUCT CONTEXT
        # We rely on the TOKEN for the restaurant mapping to save a DB lookup per request.
        # If the token is valid, the mapping inside it was valid at login time.

        return {
            "id": str(user["_id"]),
            "email": user["email"],
            "role": user.get("role"),
            # Original Tenant ID (Int)
            "tenant_id": int(user.get("tenant_id", 0)),
            # 🟢 LIVE DATA LINKS (Extracted from Token)
            "restaurant_oid": payload.get(
                "restaurant_oid"
            ),  # String version of ObjectId
            "waayu_rest_id": payload.get("waayu_rest_id"),  # String ID
            "force_password_change": bool(user.get("force_password_change", False)),
        }

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Unexpected Auth Error: {str(e)}")
        raise HTTPException(401, "Invalid token")
