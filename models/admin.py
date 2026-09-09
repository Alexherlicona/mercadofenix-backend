# backend/models/admin.py
from sqlalchemy import Column, Integer, String, DateTime
from core.database import Base
from datetime import datetime

class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    usuario = Column(String, unique=True, index=True, nullable=False)  # ← AQUÍ ESTABA EL PROBLEMA
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)