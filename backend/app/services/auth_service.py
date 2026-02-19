# backend/app/services/auth_service.py
import hashlib
import logging
from typing import Optional, Dict, Any
from bson import ObjectId

# Import both users and stores (restaurants)
from app.db.mongo import users_col, stores_col
from app.utils.common import verify_password, hash_password

log = logging.getLogger("app.auth.service")


class AuthService:
    """
    Authentication & credential persistence layer.
    Updated for Live Data: Prioritizes 'restaurant_oid' over 'tenant_id'.
    """

    # -------------------- Users --------------------

    async def create_user(self, user_doc: dict):
        result = await users_col.insert_one(user_doc)
        return result.inserted_id

    async def get_user_by_email(self, email: str):
        if not email:
            return None
        return await users_col.find_one({"email": email.lower()})

    async def get_user_by_id(self, user_id: str | ObjectId):
        if not isinstance(user_id, ObjectId):
            try:
                user_id = ObjectId(user_id)
            except Exception:
                return None
        return await users_col.find_one({"_id": user_id})

    # -------------------- Password Auth --------------------

    async def authenticate(self, email: str, password: str):
        # 1. Verify User credentials
        user = await self.get_user_by_email(email)
        log.info(f"AUTH CHECK email={email} found={bool(user)}")

        if not user or not user.get("password_hash"):
            return None

        if not verify_password(password, user["password_hash"]):
            log.warning("AUTH DEBUG password mismatch")
            return None

        # 🟢 2. LINK TO LIVE RESTAURANT (UPDATED LOGIC)
        # Priority 1: Direct ObjectId Link (Standard)
        # Priority 2: Waayu String ID
        # Priority 3: Legacy Tenant ID (Fallback)

        restaurant_doc = None

        # --- STRATEGY A: Check for direct 'restaurant_oid' ---
        if "restaurant_oid" in user and user["restaurant_oid"]:
            try:
                # It might be stored as string or ObjectId
                r_oid = user["restaurant_oid"]
                if isinstance(r_oid, str):
                    r_oid = ObjectId(r_oid)

                restaurant_doc = await stores_col.find_one({"_id": r_oid})
                if restaurant_doc:
                    log.info(f"🔗 Linked via direct restaurant_oid: {r_oid}")
            except Exception as e:
                log.error(f"Failed to link via restaurant_oid: {e}")

        # --- STRATEGY B: Check for 'waayu_rest_id' string ---
        if not restaurant_doc and "waayu_rest_id" in user and user["waayu_rest_id"]:
            w_id = str(user["waayu_rest_id"])
            restaurant_doc = await stores_col.find_one({"waayuRestId": w_id})
            if restaurant_doc:
                log.info(f"🔗 Linked via waayu_rest_id: {w_id}")

        # --- STRATEGY C: Legacy Tenant ID (Only if A & B fail) ---
        if not restaurant_doc and "tenant_id" in user and user["tenant_id"]:
            t_id = user["tenant_id"]
            # Try matching String version of tenant_id
            restaurant_doc = await stores_col.find_one({"tenantId": str(t_id)})

            # Fallback: Try matching 'waayuRestId' just in case logic differs
            if not restaurant_doc:
                restaurant_doc = await stores_col.find_one({"waayuRestId": str(t_id)})

            if restaurant_doc:
                log.info(f"🔗 Linked via legacy tenant_id: {t_id}")

        # 3. Attach Result to User Object (In-Memory for Token)
        if restaurant_doc:
            user["live_restaurant_oid"] = str(restaurant_doc["_id"])
            user["live_waayu_rest_id"] = restaurant_doc.get("waayuRestId")
        else:
            log.warning(f"⚠️ User {email} logged in but NO Restaurant could be linked.")
            user["live_restaurant_oid"] = None
            user["live_waayu_rest_id"] = None

        return user

    async def update_password(self, user_id: str | ObjectId, new_password: str):
        if not isinstance(user_id, ObjectId):
            user_id = ObjectId(user_id)

        new_hash = hash_password(new_password)

        await users_col.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "password_hash": new_hash,
                    "force_password_change": False,
                },
                "$inc": {"pwd_version": 1},
            },
        )

    # -------------------- Refresh Tokens --------------------

    @staticmethod
    def _hash_refresh(refresh_token: str) -> str:
        return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()

    async def save_refresh_hash(self, user_id: str | ObjectId, refresh_token: str):
        if not isinstance(user_id, ObjectId):
            user_id = ObjectId(user_id)

        await users_col.update_one(
            {"_id": user_id},
            {"$set": {"refresh_token_hash": self._hash_refresh(refresh_token)}},
        )

    async def get_refresh_hash(self, user_id: str | ObjectId) -> Optional[str]:
        if not isinstance(user_id, ObjectId):
            user_id = ObjectId(user_id)

        user = await users_col.find_one(
            {"_id": user_id},
            {"refresh_token_hash": 1},
        )
        return user.get("refresh_token_hash") if user else None

    async def clear_refresh_hash(self, user_id: str | ObjectId):
        if not isinstance(user_id, ObjectId):
            user_id = ObjectId(user_id)

        await users_col.update_one(
            {"_id": user_id},
            {"$unset": {"refresh_token_hash": ""}},
        )

    async def verify_refresh_token(
        self, user_id: str | ObjectId, refresh_token: str
    ) -> bool:
        stored = await self.get_refresh_hash(user_id)
        if not stored:
            return False
        return self._hash_refresh(refresh_token) == stored

    # -------------------- Token Payload --------------------

    def sanitize_user_for_token(self, user: Dict[str, Any]) -> Dict[str, Any]:
        """
        Embeds critical IDs into the JWT so we don't query DB for them again.
        """
        # Ensure we have the live links populated (from authenticate)
        # If they are missing, try to grab from raw user doc as fallback
        rest_oid = user.get("live_restaurant_oid") or str(
            user.get("restaurant_oid", "")
        )
        waayu_id = user.get("live_waayu_rest_id") or str(user.get("waayu_rest_id", ""))

        # Handle "None" strings if they slipped through
        if rest_oid == "None":
            rest_oid = None
        if waayu_id == "None":
            waayu_id = None

        return {
            "email": user.get("email"),
            "role": user.get("role"),
            "tenant_id": user.get("tenant_id"),  # Keep for legacy compatibility
            # 🟢 CRITICAL: This is what the Dashboard uses for Data Access
            "restaurant_oid": rest_oid,
            "waayu_rest_id": waayu_id,
            "pwd_version": int(user.get("pwd_version", 0)),
            "is_active": bool(user.get("is_active", True)),
            "force_password_change": bool(user.get("force_password_change", True)),
        }


# 🔥 REQUIRED singleton
auth_service = AuthService()
