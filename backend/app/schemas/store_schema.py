# backend/app/schemas/store_schema.py
from pydantic import BaseModel, Field
from typing import Optional


class FixedCostSchema(BaseModel):
    rent: float = 0
    salaries: float = 0
    electricity: float = 0
    maintenance: float = 0
    miscellaneous: float = 0


class TargetSchema(BaseModel):
    # Maps DB 'weekday' -> API 'weekday_target'
    weekday_target: float = Field(alias="weekday", default=10000.0)
    weekend_target: float = Field(alias="weekend", default=15000.0)

    class Config:
        populate_by_name = True


class StoreOut(BaseModel):
    tenant_id: str = Field(alias="waayuRestId")
    store_name: Optional[str] = Field(alias="storeName")

    # Address might come as object or string, handled in Router usually,
    # but here we define basic expectation
    address: Optional[str] = None
    phone: Optional[str] = Field(alias="mobile")
    email: Optional[str] = None

    # Nested Configs
    fixed_costs: Optional[FixedCostSchema] = Field(alias="fixedCosts")
    daily_targets: Optional[TargetSchema] = Field(alias="dailyTargets")

    class Config:
        populate_by_name = True
