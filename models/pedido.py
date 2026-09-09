# backend/models/pedido.py
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from core.database import Base

class Pedido(Base):
    __tablename__ = "pedidos"

    id          = Column(Integer, primary_key=True, index=True)
    cliente_id  = Column(Integer, ForeignKey("clientes.id",   ondelete="CASCADE"),  nullable=False, index=True)
    vendedor_id = Column(String(13), ForeignKey("vendedores.dni", ondelete="SET NULL"), nullable=True,  index=True)

    # Dirección (solo pedidos físicos)
    direccion_id          = Column(Integer, ForeignKey("direcciones.id", ondelete="SET NULL"), nullable=True)
    direccion_alternativa = Column(Text, nullable=True)

    # Estado
    estado      = Column(String(30), default="pendiente", index=True)

    # Entrega y pago
    tipo_entrega = Column(String(20), nullable=False)   # "domicilio" | "tienda" | "digital"
    metodo_pago  = Column(String(30), nullable=False)   # "efectivo" | "transferencia" | "tigo_money"

    # Montos
    subtotal    = Column(Numeric(12, 2), nullable=False)
    costo_envio = Column(Numeric(10, 2), default=0.00)
    total       = Column(Numeric(12, 2), nullable=False)

    # Notas
    nota_cliente  = Column(Text, nullable=True)
    nota_vendedor = Column(Text, nullable=True)

    # Fechas
    fecha_pedido           = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    fecha_confirmacion     = Column(DateTime(timezone=True), nullable=True)
    fecha_entrega_estimada = Column(DateTime(timezone=True), nullable=True)
    fecha_entrega_real     = Column(DateTime(timezone=True), nullable=True)

    activo = Column(Boolean, default=True)

    # ── Campos para productos digitales ──────────────────────────────────────
    es_digital              = Column(Boolean, default=False)
    descarga_habilitada     = Column(Boolean, default=False)
    descarga_token          = Column(String(128), unique=True, nullable=True)
    descarga_habilitada_en  = Column(DateTime(timezone=True), nullable=True)
    descarga_realizada      = Column(Boolean, default=False)
    descarga_realizada_en   = Column(DateTime(timezone=True), nullable=True)

    # Relaciones
    cliente  = relationship("Cliente",   back_populates="pedidos")
    vendedor = relationship("Vendedor",  back_populates="pedidos")
    direccion = relationship("Direccion", back_populates="pedidos")
    items    = relationship("PedidoItem", back_populates="pedido", cascade="all, delete-orphan")


class PedidoItem(Base):
    __tablename__ = "pedido_items"

    id         = Column(Integer, primary_key=True, index=True)
    pedido_id  = Column(Integer, ForeignKey("pedidos.id",    ondelete="CASCADE"),   nullable=False, index=True)
    producto_id = Column(UUID(as_uuid=True), ForeignKey("productos.id", ondelete="RESTRICT"), nullable=False, index=True)

    nombre_producto = Column(String(255), nullable=False)
    precio_unitario = Column(Numeric(10, 2), nullable=False)
    cantidad        = Column(Integer, nullable=False)
    subtotal        = Column(Numeric(12, 2), nullable=False)

    color = Column(String(50), nullable=True)
    talla = Column(String(20), nullable=True)

    creado_en = Column(DateTime(timezone=True), server_default=func.now())

    pedido = relationship("Pedido", back_populates="items")