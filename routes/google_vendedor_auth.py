# backend/routes/google_vendedor_auth.py
#
# Agregar en main.py:
#   from routes.google_vendedor_auth import router as google_vendedor_router
#   app.include_router(google_vendedor_router, prefix="/api")
#
# Variables de entorno necesarias en .env:
#   GOOGLE_CLIENT_ID=xxxxxxx.apps.googleusercontent.com
#   GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxx
#   GOOGLE_REDIRECT_URI=https://tu-backend.onrender.com/api/auth/google-vendedor/callback
#
# Las URLs de callback las configuras en Google Cloud Console >
# APIs y Servicios > Credenciales > ID de cliente de OAuth 2.0 > URIs de redireccionamiento autorizados.

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from urllib.parse import urlencode
from datetime import timedelta

from core.database import get_db
from core.security import create_access_token
from core.auth import ACCESS_TOKEN_EXPIRE_MINUTES
from models.vendedor import Vendedor
from sqlalchemy import func
import traceback

router = APIRouter()

# ── Configuración ─────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI_VENDEDOR", "")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:3000")

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = "openid email profile"


# ═════════════════════════════════════════════════════════════════════════════
# PASO 1: El frontend llama a este endpoint → redirige a Google
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/auth/google-vendedor")
async def google_vendedor_login():
    """
    El frontend hace: window.location.href = '/api/auth/google-vendedor'
    Este endpoint construye la URL de Google y redirige al vendedor.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "GOOGLE_CLIENT_ID no configurado en .env")
    if not GOOGLE_REDIRECT_URI:
        raise HTTPException(500, "GOOGLE_REDIRECT_URI_VENDEDOR no configurado en .env")

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "access_type":   "offline",
        "prompt":        "select_account",
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


# ═════════════════════════════════════════════════════════════════════════════
# PASO 2: Google redirige de vuelta con un "code" → intercambiamos por datos
# ═════════════════════════════════════════════════════════════════════════════
@router.get("/auth/google-vendedor/callback")
async def google_vendedor_callback(
    code:  str = None,
    error: str = None,
    db:    Session = Depends(get_db),
):
    if error or not code:
        raise HTTPException(400, f"Google rechazó el login: {error or 'sin código'}")

    async with httpx.AsyncClient() as client:
        token_res = await client.post(GOOGLE_TOKEN_URL, data={
            "code":          code,
            "client_id":     GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri":  GOOGLE_REDIRECT_URI,
            "grant_type":    "authorization_code",
        })

    if token_res.status_code != 200:
        raise HTTPException(400, "Error al obtener token de Google")

    tokens        = token_res.json()
    google_token  = tokens.get("access_token")
    if not google_token:
        raise HTTPException(400, "Google no devolvió access_token")

    async with httpx.AsyncClient() as client:
        user_res = await client.get(
            GOOGLE_USER_URL,
            headers={"Authorization": f"Bearer {google_token}"}
        )

    if user_res.status_code != 200:
        raise HTTPException(400, "Error al obtener datos del usuario de Google")

    gdata = user_res.json()

    google_id = gdata.get("sub")
    email     = (gdata.get("email") or "").lower().strip()
    if not google_id or not email:
        raise HTTPException(400, "Google no devolvió los datos necesarios")
    if not gdata.get("email_verified", False):
        raise HTTPException(400, "Tu correo de Google no está verificado")

    partes     = (gdata.get("name") or "").split()
    nombre     = gdata.get("given_name") or (partes[0] if partes else "Usuario")
    apellido   = gdata.get("family_name") or " ".join(partes[1:])
    avatar_url = gdata.get("picture")

    try:
        # 1. Ya se registró con Google
        vendedor = db.query(Vendedor).filter(Vendedor.google_id == google_id).first()

        # 2. Cuenta existente por email: vincular
        if not vendedor:
            vendedor = db.query(Vendedor).filter(func.lower(Vendedor.email) == email).first()
            if vendedor:
                vendedor.google_id      = google_id
                vendedor.oauth_provider = vendedor.oauth_provider or "google"
                vendedor.logo_url       = avatar_url

        # 3. Vendedor nuevo (se crea sin password, se completa después)
        if not vendedor:
            vendedor = Vendedor(
                dni=email.split("@")[0][:13] or str(google_id)[:13],
                rtn=None,
                propietario=nombre,
                nombre_tienda=f"Tienda de {nombre}",
                telefono="00000000",
                email=email,
                departamento="",
                municipio="",
                direccion_exacta="",
                password_hash=None,
                logo_url=avatar_url,
                google_id=google_id,
                oauth_provider="google",
            )
            db.add(vendedor)

        db.commit()
        db.refresh(vendedor)
    except Exception as e:
        db.rollback()
        print("[GOOGLE VENDEDOR] ERROR:\n" + traceback.format_exc(), flush=True)
        raise HTTPException(500, f"Error de base de datos: {type(e).__name__}")

    token = create_access_token(
        data={"sub": vendedor.dni, "role": "vendedor"},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": vendedor.dni,
            "nombres": vendedor.propietario,
            "apellidos": "",
            "nombre_tienda": vendedor.nombre_tienda,
            "email": vendedor.email,
            "telefono": vendedor.telefono,
            "avatar_url": avatar_url,
            "perfil_incompleto": not (vendedor.departamento and vendedor.municipio
                                      and vendedor.direccion_exacta and vendedor.telefono != "00000000"),
        },
    }
