# backend/notifications/push_service.py
#
# Notificaciones push al navegador usando el estándar Web Push (RFC 8030).
# Requiere: pip install pywebpush   ← AGRÉGALO también a requirements.txt,
#                                     si no, en producción falla en silencio.
#
# Variables de entorno (.env del BACKEND en producción):
#   VAPID_PRIVATE_KEY=<base64url, 43 caracteres>
#   VAPID_PUBLIC_KEY=<base64url, 87 caracteres>   (debe ser el par de la privada)
#   VAPID_CLAIMS_EMAIL=mailto:admin@tudominio.com
#
# Generar un par de claves VÁLIDO (opción simple): https://vapidkeys.com
# o con la CLI de py_vapid:  vapid --gen   → crea private_key.pem / public_key.pem

import os
import json
import asyncio
from typing import Optional

VAPID_PRIVATE_KEY    = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY     = os.getenv("VAPID_PUBLIC_KEY",  "")
VAPID_CLAIMS_EMAIL   = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:admin@mercadofenix.com")


def _problema_de_configuracion() -> Optional[str]:
    """Devuelve un texto explicando qué falta, o None si todo está bien."""
    if not VAPID_PRIVATE_KEY or not VAPID_PUBLIC_KEY:
        return "VAPID_PRIVATE_KEY y/o VAPID_PUBLIC_KEY no están configuradas en el entorno del backend"
    try:
        import pywebpush  # noqa: F401
    except ImportError:
        return "La librería pywebpush NO está instalada en el servidor (pip install pywebpush y agrégala a requirements.txt)"
    return None


