# backend/routes/notificaciones.py
#
# Registro de suscripciones push, historial de notificaciones, marcado como
# leído, y las funciones que disparan una notificación (in-app + push +
# email) para cada evento de negocio: nuevo pedido, cambio de estado, nuevo
# mensaje de chat, nuevo producto según preferencias, promociones y
# sugerencias periódicas.
#
# Prefix="/api/notificaciones" — agregar en main.py:
#   from routes.notificaciones import router as notif_router
#   app.include_router(notif_router)
#
# Migraciones SQL necesarias — ejecutar una sola vez:
# ─────────────────────────────────────────────────
#   CREATE TABLE IF NOT EXISTS push_subscriptions (
#       id              SERIAL PRIMARY KEY,
#       usuario_tipo    VARCHAR(20) NOT NULL,   -- 'cliente' | 'vendedor'
#       usuario_id      VARCHAR(50) NOT NULL,   -- cliente.id ó vendedor.dni
#       subscription_json TEXT NOT NULL,
#       dispositivo     VARCHAR(100),           -- "Chrome/Windows", "Safari/iOS", etc.
#       activo          BOOLEAN DEFAULT true,
#       creado_en       TIMESTAMPTZ DEFAULT NOW()
#   );
#   CREATE INDEX ON push_subscriptions(usuario_tipo, usuario_id);
#
#   CREATE TABLE IF NOT EXISTS notificaciones (
#       id              SERIAL PRIMARY KEY,
#       usuario_tipo    VARCHAR(20) NOT NULL,
#       usuario_id      VARCHAR(50) NOT NULL,
#       titulo          VARCHAR(200) NOT NULL,
#       cuerpo          TEXT NOT NULL,
#       url             VARCHAR(500) DEFAULT '/',
#       leida           BOOLEAN DEFAULT false,
#       tipo            VARCHAR(50) DEFAULT 'info',
#       referencia_id   INTEGER,
#       creado_en       TIMESTAMPTZ DEFAULT NOW()
#   );
#   CREATE INDEX ON notificaciones(usuario_tipo, usuario_id, leida);
#   CREATE INDEX ON notificaciones(usuario_tipo, usuario_id, tipo, creado_en);
#
#   -- Preferencia de correo promocional (opt-out). Si la columna no existe
#   -- todavía, el código asume "true" por defecto — no rompe nada mientras
#   -- corres esta migración:
#   ALTER TABLE clientes ADD COLUMN IF NOT EXISTS recibir_promociones BOOLEAN DEFAULT true;
# ─────────────────────────────────────────────────

import os
import json
import hmac
import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, func
from pydantic import BaseModel
from typing import Optional, List

from core.database import get_db
from core.auth import get_current_user, get_current_vendedor
from core.security import SECRET_KEY
from models.cliente import Cliente

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
CRON_SECRET      = os.getenv("CRON_SECRET", "")
API_PUBLIC_URL   = os.getenv("API_PUBLIC_URL", "http://localhost:8000")  # URL pública del backend, para el link de unsubscribe


# ── Schemas ───────────────────────────────────────────────────────────────────
class SuscripcionBody(BaseModel):
    subscription: dict       # { endpoint, keys: { p256dh, auth } }
    dispositivo: Optional[str] = None


class PromocionBody(BaseModel):
    titulo: str
    mensaje: str
    producto_id: Optional[str] = None


# ── VAPID public key (el frontend la necesita para suscribirse) ───────────────
@router.get("/vapid-public-key")
def get_vapid_key():
    if not VAPID_PUBLIC_KEY:
        raise HTTPException(500, "Clave VAPID no configurada en el servidor")
    return {"public_key": VAPID_PUBLIC_KEY}


# ── Registrar suscripción push (cliente) ──────────────────────────────────────
@router.post("/suscribir/cliente")
async def suscribir_cliente(
    body: SuscripcionBody,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _guardar_suscripcion(db, "cliente", str(current_user.id), body.subscription, body.dispositivo)
    return {"ok": True}


# ── Registrar suscripción push (vendedor) ─────────────────────────────────────
@router.post("/suscribir/vendedor")
async def suscribir_vendedor(
    body: SuscripcionBody,
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db),
):
    _guardar_suscripcion(db, "vendedor", current_vendedor.dni, body.subscription, body.dispositivo)
    return {"ok": True}


