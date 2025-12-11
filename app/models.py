
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship, Column, DateTime
from sqlalchemy import func


class Chat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(index=True, unique=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Subscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(foreign_key="chat.chat_id", index=True)
    coin_id: str = Field(index=True)
    interval_seconds: int = Field(default=300)
    currency: str = Field(default="usd")
    last_sent: Optional[int] = Field(default=0, description="unix timestamp of last sent")


class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    chat_id: int = Field(foreign_key="chat.chat_id", index=True)
    coin_id: str = Field(index=True)
    direction: str = Field(description="'above' or 'below'")
    target_price: float
    currency: str = Field(default="usd")
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_triggered_at: Optional[int] = Field(default=0, description="unix timestamp when last triggered")
