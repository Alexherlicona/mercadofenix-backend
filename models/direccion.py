# backend/models/direccion.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base

class Direccion(Base):
    __tablename__ = "direcciones"

    id = Column(Integer, primary_key=True, index=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False, index=True)
    
    nombre_direccion = Column(String(100), nullable=False)  # "Casa", "Trabajo", etc
    departamento = Column(String(50), nullable=False)
    municipio = Column(String(50), nullable=False)
    direccion_exacta = Column(Text, nullable=False)
    referencia = Column(Text, nullable=True)
    telefono_contacto = Column(String(8), nullable=True)
    
    es_principal = Column(Boolean, default=False)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relación
    cliente = relationship("Cliente", back_populates="direcciones")
    pedidos = relationship("Pedido", back_populates="direccion")