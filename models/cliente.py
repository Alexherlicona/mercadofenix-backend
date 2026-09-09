# backend/models/cliente.py - VERSIÓN ACTUALIZADA
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from core.database import Base
from sqlalchemy.orm import relationship

class Cliente(Base):
    __tablename__ = "clientes"

    id = Column(Integer, primary_key=True, index=True)
    nombres = Column(String(100), nullable=False)
    apellidos = Column(String(100), nullable=False)
    telefono = Column(String(20), unique=True, index=True, nullable=False)  # Login principal
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=False)
    departamento = Column(String(50), nullable=True)
    municipio = Column(String(100), nullable=True)
    direccion_exacta = Column(String(255), nullable=True)
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relaciones
    favoritos = relationship("Favorito", back_populates="cliente", cascade="all, delete-orphan")
    direcciones = relationship("Direccion", back_populates="cliente", cascade="all, delete-orphan")  # ← NUEVO
    pedidos = relationship("Pedido", back_populates="cliente", cascade="all, delete-orphan")  # ← NUEVO