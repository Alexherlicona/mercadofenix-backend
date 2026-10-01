# backend/notifications/email_service.py
#
# Envío de correos transaccionales usando la API REST de Mailjet (v3.1).
# Se eligió la API sobre SMTP porque: (1) da códigos de error claros por
# mensaje, (2) permite reintentar solo lo que falló, (3) mejor entregabilidad
# y estadísticas desde el panel de Mailjet.
#
# Variables de entorno requeridas en .env:
#   MAILJET_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#   MAILJET_API_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
#   MAILJET_FROM_EMAIL=notificaciones@tudominio.com   ← debe estar verificado en Mailjet
#   EMAIL_FROM_NAME=Mercado Fénix
#   FRONTEND_URL=https://mercadofenix.com
#
# Cómo conseguir las llaves: https://app.mailjet.com/account/apikeys
# El plan gratuito de Mailjet da 200 emails/día y no requiere tarjeta.
#
# IMPORTANTE: MAILJET_FROM_EMAIL debe ser un remitente verificado en tu
# cuenta de Mailjet (Account Settings → Sender addresses) o los envíos
# fallarán con 401/403.

import os
import time
import requests
from typing import Optional, List, Dict
import asyncio
from datetime import datetime

MAILJET_API_KEY    = os.getenv("MAILJET_API_KEY", "")
MAILJET_API_SECRET = os.getenv("MAILJET_API_SECRET", "")
MAILJET_FROM_EMAIL  = os.getenv("MAILJET_FROM_EMAIL", "notificaciones@mercadofenix.com")
FROM_NAME      = os.getenv("EMAIL_FROM_NAME", "Mercado Fénix")
FRONTEND_URL   = os.getenv("FRONTEND_URL",    "http://localhost:3000")

MAILJET_SEND_URL      = "https://api.mailjet.com/v3.1/send"
MAX_REINTENTOS        = 3   # ante error transitorio (red, 429, 5xx)
BACKOFF_BASE_SEGUNDOS = 2   # 2s, 4s, 6s...


# ── Paleta de colores por estado ─────────────────────────────────────────────
ESTADO_COLOR = {
    "pendiente":      ("#f59e0b", "⏳"),
    "confirmado":     ("#3b82f6", "✅"),
    "en_preparacion": ("#8b5cf6", "📦"),
    "en_camino":      ("#06b6d4", "🚚"),
    "entregado":      ("#10b981", "🎉"),
    "cancelado":      ("#ef4444", "❌"),
}

ESTADO_LABEL = {
    "pendiente":      "Pendiente de confirmación",
    "confirmado":     "Confirmado por la tienda",
    "en_preparacion": "En preparación",
    "en_camino":      "En camino",
    "entregado":      "Entregado",
    "cancelado":      "Cancelado",
}

ESTADO_DESC = {
    "confirmado":     "Tu pedido fue revisado y aceptado por la tienda. Pronto comenzarán a prepararlo.",
    "en_preparacion": "La tienda está preparando tu pedido con cuidado.",
    "en_camino":      "Tu pedido está en camino. Mantente atento a tu dirección de entrega.",
    "entregado":      "¡Tu pedido fue entregado! Esperamos que estés satisfecho con tu compra.",
    "cancelado":      "Tu pedido fue cancelado. Si tienes dudas, contacta a la tienda.",
}


# ── Base HTML del email ───────────────────────────────────────────────────────
def _base_html(titulo: str, cuerpo: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titulo}</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 16px;">
    <tr><td align="center">
      <table width="100%" style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#ea580c,#dc2626);padding:28px 32px;text-align:center;">
            <span style="display:inline-block;background:rgba(255,255,255,0.15);border-radius:12px;padding:8px 20px;">
              <span style="color:#ffffff;font-size:20px;font-weight:900;letter-spacing:1px;">🔥 Mercado Fénix</span>
            </span>
          </td>
        </tr>

        <!-- Cuerpo -->
        <tr>
          <td style="padding:32px;">
            {cuerpo}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f9fafb;border-top:1px solid #e5e7eb;padding:20px 32px;text-align:center;">
            <p style="margin:0;color:#9ca3af;font-size:12px;">
              © {datetime.now().year} Mercado Fénix · Honduras<br>
              <a href="{FRONTEND_URL}" style="color:#f97316;text-decoration:none;">mercadofenix.com</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _btn(texto: str, url: str, color: str = "#ea580c") -> str:
    return f"""
    <div style="text-align:center;margin:24px 0 8px;">
      <a href="{url}" style="display:inline-block;background:{color};color:#ffffff;
         font-weight:700;font-size:14px;padding:14px 32px;border-radius:12px;
         text-decoration:none;letter-spacing:0.3px;">{texto}</a>
    </div>"""


