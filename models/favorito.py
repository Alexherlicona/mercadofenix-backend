# backend/models/favorito.py

from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from core.database import Base
from datetime import datetime

class Favorito(Base):
    __tablename__ = "favoritos"

    cliente_id = Column(
        Integer,
        ForeignKey("clientes.id", ondelete="CASCADE"),
        primary_key=True
    )
    producto_id = Column(
        UUID(as_uuid=True),
        ForeignKey("productos.id", ondelete="CASCADE"),
        primary_key=True
    )
    creado_en = Column(DateTime(timezone=True), default=datetime.utcnow)

    # ← CAMBIO AQUÍ: usa strings
    cliente = relationship("Cliente", back_populates="favoritos")
    producto = relationship("Producto", back_populates="favoritos")