# ── Historial de notificaciones del cliente ───────────────────────────────────
@router.get("/mis-notificaciones")
def mis_notificaciones(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_notificaciones(db, "cliente", str(current_user.id))


# ── Historial de notificaciones del vendedor ──────────────────────────────────
@router.get("/vendedor/mis-notificaciones")
def mis_notificaciones_vendedor(
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db),
):
    return _get_notificaciones(db, "vendedor", current_vendedor.dni)


# ── Marcar todas como leídas (cliente) ───────────────────────────────────────
@router.post("/marcar-leidas")
def marcar_leidas_cliente(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _marcar_leidas(db, "cliente", str(current_user.id))
    return {"ok": True}


# ── Marcar todas como leídas (vendedor) ──────────────────────────────────────
@router.post("/vendedor/marcar-leidas")
def marcar_leidas_vendedor(
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db),
):
    _marcar_leidas(db, "vendedor", current_vendedor.dni)
    return {"ok": True}


# ── Marcar una notificación como leída ───────────────────────────────────────
@router.patch("/{notif_id}/leida")
def marcar_una_leida(
    notif_id: int,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        db.execute(
            text("UPDATE notificaciones SET leida=true WHERE id=:id AND usuario_tipo='cliente' AND usuario_id=:uid"),
            {"id": notif_id, "uid": str(current_user.id)}
        )
        db.commit()
    except Exception:
        db.rollback()
    return {"ok": True}


# ── Vendedor dispara una promoción a sus clientes anteriores ─────────────────
@router.post("/vendedor/promocion")
async def enviar_promocion(
    body: PromocionBody,
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db),
):
    """
    Envía una promoción (in-app + push + email) a los clientes que ya le
    compraron antes a este vendedor. Limitado a 1 envío cada 24h por
    vendedor para no saturar a los clientes ni gastar la cuota de Mailjet.
    """
    try:
        reciente = db.execute(text("""
            SELECT 1 FROM notificaciones
            WHERE usuario_tipo='vendedor' AND usuario_id=:dni AND tipo='promocion_enviada'
              AND creado_en > NOW() - INTERVAL '24 hours'
            LIMIT 1
        """), {"dni": current_vendedor.dni}).first()
    except Exception:
        reciente = None
    if reciente:
        raise HTTPException(429, "Ya enviaste una promoción en las últimas 24 horas. Intenta más tarde.")

    clientes_ids = _clientes_previos_de_tienda(db, current_vendedor.dni)
    if not clientes_ids:
        raise HTTPException(400, "Aún no tienes clientes previos a quienes enviarles una promoción")

    from notifications.email_service import html_promocion_cliente

    enviados = 0
    for cid in clientes_ids[:300]:   # límite de seguridad por envío
        cliente = db.query(Cliente).filter(Cliente.id == int(cid)).first()
        if not cliente:
            continue
        try:
            email_to = cliente.email if _acepta_promociones(db, cid) else None
            html = None
            if email_to:
                html = html_promocion_cliente(
                    cliente_nombre=cliente.nombres, titulo=body.titulo, mensaje=body.mensaje,
                    nombre_tienda=current_vendedor.nombre_tienda, producto_id=body.producto_id,
                    unsubscribe_url=_url_unsubscribe(cid),
                )
            url = f"/fenix/producto/{body.producto_id}" if body.producto_id else "/fenix/productos"
            await crear_y_enviar_notificacion(
                db, "cliente", cid,
                titulo=body.titulo, cuerpo=body.mensaje, url=url, tipo="promocion",
                email_to=email_to, email_asunto=f"🔥 {body.titulo} — {current_vendedor.nombre_tienda}",
                email_html=html, email_list_unsubscribe=_url_unsubscribe(cid) if email_to else None,
            )
            enviados += 1
        except Exception as e:
            print(f"[PROMOCION] Error notificando a cliente {cid}: {e}")

    try:
        db.execute(text("""
            INSERT INTO notificaciones (usuario_tipo, usuario_id, titulo, cuerpo, tipo)
            VALUES ('vendedor', :dni, :t, :c, 'promocion_enviada')
        """), {"dni": current_vendedor.dni, "t": f"Promoción enviada: {body.titulo}",
               "c": f"Se envió a {enviados} clientes"})
        db.commit()
    except Exception:
        db.rollback()

    return {"enviados": enviados}