def _push_sync(subscription_info: dict, titulo: str, cuerpo: str, url: str = "/") -> dict:
    """
    Envía una notificación push a UNA suscripción del navegador.
    Devuelve {"ok": bool, "error": str|None, "status": int|None, "expirada": bool}.
    `expirada=True` significa que el navegador ya no acepta esa suscripción
    (404/410) y hay que desactivarla.
    """
    problema = _problema_de_configuracion()
    if problema:
        print(f"[PUSH] ✗ {problema}")
        return {"ok": False, "error": problema, "status": None, "expirada": False}

    from pywebpush import webpush, WebPushException

    payload = json.dumps({
        "titulo": titulo,
        "cuerpo": cuerpo,
        "url":    url,
        "icono":  "/icons/icon-192x192.png",
        "badge":  "/icons/badge-72x72.png",
    })

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_CLAIMS_EMAIL},   # dict nuevo por llamada: pywebpush lo modifica
            ttl=86400,
        )
        print(f"[PUSH] ✓ Enviado | {titulo}")
        return {"ok": True, "error": None, "status": 201, "expirada": False}

    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"[PUSH] ✗ El servicio push rechazó el envío (HTTP {status}): {e}")
        return {"ok": False, "error": str(e), "status": status, "expirada": status in (404, 410)}

    except Exception as e:
        print(f"[PUSH] ✗ Error inesperado: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "status": None, "expirada": False}


async def enviar_push(subscription_info: dict, titulo: str, cuerpo: str, url: str = "/") -> dict:
    """Wrapper async para no bloquear el event loop."""
    return await asyncio.to_thread(_push_sync, subscription_info, titulo, cuerpo, url)


async def enviar_push_a_usuario(
    db,
    usuario_tipo: str,   # "vendedor" | "cliente"
    usuario_id:   str,   # dni del vendedor ó id del cliente (str)
    titulo: str,
    cuerpo: str,
    url:    str = "/",
) -> dict:
    """
    Envía la notificación a TODOS los dispositivos activos del usuario y
    desactiva automáticamente las suscripciones que el navegador ya no
    acepta (404/410). Devuelve un resumen {suscripciones, enviados, fallidos}.
    """
    from sqlalchemy import text

    resumen = {"suscripciones": 0, "enviados": 0, "fallidos": 0}

    try:
        rows = db.execute(
            text("""
                SELECT id, subscription_json FROM push_subscriptions
                WHERE usuario_tipo = :tipo AND usuario_id = :uid AND activo = true
            """),
            {"tipo": usuario_tipo, "uid": str(usuario_id)}
        ).fetchall()
    except Exception as e:
        db.rollback()
        print(f"[PUSH] ✗ Error consultando suscripciones (¿existe la tabla push_subscriptions?): {e}")
        return resumen

    resumen["suscripciones"] = len(rows)
    if not rows:
        print(f"[PUSH] El usuario {usuario_tipo}:{usuario_id} no tiene suscripciones push activas")
        return resumen

    for row in rows:
        try:
            sub_info = json.loads(row[1])
        except Exception as e:
            print(f"[PUSH] Suscripción {row[0]} con JSON inválido: {e}")
            resumen["fallidos"] += 1
            continue

        r = await enviar_push(sub_info, titulo, cuerpo, url)
        if r["ok"]:
            resumen["enviados"] += 1
        else:
            resumen["fallidos"] += 1
            if r["expirada"]:
                try:
                    db.execute(text("UPDATE push_subscriptions SET activo=false WHERE id=:id"), {"id": row[0]})
                    db.commit()
                    print(f"[PUSH] Suscripción {row[0]} expirada → desactivada")
                except Exception:
                    db.rollback()

    return resumen


async def diagnosticar_y_enviar_prueba(db, usuario_tipo: str, usuario_id: str) -> dict:
    """
    Para el endpoint /probar-push: revisa la configuración, cuenta las
    suscripciones del usuario y manda una notificación de prueba real.
    Devuelve un JSON legible que dice EXACTAMENTE qué está fallando.
    """
    from sqlalchemy import text

    diag = {
        "vapid_configurado": bool(VAPID_PRIVATE_KEY and VAPID_PUBLIC_KEY),
        "problema_configuracion": _problema_de_configuracion(),
        "suscripciones_activas": 0,
        "suscripciones_totales": 0,
        "envio": None,
        "veredicto": "",
    }

    try:
        diag["suscripciones_activas"] = db.execute(
            text("SELECT COUNT(*) FROM push_subscriptions WHERE usuario_tipo=:t AND usuario_id=:u AND activo=true"),
            {"t": usuario_tipo, "u": str(usuario_id)}
        ).scalar() or 0
        diag["suscripciones_totales"] = db.execute(
            text("SELECT COUNT(*) FROM push_subscriptions WHERE usuario_tipo=:t AND usuario_id=:u"),
            {"t": usuario_tipo, "u": str(usuario_id)}
        ).scalar() or 0
    except Exception as e:
        db.rollback()
        diag["veredicto"] = f"No se pudo leer la tabla push_subscriptions (¿falta crearla?): {e}"
        return diag

    if diag["problema_configuracion"]:
        diag["veredicto"] = diag["problema_configuracion"]
        return diag

    if diag["suscripciones_activas"] == 0:
        diag["veredicto"] = (
            "El backend NO tiene ninguna suscripción push guardada para este usuario. "
            "El navegador no llegó a registrarla (revisa la consola del sitio) o el guardado falló."
        )
        return diag

    diag["envio"] = await enviar_push_a_usuario(
        db, usuario_tipo, usuario_id,
        "🔔 Notificación de prueba", "Si ves esto, el push funciona correctamente.", "/",
    )
    if diag["envio"]["enviados"] > 0:
        diag["veredicto"] = (
            "Push enviado al servicio del navegador. Si aun así no ves la notificación, "
            "el problema está en el dispositivo: revisa 'No molestar'/'Asistente de concentración', "
            "permisos de notificaciones del sistema para el navegador, y que el navegador esté abierto."
        )
    else:
        diag["veredicto"] = (
            "Había suscripciones pero el servicio push rechazó todos los envíos. "
            "Revisa los logs del backend ([PUSH] ✗ ...) — la causa típica es un par VAPID "
            "que no coincide o suscripciones creadas con otra clave pública."
        )
    return diag