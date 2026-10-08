# backend/routes/google_auth.py
#
# Agregar en main.py:
#   from routes.google_auth import router as google_router
#   app.include_router(google_router, prefix="/api")
#
# Variables de entorno necesarias en .env:
#   GOOGLE_CLIENT_ID=xxxxxxx.apps.googleusercontent.com
#   GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxxxxx
#   GOOGLE_REDIRECT_URI=http://localhost:3000/fenix/mi-cuenta/auth/callback
#
# Para producción cambiar GOOGLE_REDIRECT_URI a tu dominio real.

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
from models.cliente import Cliente
from sqlalchemy import func
import traceback

router = APIRouter()

# ── Configuración ─────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID     = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:3000/fenix/mi-cuenta/auth/callback")
FRONTEND_URL         = os.getenv("FRONTEND_URL", "http://localhost:3000")

GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USER_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

SCOPES = "openid email profile"


# ════════════════════════════════════════════════════════════════════════════
# PASO 1: El frontend llama a este endpoint → redirige a Google
# ════════════════════════════════════════════════════════════════════════════
@router.get("/auth/google")
async def google_login():
    """
    El frontend hace: window.location.href = '/api/auth/google'
    Este endpoint construye la URL de Google y redirige al usuario.
    """
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(500, "GOOGLE_CLIENT_ID no configurado en .env")

    params = {
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         SCOPES,
        "access_type":   "offline",
        "prompt":        "select_account",  # siempre mostrar selector de cuenta
    }
    url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"
    return RedirectResponse(url)


# ════════════════════════════════════════════════════════════════════════════
# PASO 2: Google redirige de vuelta con un "code" → intercambiamos por datos
# Este endpoint es llamado desde el frontend con el code en query string
# ════════════════════════════════════════════════════════════════════════════
@router.get("/auth/google/callback")
async def google_callback(
    code:  str = None,
    error: str = None,
    db:    Session = Depends(get_db),
):
    """
    Recibe el código de Google, lo intercambia por el token,
    obtiene los datos del usuario y devuelve nuestro JWT.
    El frontend llama a este endpoint con el code que Google le dio.
    """
    if error or not code:
        raise HTTPException(400, f"Google rechazó el login: {error or 'sin código'}")

    # ── Intercambiar code por access_token de Google ──────────────────────
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

    # ── Obtener datos del usuario de Google ───────────────────────────────
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
        cliente = db.query(Cliente).filter(Cliente.google_id == google_id).first()

        # 2. Cuenta existente por email: vincular
        if not cliente:
            cliente = db.query(Cliente).filter(func.lower(Cliente.email) == email).first()
            if cliente:
                cliente.google_id      = google_id
                cliente.oauth_provider = cliente.oauth_provider or "google"
                cliente.email_verified = True
                cliente.avatar_url     = avatar_url

        # 3. Cliente nuevo
        if not cliente:
            cliente = Cliente(
                nombres=nombre, apellidos=apellido, email=email,
                telefono=None, password_hash=None,
                departamento="", municipio="", direccion_exacta="",
                google_id=google_id, avatar_url=avatar_url,
                oauth_provider="google", email_verified=True,
            )
            db.add(cliente)

        db.commit()
        db.refresh(cliente)
    except Exception as e:
        db.rollback()
        print("[GOOGLE] ERROR:\n" + traceback.format_exc(), flush=True)
        raise HTTPException(500, f"Error de base de datos: {type(e).__name__}")

    token = create_access_token(
        data={"sub": cliente.telefono or email, "role": "cliente", "cliente_id": cliente.id},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": cliente.id,
            "nombres": cliente.nombres,
            "apellidos": cliente.apellidos,
            "email": cliente.email,
            "avatar_url": avatar_url,
            "perfil_incompleto": not (cliente.telefono and cliente.departamento
                                      and cliente.municipio and cliente.direccion_exacta),
        },
    }