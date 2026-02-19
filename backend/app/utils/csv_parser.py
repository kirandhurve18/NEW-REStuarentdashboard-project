# backend/app/utils/csv_parser.py
import pandas as pd
import io
import re
from typing import List, Dict, Any


class SettlementParser:
    @staticmethod
    def clean_currency(value) -> float:
        """
        Converts currency strings like '₹ 1,200.50' or '(200)' to floats.
        Handles negatives in parentheses or with minus signs.
        """
        if pd.isna(value) or value == "":
            return 0.0

        s = str(value).strip()
        # Handle accounting negatives: (100) -> -100
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]

        # Remove symbols
        s = s.replace("₹", "").replace(",", "").replace(" ", "")

        try:
            return float(s)
        except ValueError:
            return 0.0

    @staticmethod
    def extract_utr(content: bytes, is_excel: bool) -> str:
        """
        Attempts to find a UTR / Bank Reference Number in the raw file content.
        Useful because sometimes UTR is in the summary sheet, not the order row.
        """
        try:
            # Convert bytes to string for regex search
            text = ""
            if is_excel:
                # Read specific cells from Summary/Glossary if possible,
                # or just crude string conversion of the first few bytes/rows
                try:
                    xls = pd.ExcelFile(io.BytesIO(content))
                    if "Summary" in xls.sheet_names:
                        df = pd.read_excel(xls, sheet_name="Summary", header=None)
                        text = df.to_string()
                    elif "Payout Breakup" in xls.sheet_names:
                        df = pd.read_excel(
                            xls, sheet_name="Payout Breakup", header=None
                        )
                        text = df.to_string()
                except Exception:
                    pass
            else:
                text = content.decode("utf-8", errors="ignore")[:2000]  # First 2kb

            # Patterns for UTR (AXIS..., CMS..., NEFT...)
            # Zomato 2026 usually lists it under "Bank UTR" in Summary
            match = re.search(
                r"(?:UTR|Reference|Ref)\s*[:#-]?\s*([A-Z0-9]{10,25})",
                text,
                re.IGNORECASE,
            )
            if match:
                return match.group(1)

            return "N/A"
        except Exception:
            return "N/A"

    @staticmethod
    def normalize_header(header: str) -> str:
        """
        Maps CSV/Excel headers to internal keys.
        Supports both 2024 legacy and 2026 new formats.
        """
        h = str(header).lower().strip().replace("\n", " ")

        # --- COMMON ---
        if "order id" in h and "parent" not in h:
            return "order_id"
        if "order date" in h:
            return "order_date"

        # --- ZOMATO 2026 MAPPING ---
        # "Order level payout" -> Net Amount
        if "order level payout" in h:
            return "net_amount"
        if "settlement status" in h:
            return "status"
        # "Subtotal (items total)" -> Item Total
        if "subtotal" in h and "items total" in h:
            return "item_total"
        # "Service fees & payment mechanism fees" -> Platform Fee (Logic: Base + Gateway)
        if "service fees" in h and "payment mechanism" in h:
            return "platform_fee"
        # Fallback for Zomato Fee: "Net Deductions" (often includes taxes)
        if "net deductions" in h:
            return "platform_fee_fallback"
        if "gst" in h and "collected from customer" in h:
            return "gst_customer"

        # --- SWIGGY 2026 MAPPING ---
        # "Net Payout for Order (after taxes)" -> Net Amount
        if "net payout for order" in h:
            return "net_amount"
        # "Item Total" -> Item Total
        if "item total" in h:
            return "item_total"
        # "Total Swiggy Fees" -> Platform Fee
        if "total swiggy fees" in h:
            return "platform_fee"
        if "order status" in h:
            return "status"

        return h

    @staticmethod
    def process_dataframe(
        df: pd.DataFrame, platform_name: str, global_utr: str
    ) -> List[Dict[str, Any]]:
        parsed_data = []

        # 1. SMART HEADER DETECTION
        # Scan first 20 rows to find the main header row (containing "Order ID")
        header_row_idx = -1
        for i, row in df.head(20).iterrows():
            row_str = " ".join([str(v).lower() for v in row.values])
            if "order id" in row_str and ("date" in row_str or "status" in row_str):
                header_row_idx = i
                break

        if header_row_idx != -1:
            # Set the found row as header
            df.columns = df.iloc[header_row_idx]
            # Drop the header row and everything before it
            df = df.iloc[header_row_idx + 1 :].reset_index(drop=True)

        # 2. Normalize Columns
        df.columns = [SettlementParser.normalize_header(c) for c in df.columns]

        # 3. Iterate Rows
        for _, row in df.iterrows():
            # Basic Validation
            if "order_id" not in row or pd.isna(row["order_id"]):
                continue

            oid = str(row["order_id"]).strip()
            if not oid or oid.lower() == "nan":
                continue

            # --- DATA EXTRACTION ---
            item_total = SettlementParser.clean_currency(row.get("item_total", 0))
            net_amount = SettlementParser.clean_currency(row.get("net_amount", 0))

            # --- FEE LOGIC ---
            # Priority 1: Explicit Fee Column
            p_fee = SettlementParser.clean_currency(row.get("platform_fee", 0))

            # Priority 2: Fallback (Zomato sometimes puts it in Net Deductions)
            if p_fee == 0 and "platform_fee_fallback" in row:
                p_fee = SettlementParser.clean_currency(row["platform_fee_fallback"])

            # Priority 3: Calculation (Item Total - Net Payout)
            # Only if status is 'settled'/'delivered' and fee is still 0
            status = str(row.get("status", "")).lower()
            if p_fee == 0 and item_total > 0 and net_amount > 0:
                # Rough estimate logic if columns fail (Not ideal, but better than 0)
                # Note: This includes taxes, so use with caution.
                pass

            # Absolute value for fees
            p_fee = abs(p_fee)

            parsed_data.append(
                {
                    "order_id": oid,
                    "platform": platform_name,
                    "status": status if status else "settled",
                    "item_total": item_total,  # ✅ Vital for % Calculation
                    "net_amount": net_amount,
                    "platform_fee": p_fee,  # ✅ Vital for % Calculation
                    "utr": global_utr,
                }
            )

        return parsed_data

    @staticmethod
    def parse_file(content: bytes, filename: str) -> List[Dict[str, Any]]:
        is_excel = filename.endswith((".xlsx", ".xls"))

        # 1. Extract UTR (Global for file)
        global_utr = SettlementParser.extract_utr(content, is_excel)

        # 2. Determine Platform
        platform = "zomato" if "zomato" in filename.lower() else "swiggy"

        try:
            if is_excel:
                xls = pd.ExcelFile(io.BytesIO(content))

                # SMART SHEET SELECTION (2026 Compatible)
                # Zomato 2026 -> "Order Level"
                # Swiggy 2026 -> "Order Level"
                target_sheet = None
                for sheet in xls.sheet_names:
                    if "order level" in sheet.lower().strip():
                        target_sheet = sheet
                        break

                if not target_sheet:
                    # Fallback to first sheet
                    target_sheet = xls.sheet_names[0]

                # Read without header first, we find it dynamically in process_dataframe
                df = pd.read_excel(xls, sheet_name=target_sheet, header=None)
            else:
                df = pd.read_csv(io.BytesIO(content), header=None)

            return SettlementParser.process_dataframe(df, platform, global_utr)

        except Exception as e:
            print(f"Error parsing settlement file: {e}")
            return []