def _item_fila(label: str, valor: str) -> str:
    return f"""
    <tr>
      <td style="padding:8px 0;color:#6b7280;font-size:13px;">{label}</td>
      <td style="padding:8px 0;color:#111827;font-size:13px;font-weight:600;text-align:right;">{valor}</td>
    </tr>"""


# ── Template: Nuevo pedido → Vendedor ────────────────────────────────────────
def html_nuevo_pedido_vendedor(
    nombre_tienda:  str,
    pedido_id:      int,
    cliente_nombre: str,
    cliente_tel:    str,
    total:          float,
    items_resumen:  str,   # "Camiseta x2, Pantalón x1"
    tipo_entrega:   str,
    metodo_pago:    str,
) -> str:
    cuerpo = f"""
    <h2 style="margin:0 0 4px;color:#111827;font-size:22px;font-weight:900;">¡Nuevo pedido recibido! 🛍️</h2>
    <p style="margin:0 0 24px;color:#6b7280;font-size:14px;">Tienda: <strong>{nombre_tienda}</strong></p>

    <div style="background:#fff7ed;border:1.5px solid #fed7aa;border-radius:12px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0;color:#ea580c;font-size:13px;font-weight:700;">PEDIDO #{pedido_id}</p>
      <p style="margin:4px 0 0;color:#9a3412;font-size:28px;font-weight:900;">L{total:,.2f}</p>
    </div>

    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {_item_fila("Cliente",       cliente_nombre)}
      {_item_fila("Teléfono",      cliente_tel)}
      {_item_fila("Productos",     items_resumen)}
      {_item_fila("Entrega",       tipo_entrega.replace("_"," ").title())}
      {_item_fila("Pago",          metodo_pago.replace("_"," ").title())}
    </table>

    <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0;">
    <p style="color:#374151;font-size:13px;line-height:1.6;">
      Confirma el pedido lo antes posible para brindarle una buena experiencia a tu cliente.
    </p>

    {_btn("Ver pedido en mi panel", f"{FRONTEND_URL}/vendedor/dashboard/pedidos")}
    """
    return _base_html(f"Nuevo pedido #{pedido_id} — Mercado Fénix", cuerpo)


# ── Template: Cambio de estado → Cliente ─────────────────────────────────────
def html_estado_pedido_cliente(
    cliente_nombre: str,
    pedido_id:      int,
    nuevo_estado:   str,
    nombre_tienda:  str,
    total:          float,
    nota_vendedor:  Optional[str] = None,
) -> str:
    color, emoji = ESTADO_COLOR.get(nuevo_estado, ("#6b7280", "📋"))
    label  = ESTADO_LABEL.get(nuevo_estado, nuevo_estado.replace("_", " ").title())
    desc   = ESTADO_DESC.get(nuevo_estado, "")

    nota_bloque = ""
    if nota_vendedor:
        nota_bloque = f"""
        <div style="background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:14px 16px;margin:16px 0;">
          <p style="margin:0 0 4px;color:#1e40af;font-size:12px;font-weight:700;">MENSAJE DE LA TIENDA</p>
          <p style="margin:0;color:#1d4ed8;font-size:13px;">{nota_vendedor}</p>
        </div>"""

    cuerpo = f"""
    <h2 style="margin:0 0 4px;color:#111827;font-size:22px;font-weight:900;">
      {emoji} Actualización de tu pedido
    </h2>
    <p style="margin:0 0 24px;color:#6b7280;font-size:14px;">Hola, <strong>{cliente_nombre}</strong></p>

    <div style="background:{color}18;border:2px solid {color}40;border-radius:12px;padding:16px 20px;margin-bottom:20px;text-align:center;">
      <p style="margin:0;color:{color};font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
        Pedido #{pedido_id} · {nombre_tienda}
      </p>
      <p style="margin:8px 0 0;color:{color};font-size:22px;font-weight:900;">{label}</p>
    </div>

    <p style="color:#374151;font-size:14px;line-height:1.65;margin:0 0 16px;">{desc}</p>

    {nota_bloque}

    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
      {_item_fila("Total del pedido", f"L{total:,.2f}")}
    </table>

    {_btn("Ver mis pedidos", f"{FRONTEND_URL}/fenix/mi-cuenta/mis-pedidos", color)}
    """
    return _base_html(f"Pedido #{pedido_id}: {label} — Mercado Fénix", cuerpo)


