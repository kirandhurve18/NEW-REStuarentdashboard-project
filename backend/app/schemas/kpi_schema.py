# backend/app/schemas/kpi_schema.py
from pydantic import BaseModel
from typing import Any, Dict


class KPIResponse(BaseModel):
    data: Dict[str, Any]
