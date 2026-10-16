from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from middleware.database import Base


class SalesRecord(Base):
    __tablename__ = "sales_records"
    __table_args__ = (
        UniqueConstraint(
            "site_id", "order_id", "product_id", name="uq_sales_site_order_product"
        ),
        ForeignKeyConstraint(
            ["site_id", "product_id"],
            ["products.site_id", "products.id"],
            name="fk_sales_product_site",
            ondelete="CASCADE",
        ),
        Index("ix_sales_site_date", "site_id", "sale_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("sites.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(Integer, index=True)
    order_id: Mapped[str] = mapped_column(String(100))
    sale_date: Mapped[date] = mapped_column(Date, index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    gross_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    discount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), server_default=text("0")
    )
