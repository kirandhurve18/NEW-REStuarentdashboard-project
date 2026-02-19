# # # backend/app/utils/jwt_handler.py

# backend/app/utils/jwt_handler.py

from fastapi import HTTPException
from typing import Dict, Any
from jose import jwt, JWTError, ExpiredSignatureError
from jose.exceptions import JWTClaimsError
import app.config as config
import uuid
import time


def _now() -> int:
    return int(time.time())


print(f"⏰ SERVER UTC NOW:{_now()}")


def create_access_token(subject: str, extra: Dict[str, Any] = None) -> str:
    current_time = _now()
    payload = {
        "sub": subject,
        "jti": str(uuid.uuid4()),
        "iat": current_time,
        "exp": current_time + int(config.ACCESS_TOKEN_EXPIRE.total_seconds()),
        "token_type": "access",
    }
    if extra:
        payload.update(extra)
    print("JWT SECRET USED:", config.JWT_SECRET_KEY[:10])
    return jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)


def create_refresh_token(subject: str, extra: Dict[str, Any] = None) -> str:
    current_time = _now()
    payload = {
        "sub": subject,
        "jti": str(uuid.uuid4()),
        "iat": current_time,
        "exp": current_time + int(config.REFRESH_TOKEN_EXPIRE.total_seconds()),
        "token_type": "refresh",
    }
    if extra:
        payload.update(extra)
    print("JWT REFRESH SECRET USED:", config.JWT_REFRESH_SECRET_KEY[:10])
    return jwt.encode(
        payload, config.JWT_REFRESH_SECRET_KEY, algorithm=config.JWT_ALGORITHM
    )


# --------------------------------------------------
# 🔐 Access Token Decoder
# --------------------------------------------------
def decode_access_token(token: str) -> Dict[str, Any]:
    # print("🔑 DECODING ACCESS TOKEN WITH KEY:", config.JWT_SECRET_KEY[:6], "...")
    print(f"🔑 VALIDATING WITH KEY: {config.JWT_SECRET_KEY[:10]}...")
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM],
            options={
                "verify_aud": False,
                "leeway": 60,  # 🟢 FIX: Allows 30sec clock difference
            },
        )

        token_type = payload.get("token_type")
        if token_type != "access":
            raise HTTPException(
                401,
                detail="Invalid access token type",
            )

        return payload

    except ExpiredSignatureError as e:
        print(f"❌ TOKEN EXPIRED: {str(e)}")
        raise HTTPException(
            401,
            detail="Access token expired",
        )
    except JWTClaimsError as e:
        print(f"⏰ CLOCK SKEW DETECTED: {repr(e)}")
        raise HTTPException(401, detail="Token not yet valid - sync server clock")

    except JWTError as e:
        print("❌ ACCESS TOKEN JWT ERROR:", repr(e))
        raise HTTPException(
            401,
            detail="Invalid or expired access token",
        )


# --------------------------------------------------
# 🔁 Refresh Token Decoder
# --------------------------------------------------
def decode_refresh_token(token: str) -> Dict[str, Any]:
    print(
        "🔑 DECODING REFRESH TOKEN WITH KEY:", config.JWT_REFRESH_SECRET_KEY[:6], "..."
    )

    try:
        payload = jwt.decode(
            token,
            config.JWT_REFRESH_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM],
            options={
                "verify_aud": False,
                "leeway": 30,
            },
        )

        if payload.get("token_type") != "refresh":
            raise HTTPException(
                status_code=401,
                detail="Invalid refresh token type",
            )

        return payload

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Refresh token expired",
        )

    except JWTError as e:
        print("❌ REFRESH TOKEN JWT ERROR:", str(e))
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token",
        )


def verify_refresh_token(token: str) -> Dict[str, Any]:
    """
    Convenience wrapper to explicitly verify a refresh token and return payload
    (raises HTTPException if invalid).
    """
    return decode_refresh_token(token)