# ── Disparar manualmente el job de sugerencias (para cron externo) ───────────
@router.post("/admin/generar-sugerencias")
async def trigger_generar_sugerencias(request: Request, db: Session = Depends(get_db)):
    if not CRON_SECRET or request.headers.get("X-Cron-Secret") != CRON_SECRET:
        raise HTTPException(403, "No autorizado")
    enviados = await generar_sugerencias_preferencias(db)
    return {"ok": True, "sugerencias_enviadas": enviados}


# ── Darse de baja de correos promocionales (link público, sin login) ─────────
@router.get("/unsubscribe/{cliente_id}", response_class=HTMLResponse)
def unsubscribe_promociones(cliente_id: int, token: str, db: Session = Depends(get_db)):
    """
    Enlace de un clic desde el correo (y vía el header List-Unsubscribe).
    No requiere sesión iniciada — se valida con un token firmado (HMAC) en
    vez de pedir login, porque el usuario puede estar dándose de baja desde
    cualquier dispositivo/cliente de correo.
    """
    if not hmac.compare_digest(token, _token_unsubscribe(cliente_id)):
        raise HTTPException(403, "Enlace inválido o vencido")

    try:
        db.execute(text("UPDATE clientes SET recibir_promociones = false WHERE id = :id"), {"id": cliente_id})
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[UNSUBSCRIBE] Error actualizando preferencia: {e}")
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding:60px 20px;'>"
            "<h2>No pudimos procesar tu solicitud</h2>"
            "<p>Intenta de nuevo más tarde o contáctanos.</p></body></html>",
            status_code=500,
        )

    return HTMLResponse("""
        <html><body style="font-family:sans-serif;text-align:center;padding:60px 20px;color:#111827;">
          <h2>Listo, te diste de baja ✅</h2>
          <p style="color:#6b7280;">Ya no recibirás promociones ni sugerencias de productos por correo.</p>
          <p style="color:#6b7280;">Seguirás recibiendo avisos de tus pedidos activos.</p>
        </body></html>
    """)


# ── Helpers internos: token de unsubscribe y preferencia del cliente ─────────
def _token_unsubscribe(cliente_id: int) -> str:
    return hmac.new(SECRET_KEY.encode(), str(cliente_id).encode(), hashlib.sha256).hexdigest()[:32]


def _url_unsubscribe(cliente_id) -> str:
    cid = int(cliente_id)
    return f"{API_PUBLIC_URL}/api/notificaciones/unsubscribe/{cid}?token={_token_unsubscribe(cid)}"


def _acepta_promociones(db: Session, cliente_id) -> bool:
    """True por defecto — incluso si la columna aún no existe (migración
    pendiente), nunca bloquea el envío por error."""
    try:
        row = db.execute(
            text("SELECT recibir_promociones FROM clientes WHERE id=:id"), {"id": int(cliente_id)}
        ).first()
        if row is None or row[0] is None:
            return True
        return bool(row[0])
    except Exception:
        return True


# ── Helpers internos: suscripciones y lectura de notificaciones ──────────────
def _guardar_suscripcion(db: Session, tipo: str, uid: str, sub: dict, dispositivo: Optional[str]):
    endpoint = sub.get("endpoint", "")
    sub_json = json.dumps(sub)
    try:
        existing = db.execute(
            text("SELECT id FROM push_subscriptions WHERE endpoint_hash=md5(:ep) AND usuario_id=:uid AND usuario_tipo=:tipo"),
            {"ep": endpoint, "uid": uid, "tipo": tipo}
        ).first()
    except Exception:
        existing = None

    try:
        if existing:
            db.execute(
                text("""
                    UPDATE push_subscriptions
                    SET subscription_json=:sub, activo=true, dispositivo=:dev
                    WHERE id=:id
                """),
                {"sub": sub_json, "dev": dispositivo, "id": existing[0]}
            )
        else:
            db.execute(
                text("""
                    INSERT INTO push_subscriptions
                        (usuario_tipo, usuario_id, subscription_json, dispositivo, activo)
                    VALUES (:tipo, :uid, :sub, :dev, true)
                """),
                {"tipo": tipo, "uid": uid, "sub": sub_json, "dev": dispositivo}
            )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[PUSH] Error guardando suscripción: {e}")


