# backend/models/reporte.py
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func
from core.database import Base

class Reporte(Base):
    """Reporte enviado por un cliente sobre una tienda, producto o servicio."""
    __tablename__ = "reportes"

    id              = Column(Integer,     primary_key=True, index=True)
    cliente_id      = Column(Integer,     ForeignKey("clientes.id",   ondelete="SET NULL"), nullable=True)
    nombre_reporter = Column(String(100), nullable=False)
    email_reporter  = Column(String(120), nullable=True)
    tipo_reporte    = Column(String(30),  nullable=False)   # tienda | producto | servicio | otro
    vendedor_dni    = Column(String(13),  ForeignKey("vendedores.dni", ondelete="SET NULL"), nullable=True)
    vendedor_nombre = Column(String(100), nullable=True)
    pedido_id       = Column(Integer,     nullable=True)
    titulo          = Column(String(200), nullable=False)
    descripcion     = Column(Text,        nullable=False)
    evidencia_url   = Column(Text,        nullable=True)
    estado          = Column(String(20),  nullable=False, default="pendiente")
    prioridad       = Column(String(10),  nullable=False, default="normal")
    nota_admin      = Column(Text,        nullable=True)
    resuelto_por    = Column(Integer,     ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    creado_en       = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Sugerencia(Base):
    """Sugerencia o queja enviada por un vendedor sobre la plataforma."""
    __tablename__ = "sugerencias"

    id            = Column(Integer,     primary_key=True, index=True)
    vendedor_dni  = Column(String(13),  ForeignKey("vendedores.dni", ondelete="CASCADE"), nullable=False)
    nombre_tienda = Column(String(100), nullable=False)
    tipo          = Column(String(30),  nullable=False)   # sugerencia | queja | error | mejora
    titulo        = Column(String(200), nullable=False)
    descripcion   = Column(Text,        nullable=False)
    estado        = Column(String(20),  nullable=False, default="nueva")
    prioridad     = Column(String(10),  nullable=False, default="normal")
    nota_admin    = Column(Text,        nullable=True)
    respondido_por= Column(Integer,     ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    creado_en     = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en= Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())