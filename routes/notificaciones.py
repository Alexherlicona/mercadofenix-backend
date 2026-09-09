# backend/routes/notificaciones.py
#
# Registro de suscripciones push, historial de notificaciones y marcado como leído.
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
#       tipo            VARCHAR(50) DEFAULT 'info',   -- 'pedido'|'estado'|'chat'|'info'
#       referencia_id   INTEGER,                      -- pedido_id relacionado
#       creado_en       TIMESTAMPTZ DEFAULT NOW()
#   );
#   CREATE INDEX ON notificaciones(usuario_tipo, usuario_id, leida);
# ─────────────────────────────────────────────────

import os
import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional

from core.database import get_db
from core.auth import get_current_user, get_current_vendedor

router = APIRouter(prefix="/api/notificaciones", tags=["notificaciones"])

VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")


# ── Schemas ───────────────────────────────────────────────────────────────────
class SuscripcionBody(BaseModel):
    subscription: dict       # { endpoint, keys: { p256dh, auth } }
    dispositivo: Optional[str] = None


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


# ── Helpers internos ──────────────────────────────────────────────────────────
def _guardar_suscripcion(db: Session, tipo: str, uid: str, sub: dict, dispositivo: Optional[str]):
    """
    Guarda o actualiza la suscripción push.
    Un mismo endpoint se actualiza en lugar de duplicarse.
    """
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
                WHERE usuario_tipo=:tipo AND usuario_id=:uid
                ORDER BY creado_en DESC
                LIMIT 50
            """),
            {"tipo": tipo, "uid": uid}
        ).fetchall()

        no_leidas = db.execute(
            text("SELECT COUNT(*) FROM notificaciones WHERE usuario_tipo=:tipo AND usuario_id=:uid AND leida=false"),
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


# ── Función pública: crear notificación en DB y enviar push + email ───────────
async def crear_y_enviar_notificacion(
    db:           Session,
    usuario_tipo: str,            # "cliente" | "vendedor"
    usuario_id:   str,
    titulo:       str,
    cuerpo:       str,
    url:          str       = "/",
    tipo:         str       = "info",
    referencia_id: Optional[int] = None,
    email_to:     Optional[str]  = None,
    email_asunto: Optional[str]  = None,
    email_html:   Optional[str]  = None,
):
    """
    Crea la notificación en BD, envía push al navegador y correo (si se proveen).
    Llama esta función desde pedidos.py en los puntos de trigger.
    """
    # 1. Guardar en BD
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

    # 2. Push al navegador
    from notifications.push_service import enviar_push_a_usuario
    await enviar_push_a_usuario(db, usuario_tipo, usuario_id, titulo, cuerpo, url)

    # 3. Correo electrónico (opcional)
    if email_to and email_asunto and email_html:
        from notifications.email_service import enviar_email
        await enviar_email(email_to, email_asunto, email_html)