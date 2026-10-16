from datetime import datetime
from datetime import date as Date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserResponse(BaseModel):
    id: int
    email: EmailStr
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardResponse(BaseModel):
    message: str
    user: UserResponse


class SiteResponse(BaseModel):
    id: int
    name: str
    url: str
    currency: str
    is_demo: bool

    model_config = ConfigDict(from_attributes=True)


class ProductResponse(BaseModel):
    id: int
    site_id: int
    name: str
    sku: str
    category: str
    unit_price: Decimal

    model_config = ConfigDict(from_attributes=True)


class DailySalesResponse(BaseModel):
    date: Date
    revenue: float
    orders: int
    units_sold: int


class ProductSalesResponse(BaseModel):
    product_id: int
    name: str
    sku: str
    revenue: float
    orders: int
    units_sold: int


class AnalyticsOverviewResponse(BaseModel):
    start_date: Date
    end_date: Date
    currency: str
    revenue: float
    orders: int
    units_sold: int
    average_order_value: float
    daily_sales: list[DailySalesResponse]
    product_sales: list[ProductSalesResponse]
