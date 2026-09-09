# backend/routes/descargas.py
"""
Endpoints para el sistema de descarga de productos digitales.

Flujo:
  1. Cliente compra → pedido creado con es_digital=True, descarga_habilitada=False
  2. Cliente envía comprobante por chat
  3. Vendedor verifica pago → llama POST /api/descargas/{pedido_id}/habilitar
  4. Backend genera token único y guarda en pedido.descarga_token
  5. GET /api/descargas/archivo/{token} → descarga el archivo (solo una vez)
"""
import os, secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from core.database import get_db
from core.auth import get_current_vendedor, get_current_user
from models.pedido import Pedido, PedidoItem
from models.producto import Producto
from models.cliente import Cliente
from models.vendedor import Vendedor

router = APIRouter(prefix="/api/descargas", tags=["descargas"])


# ── Habilitar descarga (acción del vendedor) ──────────────────────────────────
@router.post("/{pedido_id}/habilitar")
async def habilitar_descarga(
    pedido_id: int,
    vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """
    El vendedor autoriza la descarga tras verificar el pago.
    Genera un token único y lo guarda en el pedido.
    """
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == vendedor.dni
    ).first()

    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")

    if not pedido.es_digital:
        raise HTTPException(400, "Este pedido no es de un producto digital")

    if pedido.descarga_habilitada:
        # Ya habilitado — devolver token existente para reenviar al cliente
        return {
            "ok": True,
            "ya_habilitado": True,
            "descarga_token": pedido.descarga_token,
            "descarga_url": f"/api/descargas/archivo/{pedido.descarga_token}",
        }

    # Generar token seguro
    token = secrets.token_urlsafe(48)
    pedido.descarga_habilitada      = True
    pedido.descarga_token           = token
    pedido.descarga_habilitada_en   = datetime.utcnow()

    # Avanzar estado del pedido a "entregado" automáticamente
    pedido.estado                   = "entregado"
    pedido.fecha_entrega_real       = datetime.utcnow()

    db.commit()

    return {
        "ok": True,
        "ya_habilitado": False,
        "descarga_token": token,
        "descarga_url": f"/api/descargas/archivo/{token}",
        "mensaje_para_chat": f"✅ ¡Pago verificado! Tu descarga está lista:\n🔗 Haz clic aquí para descargar tu archivo:\n/api/descargas/archivo/{token}",
    }


# ── Estado de descarga de un pedido (cliente) ─────────────────────────────────
@router.get("/{pedido_id}/estado")
async def estado_descarga(
    pedido_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """El cliente consulta si su descarga ya está habilitada."""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.cliente_id == current_user.id
    ).first()

    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")

    return {
        "es_digital":          pedido.es_digital,
        "descarga_habilitada": pedido.descarga_habilitada,
        "descarga_realizada":  pedido.descarga_realizada,
        "descarga_token":      pedido.descarga_token if pedido.descarga_habilitada else None,
    }


# ── Descarga real del archivo (token público) ─────────────────────────────────
@router.get("/archivo/{token}")
async def descargar_archivo(
    token: str,
    db: Session = Depends(get_db)
):
    """
    Descarga el archivo digital asociado al token.
    No requiere auth — el token es el acceso.
    Permite múltiples descargas si max_descargas no se ha alcanzado.
    """
    pedido = db.query(Pedido).filter(
        Pedido.descarga_token == token,
        Pedido.descarga_habilitada == True,
    ).first()

    if not pedido:
        raise HTTPException(404, "Link de descarga inválido o no habilitado")

    # Obtener el producto digital del pedido
    item = db.query(PedidoItem).filter(PedidoItem.pedido_id == pedido.id).first()
    if not item:
        raise HTTPException(404, "Producto no encontrado en el pedido")

    producto = db.query(Producto).filter(Producto.id == item.producto_id).first()
    if not producto or not producto.archivo_key:
        raise HTTPException(404, "Archivo no disponible")

    # Verificar límite de descargas si aplica
    if producto.max_descargas is not None and pedido.descarga_realizada:
        raise HTTPException(403, "El límite de descargas ha sido alcanzado para este pedido")

    # Construir ruta física del archivo
    archivo_path = f"public{producto.archivo_key}"
    if not os.path.exists(archivo_path):
        raise HTTPException(404, "Archivo no encontrado en el servidor")

    # Registrar descarga
    pedido.descarga_realizada    = True
    pedido.descarga_realizada_en = datetime.utcnow()
    db.commit()

    # Nombre amigable para la descarga
    ext          = producto.archivo_key.rsplit(".", 1)[-1] if "." in producto.archivo_key else "zip"
    nombre_clean = producto.nombre.replace(" ", "_").replace("/", "-")[:60]
    filename     = f"{nombre_clean}.{ext}"

    return FileResponse(
        path=archivo_path,
        filename=filename,
        media_type="application/octet-stream",
    )


# ── Revocar descarga (vendedor — por disputa, etc.) ───────────────────────────
@router.delete("/{pedido_id}/revocar")
async def revocar_descarga(
    pedido_id: int,
    vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == vendedor.dni
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")

    pedido.descarga_habilitada = False
    pedido.descarga_token      = None
    pedido.estado              = "confirmado"   # regresa a confirmado
    db.commit()
    return {"ok": True, "mensaje": "Descarga revocada"}