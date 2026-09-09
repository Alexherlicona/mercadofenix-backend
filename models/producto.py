# backend/models/producto.py
from sqlalchemy import (
    Column, String, Integer, Numeric, Text, JSON, Boolean,
    ForeignKey, DateTime, BigInteger, Date, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from core.database import Base
import uuid


class Producto(Base):
    __tablename__ = "productos"

    # ── Identidad ────────────────────────────────────────────────────────────
    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vendedor_id = Column(String(13), ForeignKey("vendedores.dni", ondelete="CASCADE"), nullable=False)
    slug        = Column(String(320), unique=True)

    # ── Clasificación ────────────────────────────────────────────────────────
    tipo        = Column(String(10),  nullable=False)   # 'fisico' | 'digital'
    categoria   = Column(String(100), nullable=False)
    nombre      = Column(String(255), nullable=False)
    subtitulo   = Column(String(300))
    idioma      = Column(String(30),  default="Español")
    etiquetas   = Column(ARRAY(Text), default=list)
    moneda      = Column(String(5),   default="HNL")

    # ── Precios ──────────────────────────────────────────────────────────────
    precio                = Column(Numeric(10, 2), nullable=False)
    precio_original       = Column(Numeric(10, 2))
    precio_con_descuento  = Column(Numeric(10, 2))
    porcentaje_descuento  = Column(Numeric(5, 2),  default=0)
    permite_oferta        = Column(Boolean,        default=True)
    precio_minimo_oferta  = Column(Numeric(10, 2))

    # ── Texto ────────────────────────────────────────────────────────────────
    descripcion = Column(Text)

    # ── Estado y visibilidad ─────────────────────────────────────────────────
    activo      = Column(Boolean, default=True)
    destacado   = Column(Boolean, default=False)
    vendido     = Column(Boolean, default=False)

    # ── Métricas ─────────────────────────────────────────────────────────────
    ventas_count      = Column(Integer,        default=0)
    vistas_count      = Column(Integer,        default=0)
    favoritos_count   = Column(Integer,        default=0)
    calificacion_prom = Column(Numeric(3, 2),  default=0)
    total_resenas     = Column(Integer,        default=0)

    # ── Timestamps ───────────────────────────────────────────────────────────
    creado_en      = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # ═══════════════════════════════════════════════════════════════════════
    # CAMPOS FÍSICOS
    # ═══════════════════════════════════════════════════════════════════════

    # Stock
    stock               = Column(Integer, default=1)
    stock_minimo_alerta = Column(Integer, default=0)
    permite_preventa    = Column(Boolean, default=False)

    # Variantes (colores, tallas, etc.)
    variantes = Column(JSONB, default=dict)
    # Ejemplo: {"colores":["Rojo","Negro"],"tallas":["S","M","L"],"stock_por_variante":{"Rojo-S":5}}

    # Identidad del producto
    condicion       = Column(String(15),  default="nuevo")
    sku             = Column(String(100))
    codigo_barras   = Column(String(100))
    marca           = Column(String(100))
    modelo          = Column(String(100))
    pais_origen     = Column(String(80))
    material        = Column(String(200))

    # Dimensiones y peso
    peso_gramos = Column(Integer)
    largo_cm    = Column(Numeric(8, 2))
    ancho_cm    = Column(Numeric(8, 2))
    alto_cm     = Column(Numeric(8, 2))

    # Garantía
    garantia_meses        = Column(Integer, default=0)
    descripcion_garantia  = Column(Text)

    # ═══════════════════════════════════════════════════════════════════════
    # CAMPOS DIGITALES
    # ═══════════════════════════════════════════════════════════════════════

    # Archivo principal
    archivo_key     = Column(String(255))
    formato_archivo = Column(String(30))    # pdf, zip, mp4, psd, figma...
    tamano_bytes    = Column(BigInteger)
    num_archivos    = Column(Integer)
    archivos_incluidos = Column(JSONB, default=list)
    # Ejemplo: [{"nombre":"src.zip","formato":"zip","tamano_bytes":204800},
    #           {"nombre":"README.pdf","formato":"pdf","tamano_bytes":30000}]

    # Versión y compatibilidad
    version           = Column(String(30))
    requiere_software = Column(ARRAY(Text), default=list)  # ['Photoshop CC 2023']
    compatibilidad    = Column(ARRAY(Text), default=list)  # ['Windows','Mac','Linux','Web']

    # Para código / proyectos
    lenguajes         = Column(ARRAY(Text), default=list)  # ['Python','TypeScript']
    frameworks        = Column(ARRAY(Text), default=list)  # ['React','FastAPI','Django']
    nivel_dificultad  = Column(String(20))                 # basico|intermedio|avanzado|experto
    incluye_soporte   = Column(Boolean, default=False)
    dias_soporte      = Column(Integer)

    # Para cursos / videos
    duracion_minutos  = Column(Integer)
    num_lecciones     = Column(Integer)

    # Para libros / documentos
    num_paginas       = Column(Integer)
    isbn              = Column(String(20))
    autor             = Column(String(200))
    editorial         = Column(String(200))
    fecha_publicacion = Column(Date)

    # Acceso y descarga
    max_descargas     = Column(Integer)    # NULL = ilimitado
    dias_acceso       = Column(Integer)    # NULL = para siempre
    preview_url       = Column(String(500))

    # Licencia
    licencia          = Column(String(20), default="personal")
    licencia_detalle  = Column(Text)
    permite_reventa   = Column(Boolean, default=False)
    permite_modificar = Column(Boolean, default=True)

    # ── Relaciones ───────────────────────────────────────────────────────────
    vendedor  = relationship("Vendedor",     back_populates="productos")
    fotos     = relationship("FotoProducto", back_populates="producto",
                             cascade="all, delete-orphan", lazy="joined",
                             order_by="FotoProducto.orden")
    favoritos = relationship("Favorito",     back_populates="producto")


class FotoProducto(Base):
    __tablename__ = "fotos_productos"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    producto_id = Column(UUID(as_uuid=True), ForeignKey("productos.id", ondelete="CASCADE"), nullable=False)
    url         = Column(String(255), nullable=False)
    orden       = Column(Integer, default=0)
    es_video    = Column(Boolean, default=False)   # para soportar demos en video
    alt_texto   = Column(String(255))              # accesibilidad / SEO

    producto = relationship("Producto", back_populates="fotos")

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "orden": self.orden,
            "es_video": self.es_video,
            "alt_texto": self.alt_texto,
        }