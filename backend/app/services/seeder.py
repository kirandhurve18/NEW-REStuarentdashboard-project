from datetime import datetime
from app.db.mongo import stores_col


async def initialize_new_tenant(tenant_id: int, email: str = None):
    """
    Production Seeder:
    1. Sets up Store Config (REQUIRED for Dashboard Fixed Costs/Targets).
    2. [DISABLED] Dummy Data Generation.
    """

    # ---------------- STEP 1: Ensure Store Configuration Exists (KEEP THIS) ----------------
    # This is safe. It ensures every tenant has a settings document.
    store_exists = await stores_col.find_one({"tenant_id": tenant_id})

    if not store_exists:
        print(f"🏢 Creating Default Store Config for Tenant {tenant_id}...")
        new_store_config = {
            "tenant_id": tenant_id,
            "owner_email": email or f"user{tenant_id}@example.com",
            "store_name": f"Restaurant {tenant_id}",
            "created_at": datetime.utcnow(),
            # Default Costs (User edits these later)
            "fixed_costs": {
                "rent": 0,
                "salaries": 0,
                "electricity": 0,
                "maintenance": 0,
                "miscellaneous": 0,
            },
            "daily_targets": {"weekday_target": 10000, "weekend_target": 15000},
            "integrations": {
                "zomato": {"active": False},
                "swiggy": {"active": False},
                "pos": {"active": False},
            },
        }
        await stores_col.insert_one(new_store_config)

    # ---------------- STEP 2: Dummy Data Generation (DISABLED FOR PRODUCTION) ----------------
    # We comment this out so NO fake data is ever created.

    """
    order_count = await orders_col.count_documents({"tenant_id": tenant_id})

    if order_count > 100:
        print(f"⏩ Tenant {tenant_id} has {order_count} orders. Skipping seed.")
        return

    if order_count > 0:
        print(f"🧹 Cleaning stale/junk data ({order_count} orders) for Tenant {tenant_id}...")
        await orders_col.delete_many({"tenant_id": tenant_id})

    print(f"🌱 Seeding 90 days of Demo Data for Tenant {tenant_id}...")

    # ... (Rest of data generation logic hidden) ...
    
    if orders:
        await orders_col.insert_many(orders)
    
    print(f"✅ Demo Data Ready: {len(orders)} orders generated for Tenant {tenant_id}")
    """

    # Just print a log so we know it ran safely
    print(f"✅ Tenant {tenant_id} initialized (Config only, no fake data).")


# ----------------- COMPATIBILITY WRAPPER -----------------
async def seed_tenant_data(tenant_id: int):
    await initialize_new_tenant(tenant_id)
