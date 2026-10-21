"""ORM models: users and their reminders."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # chat_id
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Tashkent")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Reminder(Base):
    __tablename__ = "reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    message: Mapped[str] = mapped_column(Text)
    original_text: Mapped[str] = mapped_column(Text)
    human_readable: Mapped[str] = mapped_column(String(256))

    # Serialized app.nlp.recurrence.Schedule
    schedule_kind: Mapped[str] = mapped_column(String(16))
    schedule_spec: Mapped[str] = mapped_column(Text)

    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PendingDraft(Base):
    """Owner-scoped date awaiting an explicit clock; never a reminder row."""

    __tablename__ = "pending_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    original_text: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    target_date: Mapped[date] = mapped_column(Date)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PendingBatch(Base):
    """Owner-scoped preview awaiting an explicit confirmation action."""

    __tablename__ = "pending_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    original_text: Mapped[str] = mapped_column(Text)
    items_json: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
