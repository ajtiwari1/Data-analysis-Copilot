from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from middleware.database import Base


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (
        UniqueConstraint("user_id", "slug", name="uq_sites_user_slug"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(
        String(3), default="USD", server_default="USD"
    )
    is_demo: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    products: Mapped[list["Product"]] = relationship(
        back_populates="site", cascade="all, delete-orphan"
    )
