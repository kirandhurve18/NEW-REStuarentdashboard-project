# backend/app/db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.config import MONGO_URI, MONGO_DB_NAME
from app.utils.logger import setup_logger

log = setup_logger("db")

client = AsyncIOMotorClient(
    MONGO_URI,
    serverSelectionTimeoutMS=5000,
    socketTimeoutMS=60000,
    connectTimeoutMS=20000,
    minPoolSize=1,
    maxPoolSize=100,
    retryWrites=True,
    retryReads=True,
)

db = client[MONGO_DB_NAME]

# 🟢 LIVE COLLECTION MAPPING

# 1. Users Collection (MISSING IN YOUR CODE)
users_col = db["users"]

# 2. Restaurants (Config & Profile)
stores_col = db["restaurants"]

# 3. Live Orders
orders_col = db["neworders"]

# 4. Order Items
order_items_col = db["orderitems"]

# 5. Financial Truth (Settlements)
payouts_col = db["payoutorders"]

# 6. Internal History (Time Travel)
history_col = db["order_history"]

# 7. Internal Waayu Logic
waayu_settlements_col = db["waayu_settlements"]

# Restaurant History
store_history_col = db["store_config_history"]


async def init_db():
    try:
        await db.command("ping")

        # --- INDEXES ---

        # 1. Users Index (Email Lookup)
        await users_col.create_index("email", unique=True)

        # 2. History Index
        await history_col.create_index(
            [("tenant_id", 1), ("parent_order_id", 1), ("history_created_at", -1)]
        )

        # 3. Live Order Indexes
        await orders_col.create_index([("restaurant", 1), ("orderDate", -1)])
        await orders_col.create_index([("dpOrderId", 1)])

        # 4. Restaurant Lookup
        await stores_col.create_index("waayuRestId", unique=True)

        log.info(f"✅ MongoDB Connected to Live Collections: {MONGO_DB_NAME}")

    except Exception as e:
        log.error(f"❌ MongoDB Connection Failed: {e}")
        raise e
