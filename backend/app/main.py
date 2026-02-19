# backend/app/main.py
import os
import warnings
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    auth,
    stores,
    orders,
    kpi_routes,
    admin_users,
    settlements,
)
from app.db.mongo import init_db
from app.middleware.auth_trace import AuthTraceMiddleware
from app.utils.logger import setup_logger
from app.db.watcher import watch_orders

# 1. Setup Logger
log = setup_logger("main")

os.environ["PASSLIB_BCRYPT_FORCE_BACKEND"] = "builtin"
os.environ["PASSLIB_CONTEXT_WARN_ON_USE"] = "false"
warnings.filterwarnings("ignore", message=".*reading bcrypt version.*")

app = FastAPI(title="Restaurant Dashboard API", version="2.0")

# 2. Add Middleware


# FORCE NO-CACHE (Fixes "Same Data" on user switch)
@app.middleware("http")
async def add_no_cache_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.add_middleware(AuthTraceMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://restaurantdashboard.waayu.app",
        "http://restaurantdashboard.waayu.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "x-tenant-id",
    ],
    max_age=3600,
)


@app.on_event("startup")
async def startup_event():
    await init_db()
    log.info("🚀 Backend started. Using Live MongoDB Collections.")

    # Start the Golden Record Watcher in the background
    # This runs continuously to capture live updates
    asyncio.create_task(watch_orders())


# 3. Include Routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(stores.router, prefix="/stores", tags=["Stores"])
app.include_router(orders.router, prefix="/orders", tags=["Orders"])
app.include_router(kpi_routes.router, prefix="/kpi", tags=["KPIs"])
app.include_router(settlements.router, prefix="/settlements", tags=["Settlements"])
app.include_router(admin_users.router, prefix="/admin", tags=["Admin"])


@app.get("/")
def root():
    log.info("Health check endpoint hit.")
    return {"message": "Restaurant Dashboard Backend Running (Live Mode)"}
