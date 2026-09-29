# backend/routes/chat.py
import json
import os
import shutil
from datetime import datetime
from typing import Dict, List, Set

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload

from core.database import get_db, SessionLocal
from core.auth import get_current_user, get_current_vendedor
from models.chat import ChatSala, ChatMensaje
from models.pedido import Pedido
from models.cliente import Cliente
from models.vendedor import Vendedor
from jose import jwt, JWTError
from core.security import SECRET_KEY, ALGORITHM

router = APIRouter(prefix="/api/chat", tags=["chat"])

UPLOAD_COMPROBANTES = "public/uploads/comprobantes"
os.makedirs(UPLOAD_COMPROBANTES, exist_ok=True)


# ─── GESTOR DE CONEXIONES WEBSOCKET ──────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        # sala_id → set de WebSockets activos
        self.active: Dict[int, Set[WebSocket]] = {}

    async def connect(self, sala_id: int, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(sala_id, set()).add(ws)

    def disconnect(self, sala_id: int, ws: WebSocket):
        if sala_id in self.active:
            self.active[sala_id].discard(ws)

    async def broadcast(self, sala_id: int, data: dict):
        """Enviar mensaje a todos los conectados en la sala."""
        muertos = set()
        for ws in self.active.get(sala_id, set()):
            try:
                await ws.send_json(data)
            except Exception:
                muertos.add(ws)
        for ws in muertos:
            self.active[sala_id].discard(ws)


manager = ConnectionManager()


# ─── HELPER: autenticar desde token en WS ────────────────────────────────────
def autenticar_ws(token: str, db: Session):
    """Retorna (tipo, id) donde tipo es 'cliente' o 'vendedor'."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        role = payload.get("role")
        if not sub:
            return None, None

        if role == "vendedor":
            v = db.query(Vendedor).filter(Vendedor.dni == sub).first()
            return ("vendedor", v.dni) if v else (None, None)
        else:
            # cliente — sub es teléfono
            c = db.query(Cliente).filter(Cliente.telefono == sub).first()
            return ("cliente", str(c.id)) if c else (None, None)
    except JWTError:
        return None, None


# ─── CREAR O RECUPERAR SALA ───────────────────────────────────────────────────
@router.post("/sala/{pedido_id}")
async def obtener_o_crear_sala(
    pedido_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """El cliente abre el chat de un pedido → crea la sala si no existe."""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.cliente_id == current_user.id
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    # Si el pedido no tiene vendedor aún, intentar inferirlo del primer item
    if not pedido.vendedor_id:
        from models.pedido import PedidoItem
        from models.producto import Producto
        primer_item = db.query(PedidoItem).filter(PedidoItem.pedido_id == pedido_id).first()
        if primer_item:
            prod = db.query(Producto).filter(Producto.id == primer_item.producto_id).first()
            if prod:
                pedido.vendedor_id = prod.vendedor_id
                db.commit()
        if not pedido.vendedor_id:
            raise HTTPException(400, "Este pedido aún no tiene vendedor asignado")

    sala = db.query(ChatSala).filter(ChatSala.pedido_id == pedido_id).first()
    if not sala:
        sala = ChatSala(
            pedido_id=pedido_id,
            cliente_id=current_user.id,
            vendedor_id=pedido.vendedor_id,
        )
        db.add(sala)
        db.commit()
        db.refresh(sala)

    return {"sala_id": sala.id, "pedido_id": pedido_id}


@router.post("/sala/vendedor/{pedido_id}")
async def obtener_sala_vendedor(
    pedido_id: int,
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """El vendedor abre el chat de un pedido."""
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == current_vendedor.dni
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")

    sala = db.query(ChatSala).filter(ChatSala.pedido_id == pedido_id).first()
    if not sala:
        sala = ChatSala(
            pedido_id=pedido_id,
            cliente_id=pedido.cliente_id,
            vendedor_id=current_vendedor.dni,
        )
        db.add(sala)
        db.commit()
        db.refresh(sala)

    return {"sala_id": sala.id, "pedido_id": pedido_id}


# ─── HISTORIAL DE MENSAJES ────────────────────────────────────────────────────
@router.get("/sala/{sala_id}/mensajes")
async def get_mensajes(
    sala_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sala = db.query(ChatSala).filter(
        ChatSala.id == sala_id,
        ChatSala.cliente_id == current_user.id
    ).first()
    if not sala:
        raise HTTPException(404, "Sala no encontrada")

    # Marcar mensajes del vendedor como leídos
    db.query(ChatMensaje).filter(
        ChatMensaje.sala_id == sala_id,
        ChatMensaje.remitente_tipo == "vendedor",
        ChatMensaje.leido_cliente == False
    ).update({"leido_cliente": True})
    db.commit()

    mensajes = db.query(ChatMensaje).filter(
        ChatMensaje.sala_id == sala_id
    ).order_by(ChatMensaje.enviado_en).all()

    return {"mensajes": [_msg_to_dict(m) for m in mensajes]}


@router.get("/sala/vendedor/{sala_id}/mensajes")
async def get_mensajes_vendedor(
    sala_id: int,
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    sala = db.query(ChatSala).filter(
        ChatSala.id == sala_id,
        ChatSala.vendedor_id == current_vendedor.dni
    ).first()
    if not sala:
        raise HTTPException(404, "Sala no encontrada")

    db.query(ChatMensaje).filter(
        ChatMensaje.sala_id == sala_id,
        ChatMensaje.remitente_tipo == "cliente",
        ChatMensaje.leido_vendedor == False
    ).update({"leido_vendedor": True})
    db.commit()

    mensajes = db.query(ChatMensaje).filter(
        ChatMensaje.sala_id == sala_id
    ).order_by(ChatMensaje.enviado_en).all()

    return {"mensajes": [_msg_to_dict(m) for m in mensajes]}


# ─── ENVIAR MENSAJE POR HTTP (fallback cuando el WS no está listo) ────────────
@router.post("/sala/vendedor/{sala_id}/mensaje")
async def enviar_mensaje_vendedor(
    sala_id: int,
    body: dict,
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """
    Permite al vendedor enviar un mensaje por REST cuando el WebSocket
    aún no está en estado OPEN (p.ej. al autorizar descarga recién abierto el chat).
    """
    sala = db.query(ChatSala).filter(
        ChatSala.id == sala_id,
        ChatSala.vendedor_id == current_vendedor.dni
    ).first()
    if not sala:
        raise HTTPException(404, "Sala no encontrada")

    contenido = (body.get("contenido") or "").strip()
    if not contenido:
        raise HTTPException(400, "El mensaje no puede estar vacío")

    msg = ChatMensaje(
        sala_id=sala_id,
        remitente_tipo="vendedor",
        remitente_id=current_vendedor.dni,
        contenido=contenido,
        leido_vendedor=True,
        leido_cliente=False,
    )
    db.add(msg)
    sala.ultimo_mensaje_en = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    # Notificar por WS a quien esté conectado en la sala
    await manager.broadcast(sala_id, {
        "tipo": "mensaje",
        **_msg_to_dict(msg)
    })

    return {"mensaje": _msg_to_dict(msg)}
@router.post("/sala/{sala_id}/comprobante")
async def subir_comprobante(
    sala_id: int,
    archivo: UploadFile = File(...),
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """El cliente sube su comprobante de pago como mensaje especial."""
    sala = db.query(ChatSala).filter(
        ChatSala.id == sala_id,
        ChatSala.cliente_id == current_user.id
    ).first()
    if not sala:
        raise HTTPException(404, "Sala no encontrada")

    ext = archivo.filename.rsplit(".", 1)[-1].lower()
    if ext not in ["jpg", "jpeg", "png", "pdf", "webp"]:
        raise HTTPException(400, "Solo se permiten imágenes o PDF")

    filename = f"comprobante_{sala_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    path = os.path.join(UPLOAD_COMPROBANTES, filename)
    with open(path, "wb") as f:
        shutil.copyfileobj(archivo.file, f)

    archivo_url = f"/uploads/comprobantes/{filename}"

    msg = ChatMensaje(
        sala_id=sala_id,
        remitente_tipo="cliente",
        remitente_id=str(current_user.id),
        contenido="📎 Comprobante de pago enviado",
        es_comprobante=True,
        archivo_url=archivo_url,
        leido_vendedor=False,
        leido_cliente=True,
    )
    db.add(msg)
    sala.ultimo_mensaje_en = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    # Notificar via WS a todos en la sala
    await manager.broadcast(sala_id, {
        "tipo": "mensaje",
        **_msg_to_dict(msg)
    })

    return {"archivo_url": archivo_url, "mensaje_id": msg.id}


# ─── LISTA DE SALAS DEL VENDEDOR ─────────────────────────────────────────────
@router.get("/vendedor/salas")
async def salas_vendedor(
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """Lista de todas las conversaciones del vendedor, ordenadas por actividad."""
    salas = db.query(ChatSala).options(
        joinedload(ChatSala.cliente),
        joinedload(ChatSala.pedido),
    ).filter(
        ChatSala.vendedor_id == current_vendedor.dni
    ).order_by(ChatSala.ultimo_mensaje_en.desc().nullslast()).all()

    # Excluir pedidos archivados por el vendedor (usando text() para columna nueva)
    from sqlalchemy import text as sql_text
    try:
        archivados_rows = db.execute(sql_text(
            "SELECT id FROM pedidos WHERE vendedor_id = :dni AND archivado_vendedor = true"
        ), {"dni": current_vendedor.dni}).fetchall()
        archivados = {r[0] for r in archivados_rows}
    except Exception:
        archivados = set()  # si la migración no se corrió aún, no filtrar
    salas = [s for s in salas if s.pedido_id not in archivados]

    result = []
    for sala in salas:
        no_leidos = db.query(ChatMensaje).filter(
            ChatMensaje.sala_id == sala.id,
            ChatMensaje.remitente_tipo == "cliente",
            ChatMensaje.leido_vendedor == False
        ).count()

        ultimo = db.query(ChatMensaje).filter(
            ChatMensaje.sala_id == sala.id
        ).order_by(ChatMensaje.enviado_en.desc()).first()

        result.append({
            "sala_id": sala.id,
            "pedido_id": sala.pedido_id,
            "cliente_id": sala.cliente_id,
            "cliente_nombre": f"{sala.cliente.nombres} {sala.cliente.apellidos}",
            "cliente_telefono": sala.cliente.telefono,
            "pedido_estado": sala.pedido.estado if sala.pedido else "desconocido",
            "pedido_total": float(sala.pedido.total) if sala.pedido else 0,
            "es_digital": getattr(sala.pedido, "es_digital", False) if sala.pedido else False,
            "no_leidos": no_leidos,
            "ultimo_mensaje": ultimo.contenido if ultimo else None,
            "ultimo_mensaje_en": ultimo.enviado_en.isoformat() if ultimo else None,
        })

    return {"salas": result}



# ─── ARCHIVAR PEDIDO (ocultar del historial del vendedor) ────────────────────
@router.delete("/vendedor/pedidos/{pedido_id}")
async def archivar_pedido_vendedor(
    pedido_id: int,
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """
    Archiva un pedido del historial del vendedor.
    Solo aplica a pedidos entregados o cancelados.
    El pedido NO se elimina de la BD — solo se oculta para el vendedor.
    """
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == current_vendedor.dni
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    if pedido.estado not in ("entregado", "cancelado"):
        raise HTTPException(400, "Solo se pueden archivar pedidos entregados o cancelados")

    from sqlalchemy import text
    try:
        db.execute(
            text("UPDATE pedidos SET archivado_vendedor = true WHERE id = :id AND vendedor_id = :dni"),
            {"id": pedido_id, "dni": current_vendedor.dni}
        )
        db.commit()
    except Exception:
        # Si la columna no existe aún (migración pendiente), hacer soft-delete local
        db.rollback()
        raise HTTPException(500, "Ejecuta la migración fix_archivado_vendedor.sql primero")

    return {"msg": "Pedido archivado del historial"}


# ─── WEBSOCKET ────────────────────────────────────────────────────────────────
@router.websocket("/ws/{sala_id}")
async def websocket_chat(websocket: WebSocket, sala_id: int, token: str):
    """
    Conexión WebSocket para chat en tiempo real.
    URL: ws://localhost:8000/api/chat/ws/{sala_id}?token=<jwt>
    """
    db = SessionLocal()
    try:
        tipo, remitente_id = autenticar_ws(token, db)
        if not tipo:
            await websocket.close(code=4001)
            return

        # Verificar que pertenece a esta sala
        if tipo == "cliente":
            sala = db.query(ChatSala).filter(
                ChatSala.id == sala_id,
                ChatSala.cliente_id == int(remitente_id)
            ).first()
        else:
            sala = db.query(ChatSala).filter(
                ChatSala.id == sala_id,
                ChatSala.vendedor_id == remitente_id
            ).first()

        if not sala:
            await websocket.close(code=4003)
            return

        await manager.connect(sala_id, websocket)

        try:
            while True:
                data = await websocket.receive_json()

                if data.get("tipo") == "mensaje":
                    contenido = data.get("contenido", "").strip()
                    if not contenido:
                        continue

                    msg = ChatMensaje(
                        sala_id=sala_id,
                        remitente_tipo=tipo,
                        remitente_id=remitente_id,
                        contenido=contenido,
                        leido_cliente=(tipo == "cliente"),
                        leido_vendedor=(tipo == "vendedor"),
                    )
                    db.add(msg)
                    sala.ultimo_mensaje_en = datetime.utcnow()
                    db.commit()
                    db.refresh(msg)

                    # Broadcast a toda la sala
                    await manager.broadcast(sala_id, {
                        "tipo": "mensaje",
                        **_msg_to_dict(msg)
                    })

                elif data.get("tipo") == "typing":
                    # Notificar que el otro está escribiendo
                    await manager.broadcast(sala_id, {
                        "tipo": "typing",
                        "remitente_tipo": tipo,
                    })

        except WebSocketDisconnect:
            manager.disconnect(sala_id, websocket)

    finally:
        db.close()


# ─── HELPER ───────────────────────────────────────────────────────────────────
def _msg_to_dict(m: ChatMensaje) -> dict:
    return {
        "id": m.id,
        "sala_id": m.sala_id,
        "remitente_tipo": m.remitente_tipo,
        "remitente_id": m.remitente_id,
        "contenido": m.contenido,
        "es_comprobante": m.es_comprobante,
        "archivo_url": m.archivo_url,
        "leido_cliente": m.leido_cliente,
        "leido_vendedor": m.leido_vendedor,
        "enviado_en": m.enviado_en.isoformat() if m.enviado_en else None,
    }