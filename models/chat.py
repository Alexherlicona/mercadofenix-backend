# backend/models/chat.py
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base


class ChatSala(Base):
    """
    Una sala de chat por pedido.
    Vincula a un cliente con un vendedor en el contexto de un pedido específico.
    """
    __tablename__ = "chat_salas"

    id = Column(Integer, primary_key=True, index=True)
    pedido_id = Column(Integer, ForeignKey("pedidos.id", ondelete="CASCADE"), nullable=False, unique=True)
    cliente_id = Column(Integer, ForeignKey("clientes.id", ondelete="CASCADE"), nullable=False)
    vendedor_id = Column(String(13), ForeignKey("vendedores.dni", ondelete="CASCADE"), nullable=False)

    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    ultimo_mensaje_en = Column(DateTime(timezone=True), nullable=True)

    # Relaciones
    mensajes = relationship("ChatMensaje", back_populates="sala", cascade="all, delete-orphan", order_by="ChatMensaje.enviado_en")
    pedido = relationship("Pedido")
    cliente = relationship("Cliente")
    vendedor = relationship("Vendedor")


class ChatMensaje(Base):
    """
    Mensaje individual dentro de una sala de chat.
    El remitente puede ser "cliente" o "vendedor".
    """
    __tablename__ = "chat_mensajes"

    id = Column(Integer, primary_key=True, index=True)
    sala_id = Column(Integer, ForeignKey("chat_salas.id", ondelete="CASCADE"), nullable=False, index=True)

    # Quién envió: "cliente" | "vendedor"
    remitente_tipo = Column(String(10), nullable=False)
    remitente_id = Column(String(13), nullable=False)   # id del cliente (int→str) o dni del vendedor

    contenido = Column(Text, nullable=False)

    # Para comprobantes de pago
    es_comprobante = Column(Boolean, default=False)
    archivo_url = Column(String(255), nullable=True)    # URL de imagen del comprobante

    leido_cliente = Column(Boolean, default=False)
    leido_vendedor = Column(Boolean, default=False)

    enviado_en = Column(DateTime(timezone=True), server_default=func.now())

    # Relación
    sala = relationship("ChatSala", back_populates="mensajes")
