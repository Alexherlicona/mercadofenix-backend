# backend/notifications/push_service.py
#
# Notificaciones push al navegador usando el estándar Web Push (RFC 8030).
# Requiere: pip install pywebpush
#
# Generar claves VAPID una sola vez:
#   python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys(); print('PRIV:', v.private_key); print('PUB:', v.public_key)"
# O usar: https://vapidkeys.com
#
# Variables de entorno (.env):
#   VAPID_PRIVATE_KEY=<base64url>
#   VAPID_PUBLIC_KEY=<base64url>
#   VAPID_CLAIMS_EMAIL=mailto:admin@mercadofenix.com

import os
import json
import asyncio
from typing import Optional

VAPID_PRIVATE_KEY    = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY     = os.getenv("VAPID_PUBLIC_KEY",  "")
VAPID_CLAIMS_EMAIL   = os.getenv("VAPID_CLAIMS_EMAIL","mailto:admin@mercadofenix.com")


def _push_sync(subscription_info: dict, titulo: str, cuerpo: str, url: str = "/"):
    """
    Envía una notificación push a una suscripción del navegador.
    subscription_info tiene la forma que devuelve el navegador:
    { endpoint, keys: { p256dh, auth } }
    """
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        print(f"[PUSH] Claves VAPID no configuradas. Notif: {titulo}")
        return

    try:
        from pywebpush import webpush, WebPushException

        payload = json.dumps({
            "titulo": titulo,
            "cuerpo": cuerpo,
            "url":    url,
            "icono":  "/icons/icon-192x192.png",
            "badge":  "/icons/badge-72x72.png",
        })

        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={
                "sub": VAPID_CLAIMS_EMAIL,
            },
        )
        print(f"[PUSH] ✓ Enviado | {titulo}")

    except Exception as e:
        print(f"[PUSH] ✗ Error: {e}")


async def enviar_push(subscription_info: dict, titulo: str, cuerpo: str, url: str = "/"):
    """Wrapper async para no bloquear el event loop."""
    await asyncio.to_thread(_push_sync, subscription_info, titulo, cuerpo, url)


async def enviar_push_a_usuario(
    db,
    usuario_tipo: str,   # "vendedor" | "cliente"
    usuario_id:   str,   # dni del vendedor ó id del cliente (str)
    titulo: str,
    cuerpo: str,
    url:    str = "/",
):
    """
    Busca todas las suscripciones push activas del usuario y envía la notificación.
    Envía a todos los dispositivos registrados (móvil + escritorio).
    """
    from sqlalchemy import text

    try:
        rows = db.execute(
            text("""
                SELECT subscription_json FROM push_subscriptions
                WHERE usuario_tipo = :tipo AND usuario_id = :uid AND activo = true
            """),
            {"tipo": usuario_tipo, "uid": str(usuario_id)}
        ).fetchall()
    except Exception as e:
        print(f"[PUSH] Error consultando suscripciones: {e}")
        return

    for row in rows:
        try:
            sub_info = json.loads(row[0])
            await enviar_push(sub_info, titulo, cuerpo, url)
        except Exception as e:
            print(f"[PUSH] Suscripción inválida: {e}")