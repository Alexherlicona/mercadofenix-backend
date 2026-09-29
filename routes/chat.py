# backend/routes/chat.py
import json
import os
import shutil
import asyncio
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

# ── Notificaciones ─────────────────────────────────────────────────────────────
from routes.notificaciones import crear_y_enviar_notificacion

router = APIRouter(prefix="/api/chat", tags=["chat"])

UPLOAD_COMPROBANTES = "public/uploads/comprobantes"
os.makedirs(UPLOAD_COMPROBANTES, exist_ok=True)


# ─── GESTOR DE CONEXIONES WEBSOCKET ───────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, Set[WebSocket]] = {}

    async def connect(self, sala_id: int, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(sala_id, set()).add(ws)

    def disconnect(self, sala_id: int, ws: WebSocket):
        if sala_id in self.active:
            self.active[sala_id].discard(ws)

    async def broadcast(self, sala_id: int, data: dict):
        muertos = set()
        for ws in self.active.get(sala_id, set()):
            try:
                await ws.send_json(data)
            except Exception:
                muertos.add(ws)
        for ws in muertos:
            self.active[sala_id].discard(ws)

    def hay_conectados(self, sala_id: int) -> bool:
        """True si hay alguien conectado por WS en esta sala."""
        return bool(self.active.get(sala_id))


manager = ConnectionManager()


# ─── HELPER: autenticar desde token en WS ────────────────────────────────────
def autenticar_ws(token: str, db: Session):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub  = payload.get("sub")
        role = payload.get("role")
        if not sub:
            return None, None
        if role == "vendedor":
            v = db.query(Vendedor).filter(Vendedor.dni == sub).first()
            return ("vendedor", v.dni) if v else (None, None)
        else:
            c = db.query(Cliente).filter(Cliente.telefono == sub).first()
            return ("cliente", str(c.id)) if c else (None, None)
    except JWTError:
        return None, None


# ─── HELPER: enviar notificación de chat ─────────────────────────────────────
async def _notificar_mensaje(
    db: Session,
    sala: ChatSala,
    remitente_tipo: str,
    contenido: str,
):
    """
    Notifica al OTRO participante de la sala (no al que envía).
    Solo envía notificación si el destinatario NO está conectado por WS,
    para no duplicar alertas cuando ambos tienen el chat abierto.
    """
    try:
        preview = contenido[:80] + ("..." if len(contenido) > 80 else "")

        if remitente_tipo == "cliente":
            # Notificar al vendedor
            vendedor = db.query(Vendedor).filter(Vendedor.dni == sala.vendedor_id).first()
            if vendedor:
                await crear_y_enviar_notificacion(
                    db           = db,
                    usuario_tipo = "vendedor",
                    usuario_id   = sala.vendedor_id,
                    titulo       = "💬 Nuevo mensaje de un cliente",
                    cuerpo       = preview,
                    url          = "/vendedor/dashboard/pedidos",
                    tipo         = "chat",
                    referencia_id= sala.pedido_id,
                    # Sin email para mensajes de chat — evita spam
                )
        else:
            # Notificar al cliente
            cliente = db.query(Cliente).filter(Cliente.id == sala.cliente_id).first()
            vendedor = db.query(Vendedor).filter(Vendedor.dni == sala.vendedor_id).first()
            nombre_tienda = vendedor.nombre_tienda if vendedor else "La tienda"
            if cliente:
                await crear_y_enviar_notificacion(
                    db           = db,
                    usuario_tipo = "cliente",
                    usuario_id   = str(sala.cliente_id),
                    titulo       = f"💬 {nombre_tienda} te respondió",
                    cuerpo       = preview,
                    url          = "/fenix/mi-cuenta/mis-pedidos",
                    tipo         = "chat",
                    referencia_id= sala.pedido_id,
                )
    except Exception as e:
        print(f"[NOTIF CHAT] Error: {e}")


# ─── CREAR O RECUPERAR SALA ────────────────────────────────────────────────────
@router.post("/sala/{pedido_id}")
async def obtener_o_crear_sala(
    pedido_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.cliente_id == current_user.id
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")

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
            pedido_id  = pedido_id,
            cliente_id = current_user.id,
            vendedor_id= pedido.vendedor_id,
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
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == current_vendedor.dni
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")

    sala = db.query(ChatSala).filter(ChatSala.pedido_id == pedido_id).first()
    if not sala:
        sala = ChatSala(
            pedido_id  = pedido_id,
            cliente_id = pedido.cliente_id,
            vendedor_id= current_vendedor.dni,
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


# ─── ENVIAR MENSAJE HTTP (fallback REST) ──────────────────────────────────────
@router.post("/sala/vendedor/{sala_id}/mensaje")
async def enviar_mensaje_vendedor(
    sala_id: int,
    body: dict,
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
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
        sala_id        = sala_id,
        remitente_tipo = "vendedor",
        remitente_id   = current_vendedor.dni,
        contenido      = contenido,
        leido_vendedor = True,
        leido_cliente  = False,
    )
    db.add(msg)
    sala.ultimo_mensaje_en = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    await manager.broadcast(sala_id, {"tipo": "mensaje", **_msg_to_dict(msg)})

    # Notificar al cliente si no está en el chat
    asyncio.create_task(_notificar_mensaje(db, sala, "vendedor", contenido))

    return {"mensaje": _msg_to_dict(msg)}


# ─── SUBIR COMPROBANTE ────────────────────────────────────────────────────────
@router.post("/sala/{sala_id}/comprobante")
async def subir_comprobante(
    sala_id: int,
    archivo: UploadFile = File(...),
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sala = db.query(ChatSala).filter(
        ChatSala.id == sala_id,
        ChatSala.cliente_id == current_user.id
    ).first()
    if not sala:
        raise HTTPException(404, "Sala no encontrada")

    ext = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else "jpg"
    if ext not in ["jpg", "jpeg", "png", "webp", "pdf"]:
        raise HTTPException(400, "Formato no permitido")

    filename  = f"{sala_id}_{int(datetime.utcnow().timestamp())}.{ext}"
    filepath  = os.path.join(UPLOAD_COMPROBANTES, filename)
    contenido = await archivo.read()
    with open(filepath, "wb") as f:
        f.write(contenido)

    url = f"/uploads/comprobantes/{filename}"

    msg = ChatMensaje(
        sala_id        = sala_id,
        remitente_tipo = "cliente",
        remitente_id   = str(current_user.id),
        contenido      = "📎 Comprobante de pago",
        es_comprobante = True,
        archivo_url    = url,
        leido_cliente  = True,
        leido_vendedor = False,
    )
    db.add(msg)
    sala.ultimo_mensaje_en = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    await manager.broadcast(sala_id, {"tipo": "mensaje", **_msg_to_dict(msg)})

    # Notificar al vendedor
    asyncio.create_task(_notificar_mensaje(db, sala, "cliente", "📎 Comprobante de pago"))

    return {"mensaje": _msg_to_dict(msg), "url": url}


# ─── SALAS DEL VENDEDOR ───────────────────────────────────────────────────────
@router.get("/vendedor/salas")
async def salas_vendedor(
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    salas = db.query(ChatSala).filter(
        ChatSala.vendedor_id == current_vendedor.dni
    ).order_by(ChatSala.ultimo_mensaje_en.desc().nullslast()).all()

    resultado = []
    for sala in salas:
        pedido  = db.query(Pedido).filter(Pedido.id == sala.pedido_id).first()
        cliente = db.query(Cliente).filter(Cliente.id == sala.cliente_id).first()
        no_leidos = db.query(ChatMensaje).filter(
            ChatMensaje.sala_id == sala.id,
            ChatMensaje.remitente_tipo == "cliente",
            ChatMensaje.leido_vendedor == False
        ).count()

        resultado.append({
            "sala_id":        sala.id,
            "pedido_id":      sala.pedido_id,
            "estado_pedido":  pedido.estado if pedido else "—",
            "total_pedido":   float(pedido.total) if pedido else 0,
            "cliente_nombre": f"{cliente.nombres} {cliente.apellidos}" if cliente else "Cliente",
            "cliente_tel":    cliente.telefono if cliente else "",
            "no_leidos":      no_leidos,
            "ultimo_mensaje": sala.ultimo_mensaje_en.isoformat() if sala.ultimo_mensaje_en else None,
        })
    return {"salas": resultado}


@router.delete("/vendedor/pedidos/{pedido_id}")
async def archivar_pedido_vendedor(
    pedido_id: int,
    current_vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == current_vendedor.dni
    ).first()
    if not pedido:
        raise HTTPException(404, "Pedido no encontrado")
    pedido.activo = False
    db.commit()
    return {"mensaje": "Pedido archivado"}


# ─── WEBSOCKET ────────────────────────────────────────────────────────────────
@router.websocket("/ws/{sala_id}")
async def websocket_chat(websocket: WebSocket, sala_id: int, token: str):
    db = SessionLocal()
    try:
        tipo, remitente_id = autenticar_ws(token, db)
        if not tipo:
            await websocket.close(code=4001)
            return

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
                        sala_id        = sala_id,
                        remitente_tipo = tipo,
                        remitente_id   = remitente_id,
                        contenido      = contenido,
                        leido_cliente  = (tipo == "cliente"),
                        leido_vendedor = (tipo == "vendedor"),
                    )
                    db.add(msg)
                    sala.ultimo_mensaje_en = datetime.utcnow()
                    db.commit()
                    db.refresh(msg)

                    # Broadcast por WS
                    await manager.broadcast(sala_id, {
                        "tipo": "mensaje",
                        **_msg_to_dict(msg)
                    })

                    # Push + BD — solo si el otro no está conectado por WS
                    asyncio.create_task(
                        _notificar_mensaje(db, sala, tipo, contenido)
                    )

                elif data.get("tipo") == "typing":
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
        "id":              m.id,
        "sala_id":         m.sala_id,
        "remitente_tipo":  m.remitente_tipo,
        "remitente_id":    m.remitente_id,
        "contenido":       m.contenido,
        "es_comprobante":  m.es_comprobante,
        "archivo_url":     m.archivo_url,
        "leido_cliente":   m.leido_cliente,
        "leido_vendedor":  m.leido_vendedor,
        "enviado_en":      m.enviado_en.isoformat() if m.enviado_en else None,
    }