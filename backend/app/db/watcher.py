# backend/app/db/watcher.py
from app.db.mongo import orders_col
from app.services.history_service import history_service
from app.utils.logger import setup_logger

log = setup_logger("db_watcher")


async def watch_orders():
    log.info("👀 STARTING LIVE ORDER WATCHER (Golden Record Engine)...")

    # Watch for updates (update) or overwrites (replace)
    pipeline = [{"$match": {"operationType": {"$in": ["update", "replace"]}}}]

    try:
        async with orders_col.watch(pipeline, full_document="updateLookup") as stream:
            async for change in stream:
                try:
                    new_doc = change.get("fullDocument")
                    if not new_doc:
                        continue

                    # 1. ID Extraction
                    order_id = new_doc.get("dpOrderId") or str(new_doc.get("_id"))

                    # 2. Tenant ID (CRITICAL FIX)
                    # We check 'waayuRestId' first.
                    # If it's missing, we check 'restaurant' (which might be an ObjectId).
                    # If it's an ObjectId, we might need to convert it string,
                    # BUT ideally we need the 'waayuRestId' string (e.g., '1222575').
                    tenant_id = new_doc.get("waayuRestId")

                    if not tenant_id:
                        # Fallback: Use stringified _id of the restaurant ref
                        # This is risky if your dashboard filters by numeric ID.
                        # Ideally, your aggregation pipeline should handle this.
                        r_ref = new_doc.get("restaurant")
                        tenant_id = str(r_ref) if r_ref else "0"

                    # 3. Changes
                    update_desc = change.get("updateDescription", {})
                    updated_fields = update_desc.get("updatedFields", {})

                    if change["operationType"] == "replace":
                        updated_fields = new_doc

                    # 4. Save
                    await history_service.record_change_mongo_native(
                        order_id=order_id, tenant_id=tenant_id, changes=updated_fields
                    )

                except Exception as e:
                    log.error(f"❌ Error processing change: {e}")

    except Exception as e:
        log.error(f"❌ Change Stream Failed: {e}")
