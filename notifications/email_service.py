# backend/notifications/email_service.py
#
# Envío de correos transaccionales usando smtplib estándar (sin dependencias extra).
# Variables de entorno requeridas en .env:
#   SMTP_HOST=smtp.gmail.com
#   SMTP_PORT=587
#   SMTP_USER=notificaciones@mercadofenix.com
#   SMTP_PASSWORD=tu_app_password          ← En Gmail usar "App Password", no la contraseña normal
#   EMAIL_FROM_NAME=Mercado Fénix
#   FRONTEND_URL=https://mercadofenix.com
#
# Para Gmail: Activar verificación en 2 pasos → Generar App Password en
# https://myaccount.google.com/apppasswords

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional
import asyncio
from datetime import datetime

SMTP_HOST      = os.getenv("SMTP_HOST",      "smtp.gmail.com")
SMTP_PORT      = int(os.getenv("SMTP_PORT",  "587"))
SMTP_USER      = os.getenv("SMTP_USER",      "")
SMTP_PASSWORD  = os.getenv("SMTP_PASSWORD",  "")
FROM_NAME      = os.getenv("EMAIL_FROM_NAME","Mercado Fénix")
FRONTEND_URL   = os.getenv("FRONTEND_URL",   "http://localhost:3000")


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

    <!-- Badge pedido -->
    <div style="background:#fff7ed;border:1.5px solid #fed7aa;border-radius:12px;padding:16px 20px;margin-bottom:24px;">
      <p style="margin:0;color:#ea580c;font-size:13px;font-weight:700;">PEDIDO #{pedido_id}</p>
      <p style="margin:4px 0 0;color:#9a3412;font-size:28px;font-weight:900;">L{total:,.2f}</p>
    </div>

    <!-- Detalle -->
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

    <!-- Badge estado -->
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


# ── Función de envío (síncrona, se llama desde asyncio.to_thread) ─────────────
def _enviar_sync(destinatario: str, asunto: str, html: str):
    """Envío SMTP con TLS. Lanza excepción si falla — capturar en el caller."""
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[EMAIL] Credenciales SMTP no configuradas. Asunto: {asunto} → {destinatario}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"]    = f"{FROM_NAME} <{SMTP_USER}>"
    msg["To"]      = destinatario
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.sendmail(SMTP_USER, destinatario, msg.as_string())
    print(f"[EMAIL] ✓ Enviado a {destinatario} | {asunto}")


async def enviar_email(destinatario: str, asunto: str, html: str):
    """Wrapper async — no bloquea el event loop de FastAPI."""
    try:
        await asyncio.to_thread(_enviar_sync, destinatario, asunto, html)
    except Exception as e:
        print(f"[EMAIL] ✗ Error enviando a {destinatario}: {e}")