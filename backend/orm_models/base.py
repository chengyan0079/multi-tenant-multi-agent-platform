"""SQLAlchemy 声明基类（2.x async）。"""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有模型公共基类。"""
