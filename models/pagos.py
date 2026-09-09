# backend/models/pago.py
from sqlalchemy import Column, Integer, String, Numeric, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base

class Pago(Base):
    __tablename__ = "pagos"

    id              = Column(Integer,      primary_key=True, index=True)
    vendor_dni      = Column(String(13),   ForeignKey("vendedores.dni", ondelete="RESTRICT"), nullable=False, index=True)
    plan            = Column(String(20),   nullable=False)
    meses_pagados   = Column(Integer,      nullable=False)
    monto           = Column(Numeric(10,2),nullable=False)
    metodo_pago     = Column(String(30),   nullable=False, default="efectivo")
    comprobante_url = Column(Text,         nullable=True)
    aprobado        = Column(Boolean,      default=False)
    # FK a admins — sin back_populates porque Admin no declara la relación inversa
    aprobado_por    = Column(Integer,      ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    fecha_pago      = Column(Date,         nullable=False, server_default=func.current_date())
    fecha_aprobacion= Column(DateTime(timezone=True), nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Columnas de período y emisor (agrega con migracion_pagos_columnas.sql)
    fecha_inicio_periodo = Column(DateTime(timezone=True), nullable=True)
    fecha_fin_periodo    = Column(DateTime(timezone=True), nullable=True)
    emisor               = Column(String(100), nullable=True)

    # Sin back_populates — Vendedor no declara la relación inversa para evitar
    # errores de inicialización de mappers cuando Pago se carga antes que Vendedor.
    # Los pagos se consultan siempre por query directa: db.query(Pago).filter(Pago.vendor_dni == dni)
    vendedor = relationship("Vendedor", foreign_keys=[vendor_dni])