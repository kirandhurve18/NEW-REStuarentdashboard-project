# # # backend/app/config.py
import os
from datetime import timedelta
from dotenv import load_dotenv
from pathlib import Path

# 🔥 Always resolve from THIS file location
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

# ----------------------------------------------------
# 🟢 TOKEN LIFETIMES (UPDATED FOR STABILITY)
# ----------------------------------------------------
# We use .get() but defaulting to integers directly to prevent type errors
# Changed from 15 mins -> 60 mins
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 480))

# Changed from 30 days -> 7 days (Standard security practice)
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# ----------------------------------------------------
# JWT KEYS (MUST be overridden in prod)
# ----------------------------------------------------
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super_long_random_access_secret_123456")
JWT_REFRESH_SECRET_KEY = os.getenv(
    "JWT_REFRESH_SECRET_KEY", "super_long_random_refresh_secret_123456"
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# ----------------------------------------------------
# REFRESH COOKIE CONFIG
# ----------------------------------------------------
REFRESH_TOKEN_COOKIE_NAME = os.getenv("REFRESH_TOKEN_COOKIE_NAME", "waayu_refresh")

# Always allow refresh cookie on /auth/*
REFRESH_TOKEN_COOKIE_PATH = "/"

# ENV detection
ENV = os.getenv("ENV", "local").lower()
IS_LOCAL = ENV in ("local", "development", "dev")

# COOKIE BEHAVIOUR
# - In local dev with Vite proxy single-origin, Secure can be False and SameSite 'lax' is fine.
# - For cross-origin setups (frontend on different host than backend) you'd use SameSite=None and Secure=True (HTTPS).
if IS_LOCAL:
    REFRESH_TOKEN_COOKIE_SECURE = False
    REFRESH_TOKEN_COOKIE_SAMESITE = "lax"
else:
    # Production: cookies should be secure and allow cross-site if you use different domains/subdomains.
    REFRESH_TOKEN_COOKIE_SECURE = True
    # If you host frontend and backend under same parent domain prefer "lax".
    # If you use separate domains/subdomains and need cross-site cookies use "none".
    REFRESH_TOKEN_COOKIE_SAMESITE = os.getenv("REFRESH_TOKEN_COOKIE_SAMESITE", "lax")

# ----------------------------------------------------
# Convenience
# ----------------------------------------------------
ACCESS_TOKEN_EXPIRE = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
REFRESH_TOKEN_EXPIRE = timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

# ----------------------------------------------------
# MONGODB CONFIG
# ----------------------------------------------------
MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

# Debug Prints
print(
    f"🔍 CONFIG LOADED: Access Token Lifetime = {ACCESS_TOKEN_EXPIRE_MINUTES} minutes"
)
print("🔍 MONGO_URI =", MONGO_URI)
print("🔍 MONGO_DB_NAME =", MONGO_DB_NAME)

assert MONGO_URI, "❌ MONGO_URI missing"
assert MONGO_DB_NAME, "❌ MONGO_DB_NAME missing"
