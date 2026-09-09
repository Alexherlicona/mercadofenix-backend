# backend/schemas.py
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal


# ==================== AUTH / CLIENTES ====================

class ClienteRegistro(BaseModel):
    """Body del POST /api/auth/registro"""
    nombres: str
    apellidos: str
    telefono: str
    password: str
    email: Optional[str] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    direccion_exacta: Optional[str] = None

class ClienteLogin(BaseModel):
    """Body del POST /api/auth/login"""
    telefono: str
    password: str

# Alias para que routes/auth.py siga funcionando sin cambios
# (el archivo usa LoginData como parámetro del endpoint login)
LoginData = ClienteLogin

class ClienteOut(BaseModel):
    """Respuesta con datos del cliente"""
    id: int
    nombres: str
    apellidos: str
    telefono: str
    email: Optional[str]
    departamento: Optional[str]
    municipio: Optional[str]
    direccion_exacta: Optional[str]
    creado_en: datetime
    actualizado_en: datetime

    class Config:
        from_attributes = True

class PerfilUpdate(BaseModel):
    """Body del PUT /api/auth/perfil"""
    nombres: Optional[str] = None
    apellidos: Optional[str] = None
    email: Optional[str] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    direccion_exacta: Optional[str] = None
    telefono: Optional[str] = None

    class Config:
        from_attributes = True


# ==================== PAGOS ====================

class PagoCreate(BaseModel):
    vendor_dni: str
    plan: str           # "basico" | "premium"
    meses_pagados: int
    monto: float
    metodo_pago: str
    comprobante_url: Optional[str] = None
    fecha_pago: Optional[date] = None

class PagoOut(BaseModel):
    id: int
    vendor_dni: str
    plan: str
    meses_pagados: int
    monto: float
    metodo_pago: str
    comprobante_url: Optional[str]
    fecha_pago: date
    fecha_aprobacion: Optional[datetime]

    class Config:
        from_attributes = True


# ==================== DIRECCIONES ====================

class DireccionCreate(BaseModel):
    nombre_direccion: str       # "Casa", "Trabajo", etc.
    departamento: str
    municipio: str
    direccion_exacta: str
    referencia: Optional[str] = None
    telefono_contacto: Optional[str] = None
    es_principal: bool = False

class DireccionUpdate(BaseModel):
    nombre_direccion: Optional[str] = None
    departamento: Optional[str] = None
    municipio: Optional[str] = None
    direccion_exacta: Optional[str] = None
    referencia: Optional[str] = None
    telefono_contacto: Optional[str] = None
    es_principal: Optional[bool] = None

class DireccionOut(BaseModel):
    id: int
    nombre_direccion: str
    departamento: str
    municipio: str
    direccion_exacta: str
    referencia: Optional[str]
    telefono_contacto: Optional[str]
    es_principal: bool
    creado_en: datetime

    class Config:
        from_attributes = True


# ==================== PEDIDOS ====================

class PedidoItemCreate(BaseModel):
    producto_id: str        # UUID como string
    nombre_producto: str
    precio_unitario: Decimal
    cantidad: int
    color: Optional[str] = None
    talla: Optional[str] = None

class PedidoItemOut(BaseModel):
    id: int
    producto_id: str
    nombre_producto: str
    precio_unitario: Decimal
    cantidad: int
    subtotal: Decimal
    color: Optional[str]
    talla: Optional[str]

    class Config:
        from_attributes = True

class PedidoCreate(BaseModel):
    direccion_id: Optional[int] = None
    direccion_alternativa: Optional[str] = None
    items: List[PedidoItemCreate]
    tipo_entrega: str       # "domicilio" | "tienda" | "oficina_fenix"
    metodo_pago: str        # "efectivo" | "transferencia"
    nota_cliente: Optional[str] = None

class PedidoOut(BaseModel):
    id: int
    cliente_id: int
    vendedor_id: Optional[str]
    estado: str
    tipo_entrega: str
    metodo_pago: str
    subtotal: Decimal
    costo_envio: Decimal
    total: Decimal
    items: List[PedidoItemOut]
    fecha_pedido: datetime
    fecha_confirmacion: Optional[datetime]
    fecha_entrega_real: Optional[datetime]

    class Config:
        from_attributes = True

class PedidoUpdateEstado(BaseModel):
    estado: str     # "pendiente"|"confirmado"|"en_preparacion"|"en_camino"|"entregado"|"cancelado"
    nota_vendedor: Optional[str] = None