def _get_notificaciones(db: Session, tipo: str, uid: str) -> dict:
    try:
        rows = db.execute(
            text("""
                SELECT id, titulo, cuerpo, url, leida, tipo, referencia_id, creado_en
                FROM notificaciones
                WHERE usuario_tipo=:tipo AND usuario_id=:uid AND tipo NOT IN ('promocion_enviada','promocion_producto_enviada')
                ORDER BY creado_en DESC
                LIMIT 50
            """),
            {"tipo": tipo, "uid": uid}
        ).fetchall()

        no_leidas = db.execute(
            text("""
                SELECT COUNT(*) FROM notificaciones
                WHERE usuario_tipo=:tipo AND usuario_id=:uid AND leida=false
                  AND tipo NOT IN ('promocion_enviada','promocion_producto_enviada')
            """),
            {"tipo": tipo, "uid": uid}
        ).scalar() or 0

        notifs = [
            {
                "id":           r[0],
                "titulo":       r[1],
                "cuerpo":       r[2],
                "url":          r[3],
                "leida":        r[4],
                "tipo":         r[5],
                "referencia_id":r[6],
                "creado_en":    r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
        return {"notificaciones": notifs, "no_leidas": no_leidas}
    except Exception as e:
        print(f"[NOTIF] Error obteniendo notificaciones: {e}")
        return {"notificaciones": [], "no_leidas": 0}


def _marcar_leidas(db: Session, tipo: str, uid: str):
    try:
        db.execute(
            text("UPDATE notificaciones SET leida=true WHERE usuario_tipo=:tipo AND usuario_id=:uid AND leida=false"),
            {"tipo": tipo, "uid": uid}
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[NOTIF] Error marcando leídas: {e}")


# ── Función pública de bajo nivel: crear notificación en DB + push + email ───
async def crear_y_enviar_notificacion(
    db:           Session,
    usuario_tipo: str,
    usuario_id:   str,
    titulo:       str,
    cuerpo:       str,
    url:          str       = "/",
    tipo:         str       = "info",
    referencia_id: Optional[int] = None,
    email_to:     Optional[str]  = None,
    email_asunto: Optional[str]  = None,
    email_html:   Optional[str]  = None,
    email_list_unsubscribe: Optional[str] = None,
):
    """
    Crea la notificación en BD, envía push al navegador y correo (si se
    proveen). Cada paso está aislado: un push o email fallido nunca tumba
    un flujo de negocio como crear un pedido o cambiar su estado.
    `email_list_unsubscribe`: pásalo SOLO en correos promocionales/masivos
    (promoción, sugerencia, nuevo producto) — ayuda mucho contra el filtro
    de spam de Gmail/Yahoo. No es necesario en correos transaccionales
    (nuevo pedido, cambio de estado).
    """
    try:
        db.execute(
            text("""
                INSERT INTO notificaciones
                    (usuario_tipo, usuario_id, titulo, cuerpo, url, tipo, referencia_id)
                VALUES (:tipo_u, :uid, :titulo, :cuerpo, :url, :tipo, :ref_id)
            """),
            {
                "tipo_u": usuario_tipo, "uid": str(usuario_id),
                "titulo": titulo, "cuerpo": cuerpo, "url": url,
                "tipo": tipo, "ref_id": referencia_id,
            }
        )
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[NOTIF] Error guardando en BD: {e}")

    try:
        from notifications.push_service import enviar_push_a_usuario
        await enviar_push_a_usuario(db, usuario_tipo, usuario_id, titulo, cuerpo, url)
    except Exception as e:
        print(f"[NOTIF] Error enviando push: {e}")

    if email_to and email_asunto and email_html:
        try:
            from notifications.email_service import enviar_email
            await enviar_email(email_to, email_asunto, email_html, list_unsubscribe=email_list_unsubscribe)
        except Exception as e:
            print(f"[NOTIF] Error enviando email: {e}")


# ══════════════════════════════════════════════════════════════════════════
# HELPERS DE ALTO NIVEL POR EVENTO DE NEGOCIO
# ══════════════════════════════════════════════════════════════════════════

def _email_vendedor(db: Session, dni: str) -> Optional[str]:
    try:
        row = db.execute(text("SELECT email FROM vendedores WHERE dni=:d"), {"d": dni}).first()
        return row[0] if row and row[0] else None
    except Exception:
        return None


async def notificar_nuevo_pedido_vendedor(db: Session, pedido, vendedor, cliente):
    """Transaccional — sin unsubscribe."""
    from notifications.email_service import html_nuevo_pedido_vendedor

    items_resumen = ", ".join(f"{it.nombre_producto} x{it.cantidad}" for it in pedido.items) or "—"
    email_vendedor = _email_vendedor(db, vendedor.dni)
    html = None
    if email_vendedor:
        html = html_nuevo_pedido_vendedor(
            nombre_tienda=vendedor.nombre_tienda, pedido_id=pedido.id,
            cliente_nombre=f"{cliente.nombres} {cliente.apellidos}", cliente_tel=cliente.telefono,
            total=float(pedido.total), items_resumen=items_resumen,
            tipo_entrega=pedido.tipo_entrega, metodo_pago=pedido.metodo_pago,
        )

    await crear_y_enviar_notificacion(
        db, "vendedor", vendedor.dni,
        titulo=f"Nuevo pedido #{pedido.id}",
        cuerpo=f"{cliente.nombres} hizo un pedido por L{float(pedido.total):.2f}",
        url="/vendedor/dashboard/pedidos", tipo="pedido", referencia_id=pedido.id,
        email_to=email_vendedor,
        email_asunto=f"🛍️ Nuevo pedido #{pedido.id} — Mercado Fénix" if email_vendedor else None,
        email_html=html,
    )


async def notificar_cambio_estado_cliente(db: Session, pedido, cliente, nombre_tienda: str):
    """Transaccional — sin unsubscribe."""
    from notifications.email_service import html_estado_pedido_cliente, ESTADO_LABEL

    html = None
    if cliente.email:
        html = html_estado_pedido_cliente(
            cliente_nombre=cliente.nombres, pedido_id=pedido.id, nuevo_estado=pedido.estado,
            nombre_tienda=nombre_tienda, total=float(pedido.total), nota_vendedor=pedido.nota_vendedor,
        )

    label = ESTADO_LABEL.get(pedido.estado, pedido.estado.replace("_", " ").title())
    await crear_y_enviar_notificacion(
        db, "cliente", str(cliente.id),
        titulo=f"Pedido #{pedido.id}: {label}",
        cuerpo=f"Tu pedido en {nombre_tienda} cambió a: {pedido.estado.replace('_',' ')}",
        url="/fenix/mi-cuenta/mis-pedidos", tipo="estado", referencia_id=pedido.id,
        email_to=cliente.email,
        email_asunto=f"Pedido #{pedido.id} actualizado — Mercado Fénix" if cliente.email else None,
        email_html=html,
    )


async def notificar_nuevo_mensaje_chat(db: Session, sala, remitente_tipo: str, contenido: str):
    """Sin email: el chat ya es tiempo real por WS, mandar correo por mensaje sería spam."""
    preview = (contenido[:80] + "…") if len(contenido) > 80 else contenido
    if remitente_tipo == "cliente":
        await crear_y_enviar_notificacion(
            db, "vendedor", sala.vendedor_id,
            titulo="Nuevo mensaje de cliente",
            cuerpo=preview, url="/vendedor/dashboard/pedidos",
            tipo="chat", referencia_id=sala.pedido_id,
        )
    else:
        await crear_y_enviar_notificacion(
            db, "cliente", str(sala.cliente_id),
            titulo="Respuesta de la tienda",
            cuerpo=preview, url="/fenix/mi-cuenta/mis-pedidos",
            tipo="chat", referencia_id=sala.pedido_id,
        )


def _clientes_interesados_en_categoria(db: Session, categoria: str, limite: int = 200) -> List[str]:
    from models.pedido import Pedido, PedidoItem
    from models.producto import Producto as ProductoModel

    filas = (
        db.query(Pedido.cliente_id)
        .join(PedidoItem, PedidoItem.pedido_id == Pedido.id)
        .join(ProductoModel, ProductoModel.id == PedidoItem.producto_id)
        .filter(ProductoModel.categoria == categoria, Pedido.cliente_id.isnot(None))
        .distinct()
        .limit(limite)
        .all()
    )
    return [str(row[0]) for row in filas]


def _clientes_previos_de_tienda(db: Session, vendedor_dni: str, limite: int = 500) -> List[str]:
    from models.pedido import Pedido

    filas = (
        db.query(Pedido.cliente_id)
        .filter(Pedido.vendedor_id == vendedor_dni, Pedido.cliente_id.isnot(None))
        .distinct()
        .limit(limite)
        .all()
    )
    return [str(row[0]) for row in filas]


async def notificar_nuevo_producto_interesados(db: Session, producto, vendedor, max_clientes: int = 100) -> int:
    """PROMOCIONAL — respeta recibir_promociones y lleva List-Unsubscribe."""
    from notifications.email_service import html_nuevo_producto_cliente

    clientes_ids = _clientes_interesados_en_categoria(db, producto.categoria)
    if not clientes_ids:
        return 0

    foto_url = producto.fotos[0].url if getattr(producto, "fotos", None) else None
    enviados = 0
    for cid in clientes_ids[:max_clientes]:
        cliente = db.query(Cliente).filter(Cliente.id == int(cid)).first()
        if not cliente:
            continue
        try:
            email_to = cliente.email if _acepta_promociones(db, cid) else None
            html = None
            if email_to:
                html = html_nuevo_producto_cliente(
                    cliente_nombre=cliente.nombres, nombre_producto=producto.nombre,
                    nombre_tienda=vendedor.nombre_tienda, precio=float(producto.precio),
                    categoria=producto.categoria, producto_id=str(producto.id), foto_url=foto_url,
                    unsubscribe_url=_url_unsubscribe(cid),
                )
            await crear_y_enviar_notificacion(
                db, "cliente", cid,
                titulo="Nuevo producto que podría interesarte",
                cuerpo=f"{producto.nombre} en {vendedor.nombre_tienda} — L{float(producto.precio):.2f}",
                url=f"/fenix/producto/{producto.id}", tipo="info",
                email_to=email_to,
                email_asunto=f"✨ Nuevo en {producto.categoria}: {producto.nombre}" if email_to else None,
                email_html=html,
                email_list_unsubscribe=_url_unsubscribe(cid) if email_to else None,
            )
            enviados += 1
        except Exception as e:
            print(f"[NUEVO_PRODUCTO] Error notificando a cliente {cid}: {e}")
    return enviados


async def notificar_promocion_producto(
    db: Session, producto, vendedor, nuevo_descuento: float, max_clientes: int = 150
) -> int:
    """PROMOCIONAL — respeta recibir_promociones y lleva List-Unsubscribe.
    Rate-limit de 24h por producto (no por vendedor), guardado como fila
    marcador en la propia tabla notificaciones."""
    try:
        reciente = db.execute(text("""
            SELECT 1 FROM notificaciones
            WHERE usuario_tipo='vendedor' AND usuario_id=:dni
              AND tipo='promocion_producto_enviada' AND cuerpo=:pid
              AND creado_en > NOW() - INTERVAL '24 hours'
            LIMIT 1
        """), {"dni": vendedor.dni, "pid": str(producto.id)}).first()
    except Exception:
        reciente = None
    if reciente:
        return 0

    from notifications.email_service import html_promocion_cliente

    clientes_ids = _clientes_interesados_en_categoria(db, producto.categoria)
    if not clientes_ids:
        return 0

    precio_final = float(producto.precio) * (1 - nuevo_descuento / 100)
    titulo  = f"¡{int(nuevo_descuento)}% de descuento en {producto.nombre}!"
    mensaje = f"Ahora L{precio_final:,.2f} (antes L{float(producto.precio):,.2f}) en {vendedor.nombre_tienda}."

    enviados = 0
    for cid in clientes_ids[:max_clientes]:
        cliente = db.query(Cliente).filter(Cliente.id == int(cid)).first()
        if not cliente:
            continue
        try:
            email_to = cliente.email if _acepta_promociones(db, cid) else None
            html = None
            if email_to:
                html = html_promocion_cliente(
                    cliente_nombre=cliente.nombres, titulo=titulo, mensaje=mensaje,
                    nombre_tienda=vendedor.nombre_tienda, producto_id=str(producto.id),
                    unsubscribe_url=_url_unsubscribe(cid),
                )
            await crear_y_enviar_notificacion(
                db, "cliente", cid,
                titulo=titulo, cuerpo=mensaje, url=f"/fenix/producto/{producto.id}",
                tipo="promocion",
                email_to=email_to,
                email_asunto=f"🔥 {titulo}" if email_to else None,
                email_html=html,
                email_list_unsubscribe=_url_unsubscribe(cid) if email_to else None,
            )
            enviados += 1
        except Exception as e:
            print(f"[PROMOCION_PRODUCTO] Error notificando a cliente {cid}: {e}")

    try:
        db.execute(text("""
            INSERT INTO notificaciones (usuario_tipo, usuario_id, titulo, cuerpo, tipo)
            VALUES ('vendedor', :dni, :t, :pid, 'promocion_producto_enviada')
        """), {"dni": vendedor.dni, "t": f"Promoción automática: {producto.nombre}", "pid": str(producto.id)})
        db.commit()
    except Exception:
        db.rollback()

    return enviados


async def generar_sugerencias_preferencias(db: Session, dias_desde_ultima: int = 7, max_clientes: int = 500) -> int:
    """PROMOCIONAL — respeta recibir_promociones y lleva List-Unsubscribe."""
    from models.pedido import Pedido, PedidoItem
    from models.producto import Producto as ProductoModel
    from notifications.email_service import html_sugerencia_cliente

    clientes_ids = (
        db.query(Pedido.cliente_id)
        .filter(Pedido.cliente_id.isnot(None))
        .distinct()
        .limit(max_clientes)
        .all()
    )

    enviados = 0
    for (cid,) in clientes_ids:
        cid = str(cid)

        try:
            reciente = db.execute(text(f"""
                SELECT 1 FROM notificaciones
                WHERE usuario_tipo='cliente' AND usuario_id=:cid AND tipo='sugerencia'
                  AND creado_en > NOW() - INTERVAL '{int(dias_desde_ultima)} days'
                LIMIT 1
            """), {"cid": cid}).first()
        except Exception:
            reciente = None
        if reciente:
            continue

        cat_row = (
            db.query(ProductoModel.categoria, func.count(ProductoModel.categoria).label("c"))
            .join(PedidoItem, PedidoItem.producto_id == ProductoModel.id)
            .join(Pedido, Pedido.id == PedidoItem.pedido_id)
            .filter(Pedido.cliente_id == int(cid))
            .group_by(ProductoModel.categoria)
            .order_by(func.count(ProductoModel.categoria).desc())
            .first()
        )
        if not cat_row:
            continue
        categoria = cat_row[0]

        ya_comprados = {
            row[0] for row in
            db.query(PedidoItem.producto_id)
            .join(Pedido, Pedido.id == PedidoItem.pedido_id)
            .filter(Pedido.cliente_id == int(cid))
            .all()
        }

        candidatos = (
            db.query(ProductoModel)
            .filter(ProductoModel.categoria == categoria, ProductoModel.activo == True)
            .order_by(ProductoModel.creado_en.desc())
            .limit(20)
            .all()
        )
        sugeridos = [p for p in candidatos if p.id not in ya_comprados][:3]
        if not sugeridos:
            continue

        cliente = db.query(Cliente).filter(Cliente.id == int(cid)).first()
        if not cliente:
            continue

        nombres_productos = ", ".join(p.nombre for p in sugeridos)
        email_to = cliente.email if _acepta_promociones(db, cid) else None
        html = None
        if email_to:
            html = html_sugerencia_cliente(
                cliente_nombre=cliente.nombres, categoria=categoria,
                productos=[{"nombre": p.nombre, "precio": float(p.precio)} for p in sugeridos],
                unsubscribe_url=_url_unsubscribe(cid),
            )
        await crear_y_enviar_notificacion(
            db, "cliente", cid,
            titulo=f"Productos de {categoria} para ti",
            cuerpo=f"Basado en tus compras: {nombres_productos}",
            url=f"/fenix/productos?categoria={categoria}", tipo="sugerencia",
            email_to=email_to,
            email_asunto="💡 Sugerencias para ti — Mercado Fénix" if email_to else None,
            email_html=html,
            email_list_unsubscribe=_url_unsubscribe(cid) if email_to else None,
        )
        enviados += 1

    print(f"[SUGERENCIAS] Generadas para {enviados} clientes")
    return enviados