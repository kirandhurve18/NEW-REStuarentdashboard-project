# backend/app/models/store_model.py

from pydantic import BaseModel, Field
from typing import Optional


class FixedCosts(BaseModel):
    rent: float = 0.0
    electricity: float = 0.0
    salaries: float = 0.0
    maintenance: float = 0.0
    miscellaneous: float = 0.0


class DailyTargets(BaseModel):
    weekday_target: float = Field(default=10000.0, alias="weekday")
    weekend_target: float = Field(default=15000.0, alias="weekend")


class StoreModel(BaseModel):
    # [cite_start]Live uses String ID (waayuRestId) [cite: 447]
    tenant_id: str = Field(alias="waayuRestId")

    store_name: Optional[str] = Field(alias="storeName")
    address: Optional[dict] = None  # Live uses nested object, simpler to keep as dict

    # 🟢 CONFIGURATION (Mapped to CamelCase fields in DB)
    food_cost_percentage: float = Field(default=35.0, alias="foodCostPercentage")

    # Maps 'fixedCosts' (DB) -> 'fixed_costs' (Python)
    fixed_costs: Optional[FixedCosts] = Field(
        default_factory=FixedCosts, alias="fixedCosts"
    )

    # Maps 'dailyTargets' (DB) -> 'daily_targets' (Python)
    daily_targets: Optional[DailyTargets] = Field(
        default_factory=DailyTargets, alias="dailyTargets"
    )

    class Config:
        populate_by_name = True
