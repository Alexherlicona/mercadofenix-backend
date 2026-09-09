# backend/models/vendedor.py
from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, JSON, Float
from core.database import Base
from sqlalchemy.orm import relationship
from datetime import datetime

class Vendedor(Base):
    __tablename__ = "vendedores"

    dni            = Column(String(13),  primary_key=True, index=True)
    rtn            = Column(String(14),  unique=True, index=True, nullable=True)
    propietario    = Column(String(100), nullable=False)
    nombre_tienda  = Column(String(100), nullable=False)
    telefono       = Column(String(8),   unique=True, index=True, nullable=False)
    email          = Column(String(120), unique=True, index=True, nullable=True)  # ← NUEVO
    departamento   = Column(String(50),  nullable=False)
    municipio      = Column(String(50),  nullable=False)
    direccion_exacta = Column(Text,      nullable=False)
    password_hash  = Column(String(255), nullable=False)
    logo_url       = Column(String,      nullable=True)
    documento_url  = Column(Text,        nullable=True)   # ← NUEVO — foto del DNI/pasaporte
    tipo_pago      = Column(String(50),  nullable=True)
    tipo_entrega   = Column(String(50),  nullable=True)

    # Ubicación de la tienda                                ← NUEVO
    latitud         = Column(Float,  nullable=True)
    longitud        = Column(Float,  nullable=True)
    google_maps_url = Column(Text,   nullable=True)

    # Estado y plan
    activo             = Column(Boolean,  default=False)
    solicitud_pendiente = Column(Boolean, default=True)
    plan               = Column(String,   default="prueba")
    meses_pagados      = Column(Integer,  default=0)
    fecha_pago         = Column(DateTime, default=datetime.utcnow)
    fecha_solicitud    = Column(DateTime, default=datetime.utcnow)
    fecha_aprobacion   = Column(DateTime, nullable=True)
    fecha_expiracion   = Column(DateTime(timezone=True), nullable=True)
    aprobado_por       = Column(String(50), nullable=True)
    ips                = Column(JSON,    default=list)
    visitas_totales    = Column(Integer, default=0)

    # Relaciones
    productos = relationship("Producto", back_populates="vendedor", cascade="all, delete-orphan")
    pedidos   = relationship("Pedido",   back_populates="vendedor", cascade="all, delete-orphan")