# ── Template: Nuevo producto (según preferencias) → Cliente ──────────────────
def html_nuevo_producto_cliente(
    cliente_nombre:  str,
    nombre_producto: str,
    nombre_tienda:   str,
    precio:          float,
    categoria:       str,
    producto_id:     str,
    foto_url:        Optional[str] = None,
) -> str:
    imagen_bloque = (
        f'<img src="{foto_url}" alt="{nombre_producto}" '
        f'style="width:100%;max-width:280px;border-radius:12px;margin:0 auto 16px;display:block;">'
        if foto_url else ""
    )
    cuerpo = f"""
    <h2 style="margin:0 0 4px;color:#111827;font-size:22px;font-weight:900;">✨ Algo nuevo para ti</h2>
    <p style="margin:0 0 20px;color:#6b7280;font-size:14px;">
      Hola, <strong>{cliente_nombre}</strong> — vimos que te interesa <strong>{categoria}</strong>
    </p>
    {imagen_bloque}
    <div style="background:#fff7ed;border:1.5px solid #fed7aa;border-radius:12px;padding:16px 20px;margin-bottom:8px;text-align:center;">
      <p style="margin:0;color:#111827;font-size:16px;font-weight:800;">{nombre_producto}</p>
      <p style="margin:6px 0 0;color:#ea580c;font-size:22px;font-weight:900;">L{precio:,.2f}</p>
      <p style="margin:4px 0 0;color:#9ca3af;font-size:12px;">{nombre_tienda}</p>
    </div>
    {_btn("Ver producto", f"{FRONTEND_URL}/fenix/producto/{producto_id}")}
    <p style="margin:20px 0 0;color:#9ca3af;font-size:11px;text-align:center;">
      Te avisamos porque has comprado productos similares antes en Mercado Fénix.
    </p>
    """
    return _base_html(f"Nuevo en {categoria}: {nombre_producto}", cuerpo)


# ── Template: Promoción de una tienda → Cliente ───────────────────────────────
def html_promocion_cliente(
    cliente_nombre: str,
    titulo:         str,
    mensaje:        str,
    nombre_tienda:  str,
    producto_id:    Optional[str] = None,
) -> str:
    boton = (
        _btn("Ver oferta", f"{FRONTEND_URL}/fenix/producto/{producto_id}")
        if producto_id else
        _btn("Ver tienda", f"{FRONTEND_URL}/fenix/productos")
    )
    cuerpo = f"""
    <h2 style="margin:0 0 4px;color:#111827;font-size:22px;font-weight:900;">🔥 {titulo}</h2>
    <p style="margin:0 0 20px;color:#6b7280;font-size:14px;">
      Hola, <strong>{cliente_nombre}</strong> — de parte de <strong>{nombre_tienda}</strong>
    </p>
    <p style="color:#374151;font-size:14px;line-height:1.65;">{mensaje}</p>
    {boton}
    <p style="margin:20px 0 0;color:#9ca3af;font-size:11px;text-align:center;">
      Recibes esto porque compraste antes en {nombre_tienda} a través de Mercado Fénix.
    </p>
    """
    return _base_html(f"{titulo} — {nombre_tienda}", cuerpo)


