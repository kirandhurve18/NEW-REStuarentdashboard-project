# backend/app/services/history_service.py
from datetime import datetime
from app.db.mongo import history_col
from app.utils.logger import setup_logger

log = setup_logger("history_service")


class HistoryService:
    def _calculate_delta(self, old_doc: dict, new_doc: dict) -> dict:
        """
        Compares two order states and returns ONLY the changes.
        Used when we have both full documents (e.g., manual updates).
        """
        delta = {}
        ignored_keys = {"updatedAt", "last_updated", "_id", "__v"}

        for key, new_val in new_doc.items():
            if key in ignored_keys:
                continue

            old_val = old_doc.get(key)

            if new_val != old_val:
                if isinstance(new_val, dict) and isinstance(old_val, dict):
                    # Simple snapshot for nested dicts
                    if new_val != old_val:
                        delta[key] = {"old": old_val, "new": new_val}
                else:
                    delta[key] = {"old": old_val, "new": new_val}

        return delta

    async def record_change(
        self, order_id: str, old_doc: dict, new_doc: dict, tenant_id: str
    ):
        """
        Standard recording when we have both Old and New documents.
        """
        delta = self._calculate_delta(old_doc, new_doc)
        if not delta:
            return

        await self._persist_history(order_id, tenant_id, delta)

    async def record_change_mongo_native(
        self, order_id: str, tenant_id: str, changes: dict
    ):
        """
        Handles 'updatedFields' directly from MongoDB Change Streams.
        Since Change Streams (by default) don't give the 'Old' value,
        we record the 'New' value to maintain the timeline.
        """
        if not changes:
            return

        # Format changes into our Delta Structure
        # Format: "field": {"old": "N/A", "new": value}
        delta = {}
        ignored_keys = {"updatedAt", "last_updated", "_id", "__v"}

        for field, new_val in changes.items():
            if field in ignored_keys:
                continue
            delta[field] = {"old": "N/A", "new": new_val}

        if delta:
            await self._persist_history(order_id, tenant_id, delta, is_native=True)

    async def _persist_history(
        self, order_id: str, tenant_id: str, delta: dict, is_native: bool = False
    ):
        """
        Internal helper to save to DB.
        """
        # Determine Trigger
        trigger = "UPDATE"
        # Flatten keys for checking (e.g., "status.orderStatus" -> "status")
        flat_keys = [k.split(".")[0] for k in delta.keys()]

        if "status" in flat_keys or "orderStatus" in delta:
            trigger = "STATUS_UPDATE"
            # Try to extract readable status
            if "status.orderStatus" in delta:
                new_s = delta["status.orderStatus"].get("new")
                trigger = f"STATUS: {new_s}"
            elif "status" in delta and isinstance(delta["status"].get("new"), str):
                trigger = f"STATUS: {delta['status']['new']}"

        elif "pricing" in flat_keys or "item_total" in flat_keys:
            trigger = "FINANCIAL_UPDATE"

        history_entry = {
            "parent_order_id": order_id,
            "tenant_id": tenant_id,
            "delta": delta,
            "history_trigger": trigger,
            "history_created_at": datetime.utcnow(),
            "source": "live_watcher" if is_native else "manual",
        }

        try:
            await history_col.insert_one(history_entry)
            log.info(f"💾 Golden Record saved for {order_id} [{trigger}]")
        except Exception as e:
            log.error(f"❌ Failed to save history: {e}")


history_service = HistoryService()
