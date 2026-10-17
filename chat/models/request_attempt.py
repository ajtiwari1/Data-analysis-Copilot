from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from middleware.database import Base


class ChatRequestAttempt(Base):
    __tablename__ = "chat_request_attempts"
    __table_args__ = (Index("ix_chat_request_attempts_user_time", "user_id", "attempted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