# ── Template: Sugerencias de productos según historial → Cliente ─────────────
def html_sugerencia_cliente(
    cliente_nombre: str,
    categoria:      str,
    productos:      List[Dict],   # [{"nombre": str, "precio": float}, ...]
) -> str:
    filas = "".join(
        f'<tr><td style="padding:10px 0;border-bottom:1px solid #f3f4f6;color:#111827;'
        f'font-size:14px;font-weight:600;">{p["nombre"]}</td>'
        f'<td style="padding:10px 0;border-bottom:1px solid #f3f4f6;color:#ea580c;'
        f'font-size:14px;font-weight:800;text-align:right;">L{p["precio"]:,.2f}</td></tr>'
        for p in productos
    )
    cuerpo = f"""
    <h2 style="margin:0 0 4px;color:#111827;font-size:22px;font-weight:900;">💡 Elegido para ti</h2>
    <p style="margin:0 0 20px;color:#6b7280;font-size:14px;">
      Hola, <strong>{cliente_nombre}</strong> — esto podría gustarte en <strong>{categoria}</strong>
    </p>
    <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-bottom:8px;">{filas}</table>
    {_btn("Ver más", f"{FRONTEND_URL}/fenix/productos?categoria={categoria}")}
    <p style="margin:20px 0 0;color:#9ca3af;font-size:11px;text-align:center;">
      Basado en tu historial de compras en Mercado Fénix.
    </p>
    """
    return _base_html(f"Sugerencias en {categoria} — Mercado Fénix", cuerpo)


# ── Función de envío (síncrona; se llama desde asyncio.to_thread) ────────────
def _enviar_sync(destinatario: str, asunto: str, html: str) -> bool:
    """
    Envía un correo vía la API REST de Mailjet (v3.1).
    - Reintenta ante errores transitorios (timeouts, 429, 5xx) con backoff.
    - NO reintenta ante errores permanentes (4xx que no sea 429: credenciales
      inválidas, remitente no verificado, destinatario mal formado, etc.) —
      reintentar eso solo desperdicia tiempo, el resultado sería el mismo.
    - Nunca lanza excepción: devuelve True/False. El llamador decide qué
      hacer (aquí solo se loguea; la notificación en la app ya quedó guardada
      en BD sin importar si el correo falla).
    """
    if not MAILJET_API_KEY or not MAILJET_API_SECRET:
        print(f"[EMAIL] Credenciales de Mailjet no configuradas. Asunto: {asunto} → {destinatario}")
        return False

    payload = {
        "Messages": [{
            "From": {"Email": MAILJET_FROM_EMAIL, "Name": FROM_NAME},
            "To":   [{"Email": destinatario}],
            "Subject":  asunto,
            "HTMLPart": html,
        }]
    }

    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            resp = requests.post(
                MAILJET_SEND_URL,
                auth=(MAILJET_API_KEY, MAILJET_API_SECRET),
                json=payload,
                timeout=10,
            )
            if resp.status_code == 200:
                print(f"[EMAIL] ✓ Enviado a {destinatario} | {asunto}")
                return True

            if resp.status_code == 429 or resp.status_code >= 500:
                # Rate limit o error del servidor de Mailjet → vale la pena reintentar
                ultimo_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            else:
                # Error permanente (400/401/403 por ejemplo) → no reintentar
                print(f"[EMAIL] ✗ Mailjet rechazó el envío a {destinatario}: "
                      f"HTTP {resp.status_code} — {resp.text[:200]}")
                return False

        except requests.RequestException as e:
            ultimo_error = str(e)

        if intento < MAX_REINTENTOS:
            time.sleep(BACKOFF_BASE_SEGUNDOS * intento)  # 2s, 4s...

    print(f"[EMAIL] ✗ Falló el envío a {destinatario} tras {MAX_REINTENTOS} intentos: {ultimo_error}")
    return False


async def enviar_email(destinatario: str, asunto: str, html: str) -> bool:
    """Wrapper async — no bloquea el event loop de FastAPI."""
    if not destinatario:
        return False
    try:
        return await asyncio.to_thread(_enviar_sync, destinatario, asunto, html)
    except Exception as e:
        print(f"[EMAIL] ✗ Error inesperado enviando a {destinatario}: {e}")
        return False