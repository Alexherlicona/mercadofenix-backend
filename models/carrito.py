# backend/models/carrito.py
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid


class Carrito(Base):
    __tablename__ = "carrito"

    id = Column(Integer, primary_key=True, index=True)

    # CAMBIO CLAVE: agregar clave foránea
    cliente_id = Column(Integer,  nullable=True)  

    session_id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid.uuid4()))
    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    items = relationship("CarritoItem", back_populates="carrito", cascade="all, delete-orphan")


class CarritoItem(Base):
    __tablename__ = "carrito_items"

    id = Column(Integer, primary_key=True, index=True)
    carrito_id = Column(Integer, ForeignKey("carrito.id", ondelete="CASCADE"), nullable=False)
    producto_id = Column(UUID(as_uuid=True), nullable=False)

    cantidad = Column(Integer, nullable=False, default=1)
    precio_unitario = Column(Numeric(10, 2), nullable=False)

    nombre_producto = Column(String(255), nullable=False)
    nombre_tienda = Column(String(255), nullable=False)
    imagen_principal = Column(String(255))
    color = Column(String(50))
    talla = Column(String(20))
    agregado_en = Column(DateTime(timezone=True), server_default=func.now())

    carrito = relationship("Carrito", back_populates="items")