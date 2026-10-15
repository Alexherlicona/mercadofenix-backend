# backend/routes/social.py
"""
Rutas para integración con redes sociales (Facebook Pages + Instagram Business).

NIVEL A: Endpoints de estado (qué redes están conectadas).
NIVEL B: OAuth callback, guardar tokens, publicar automáticamente.

Requiere en .env:
    META_APP_ID=tu_app_id
    META_APP_SECRET=tu_app_secret

Tabla en Neon (ejecutar SQL al final del archivo):
    CREATE TABLE redes_sociales_vendedor (...)
"""

import os
import httpx
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text
from sqlalchemy.sql import func
from core.database import get_db, Base
from core.auth import get_current_vendedor
from models.vendedor import Vendedor
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import io, re, uuid
from fastapi.responses import RedirectResponse, Response
from models.producto import Producto, FotoProducto   # ajusta la ruta si difiere

API_PUBLIC_URL = os.getenv("API_PUBLIC_URL", "")      # ej: https://tu-api.onrender.com

router = APIRouter(prefix="/vendedor", tags=["redes-sociales"])
router_publico = APIRouter(prefix="/public", tags=["public-social"])

META_APP_ID     = os.getenv("META_APP_ID", "")
META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_GRAPH_URL  = "https://graph.facebook.com/v19.0"
PLATAFORMA_URL  = os.getenv("PLATAFORMA_URL", "https://mercadofenix.vercel.app")  # Cambiar a tu dominio real en producción

def _to_uuid(v):
    try:
        return uuid.UUID(str(v))
    except Exception:
        return None


def _cloudinary_social(url: str) -> Optional[str]:
    """Cloudinary -> JPEG cuadrado 1080x1080 con fondo blanco. None si no es Cloudinary."""
    if url and "res.cloudinary.com" in url and "/upload/" in url:
        u = url.replace("/upload/", "/upload/f_jpg,q_auto:good,c_pad,b_white,w_1080,h_1080/", 1)
        return re.sub(r"\.(webp|png|jpe?g|gif|avif)$", ".jpg", u, flags=re.I)
    return None


def primera_foto_url(db: Session, producto_id: str) -> Optional[str]:
    pid = _to_uuid(producto_id)
    if not pid:
        return None
    f = (db.query(FotoProducto)
           .filter(FotoProducto.producto_id == pid, FotoProducto.es_video == False)
           .order_by(FotoProducto.orden.asc(), FotoProducto.id.asc())
           .first())
    return f.url if f else None


def foto_social_publica(db: Session, producto_id: str) -> Optional[str]:
    """URL pública y compatible con Meta (JPEG) de la portada del producto."""
    url = primera_foto_url(db, producto_id)
    if not url:
        return None
    return _cloudinary_social(url) or f"{API_PUBLIC_URL}/api/public/producto/{producto_id}/foto-social.jpg"


# ── Modelo SQLAlchemy ─────────────────────────────────────────────────────────
class RedSocialVendedor(Base):
    __tablename__ = "redes_sociales_vendedor"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    vendedor_dni    = Column(String(13), nullable=False, index=True)
    red             = Column(String(20), nullable=False)   # "facebook" | "instagram"
    conectada       = Column(Boolean, default=False)
    page_id         = Column(String(50))
    ig_user_id      = Column(String(50))
    nombre_pagina   = Column(String(200))
    foto_pagina     = Column(String(500))
    access_token    = Column(Text)                         # token de larga duración, encriptarlo en producción
    token_expira    = Column(DateTime)
    posts_total     = Column(Integer, default=0)
    ultimo_post     = Column(DateTime)
    creado_en       = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── Schemas ───────────────────────────────────────────────────────────────────
class ConectarFacebookPayload(BaseModel):
    access_token: str
    user_id: str

class PublicarPayload(BaseModel):
    red: str
    producto_id: str
    texto: str
    foto_url: Optional[str] = None
    producto_url: str


# ── Helpers Graph API ─────────────────────────────────────────────────────────
async def get_long_lived_token(short_token: str) -> dict:
    """Intercambia token corto por token de larga duración (60 días)."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{META_GRAPH_URL}/oauth/access_token", params={
            "grant_type":        "fb_exchange_token",
            "client_id":         META_APP_ID,
            "client_secret":     META_APP_SECRET,
            "fb_exchange_token": short_token,
        })
        r.raise_for_status()
        return r.json()

async def get_pages(user_token: str) -> list:
    """Obtiene las páginas administradas por el usuario."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{META_GRAPH_URL}/me/accounts", params={
            "access_token": user_token,
            "fields":       "id,name,picture,access_token",
        })
        r.raise_for_status()
        return r.json().get("data", [])

async def get_ig_account(page_id: str, page_token: str) -> Optional[dict]:
    """Obtiene la cuenta de Instagram Business vinculada a la página."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{META_GRAPH_URL}/{page_id}", params={
            "fields":       "instagram_business_account{id,username,profile_picture_url}",
            "access_token": page_token,
        })
        data = r.json()
        return data.get("instagram_business_account")

async def publicar_facebook(page_id: str, page_token: str, texto: str, foto_url: Optional[str]) -> dict:
    """Publica en una Página de Facebook."""
    async with httpx.AsyncClient() as client:
        if foto_url:
            # Publicar con imagen
            r = await client.post(f"{META_GRAPH_URL}/{page_id}/photos", data={
                "url":          foto_url,
                "caption":      texto,
                "access_token": page_token,
            })
        else:
            # Solo texto
            r = await client.post(f"{META_GRAPH_URL}/{page_id}/feed", data={
                "message":      texto,
                "access_token": page_token,
            })
        r.raise_for_status()
        return r.json()

async def publicar_instagram(ig_user_id: str, page_token: str, texto: str, foto_url: str) -> dict:
    """
    Publica en Instagram Business (requiere foto obligatoriamente).
    Proceso: crear container → publicar container.
    """
    if not foto_url:
        raise ValueError("Instagram requiere al menos una imagen")

    async with httpx.AsyncClient() as client:
        # Paso 1: crear el media container
        r1 = await client.post(f"{META_GRAPH_URL}/{ig_user_id}/media", data={
            "image_url":    foto_url,
            "caption":      texto[:2200],   # IG límite 2200 chars
            "access_token": page_token,
        })
        r1.raise_for_status()
        container_id = r1.json()["id"]

        # Paso 2: publicar el container
        r2 = await client.post(f"{META_GRAPH_URL}/{ig_user_id}/media_publish", data={
            "creation_id":  container_id,
            "access_token": page_token,
        })
        r2.raise_for_status()
        return r2.json()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router_publico.get("/producto/{producto_id}/foto-social.jpg")
async def foto_social(producto_id: str, db: Session = Depends(get_db)):
    url = primera_foto_url(db, producto_id)
    if not url:
        raise HTTPException(404, "Producto sin foto")

    # Cloudinary: redirige a la versión transformada
    social = _cloudinary_social(url)
    if social:
        return RedirectResponse(social, status_code=302)

    # Fallback (foto en disco local): convertir con Pillow  ->  pip install Pillow
    from PIL import Image
    origen = url if url.startswith("http") else f"{API_PUBLIC_URL}{url}"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(origen)
        r.raise_for_status()

    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    base = Image.new("RGBA", img.size, (255, 255, 255, 255))
    base.alpha_composite(img)                      # aplana transparencia sobre blanco
    img = base.convert("RGB")
    img.thumbnail((1080, 1080))
    lienzo = Image.new("RGB", (1080, 1080), (255, 255, 255))
    lienzo.paste(img, ((1080 - img.width) // 2, (1080 - img.height) // 2))

    buf = io.BytesIO()
    lienzo.save(buf, "JPEG", quality=88)
    return Response(buf.getvalue(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})

@router.get("/redes-sociales")
async def listar_redes(
    vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """Devuelve el estado de conexión de cada red para este vendedor."""
    registros = db.query(RedSocialVendedor).filter(
        RedSocialVendedor.vendedor_dni == vendedor.dni
    ).all()

    resultado = []
    for red in ("facebook", "instagram"):
        reg = next((r for r in registros if r.red == red), None)
        resultado.append({
            "red":           red,
            "conectada":     reg.conectada if reg else False,
            "nombre_pagina": reg.nombre_pagina if reg else None,
            "foto_pagina":   reg.foto_pagina if reg else None,
            "page_id":       reg.page_id if reg else None,
            "ig_user_id":    reg.ig_user_id if reg else None,
            "ultimo_post":   reg.ultimo_post.isoformat() if reg and reg.ultimo_post else None,
            "posts_total":   reg.posts_total if reg else 0,
        })
    return resultado


@router.post("/redes-sociales/conectar-facebook")
async def conectar_facebook(
    payload: ConectarFacebookPayload,
    vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    """
    Recibe el token corto del SDK de Facebook,
    lo intercambia por token largo, obtiene la primera página administrada
    y guarda todo en la BD.
    """
    if not META_APP_ID or not META_APP_SECRET:
        raise HTTPException(400, detail="META_APP_ID y META_APP_SECRET no configurados en el servidor.")

    try:
        # 1. Token largo de usuario
        long_token_data = await get_long_lived_token(payload.access_token)
        user_long_token = long_token_data["access_token"]

        # 2. Páginas administradas
        pages = await get_pages(user_long_token)
        if not pages:
            raise HTTPException(400, detail="No tienes Páginas de Facebook administradas. Crea una Página de negocio primero.")

        page = pages[0]   # Usamos la primera; en producción permitir elegir
        page_id      = page["id"]
        page_token   = page["access_token"]
        nombre_pag   = page["name"]
        foto_pag     = page.get("picture", {}).get("data", {}).get("url")

        # 3. Cuenta Instagram Business vinculada
        ig_account   = await get_ig_account(page_id, page_token)
        ig_user_id   = ig_account["id"] if ig_account else None

        # 4. Guardar / actualizar en BD
        def upsert(red: str, **kwargs):
            reg = db.query(RedSocialVendedor).filter(
                RedSocialVendedor.vendedor_dni == vendedor.dni,
                RedSocialVendedor.red == red
            ).first()
            if reg:
                for k, v in kwargs.items(): setattr(reg, k, v)
            else:
                reg = RedSocialVendedor(vendedor_dni=vendedor.dni, red=red, **kwargs)
                db.add(reg)

        upsert("facebook",
            conectada=True, page_id=page_id, access_token=page_token,
            nombre_pagina=nombre_pag, foto_pagina=foto_pag)

        if ig_user_id:
            upsert("instagram",
                conectada=True, ig_user_id=ig_user_id, page_id=page_id,
                access_token=page_token, nombre_pagina=nombre_pag, foto_pagina=foto_pag)

        db.commit()
        return await listar_redes(vendedor=vendedor, db=db)

    except httpx.HTTPStatusError as e:
        raise HTTPException(400, detail=f"Error de Meta API: {e.response.text}")
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.delete("/redes-sociales/{red}")
async def desconectar_red(
    red: str,
    vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    reg = db.query(RedSocialVendedor).filter(
        RedSocialVendedor.vendedor_dni == vendedor.dni,
        RedSocialVendedor.red == red
    ).first()
    if reg:
        reg.conectada     = False
        reg.access_token  = None
        reg.page_id       = None
        reg.ig_user_id    = None
        db.commit()
    return {"ok": True}


@router.post("/publicar-red-social")
async def publicar_en_red(
    payload: PublicarPayload,
    vendedor: Vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    reg = db.query(RedSocialVendedor).filter(
        RedSocialVendedor.vendedor_dni == vendedor.dni,
        RedSocialVendedor.red == payload.red,
        RedSocialVendedor.conectada == True
    ).first()
    if not reg or not reg.access_token:
        raise HTTPException(400, detail=f"Red {payload.red} no conectada. Usa compartir manual.")

    # El producto debe ser del vendedor (ajusta el nombre del campo dueño si es distinto)
    pid = _to_uuid(payload.producto_id)
    prod = db.query(Producto).filter(
        Producto.id == pid, Producto.vendedor_dni == vendedor.dni
    ).first() if pid else None
    if not prod:
        raise HTTPException(404, detail="Producto no encontrado.")

    # La portada se resuelve en el servidor (se ignora payload.foto_url)
    foto_url = foto_social_publica(db, payload.producto_id)

    try:
        if payload.red == "facebook":
            result   = await publicar_facebook(reg.page_id, reg.access_token, payload.texto, foto_url)
            post_id  = result.get("post_id") or result.get("id")
            post_url = f"https://www.facebook.com/{post_id}" if post_id else None

        elif payload.red == "instagram":
            if not reg.ig_user_id:
                raise HTTPException(400, detail="No tienes cuenta Instagram Business vinculada.")
            if not foto_url:
                raise HTTPException(400, detail="Instagram requiere que el producto tenga al menos una foto.")
            result  = await publicar_instagram(reg.ig_user_id, reg.access_token, payload.texto, foto_url)
            post_id = result.get("id")
            post_url = None
            if post_id:  # el id NO es el shortcode de la URL; se pide el permalink real
                async with httpx.AsyncClient() as c:
                    pr = await c.get(f"{META_GRAPH_URL}/{post_id}",
                                     params={"fields": "permalink", "access_token": reg.access_token})
                    post_url = pr.json().get("permalink")
        else:
            raise HTTPException(400, detail=f"Red {payload.red} no soportada.")

        reg.posts_total = (reg.posts_total or 0) + 1
        reg.ultimo_post = datetime.utcnow()
        db.commit()
        return {"ok": True, "post_id": post_id, "post_url": post_url}

    except httpx.HTTPStatusError as e:
        raise HTTPException(400, detail=f"Error de Meta API: {e.response.text}")

# ── Función helper para auto-publicar al actualizar un producto ───────────────
async def auto_publicar_actualizacion(
    vendedor_dni: str,
    producto: dict,
    db: Session
):
    """
    Llama a esto en background cuando el vendedor actualiza un producto
    y tiene publicación automática activa.

    Uso en routes/vendedor.py al final de editar_producto:
        from routes.social import auto_publicar_actualizacion
        background_tasks.add_task(auto_publicar_actualizacion, vendedor.dni, producto_dict, db)
    """
    redes_activas = db.query(RedSocialVendedor).filter(
        RedSocialVendedor.vendedor_dni == vendedor_dni,
        RedSocialVendedor.conectada == True
    ).all()

    if not redes_activas:
        return

    from core.slug import slug_tienda
    vendedor = db.query(Vendedor).filter(Vendedor.dni == vendedor_dni).first()
    if not vendedor:
        return

    slug = slug_tienda(vendedor.nombre_tienda, vendedor.municipio)
    url = f"{PLATAFORMA_URL}/fenix/tiendas/{slug}?producto={producto['id']}"
    precio = producto.get("precio_con_descuento") or producto.get("precio", 0)
    texto = (
        f"¡Nuevo producto en {vendedor.nombre_tienda}! 🎉\n\n"
        f"{producto['nombre']} - L. {precio:,.2f}\n\n"
        f"{producto['descripcion'][:100]}...\n\n"
        f"Ver más: {url}"
    )

    foto_url = foto_social_publica(db, producto["id"])

    for reg in redes_activas:
        try:
            if reg.red == "facebook":
                await publicar_facebook(reg.page_id, reg.access_token, texto, foto_url)
            elif reg.red == "instagram" and reg.ig_user_id and foto_url:
                await publicar_instagram(reg.ig_user_id, reg.access_token, texto, foto_url)
            reg.posts_total = (reg.posts_total or 0) + 1
            reg.ultimo_post = datetime.utcnow()
        except Exception as e:
            print(f"[social] Error publicando actualización en {reg.red}: {e}")

    db.commit()


# ══════════════════════════════════════════════════════════════════════════════
# SQL para ejecutar en Neon (crear tabla):
# ══════════════════════════════════════════════════════════════════════════════
"""
CREATE TABLE IF NOT EXISTS redes_sociales_vendedor (
    id              SERIAL PRIMARY KEY,
    vendedor_dni    VARCHAR(13) NOT NULL,
    red             VARCHAR(20) NOT NULL,
    conectada       BOOLEAN DEFAULT false,
    page_id         VARCHAR(50),
    ig_user_id      VARCHAR(50),
    nombre_pagina   VARCHAR(200),
    foto_pagina     VARCHAR(500),
    access_token    TEXT,
    token_expira    TIMESTAMP,
    posts_total     INTEGER DEFAULT 0,
    ultimo_post     TIMESTAMP,
    creado_en       TIMESTAMPTZ DEFAULT now(),
    actualizado_en  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(vendedor_dni, red),
    FOREIGN KEY (vendedor_dni) REFERENCES vendedores(dni) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_redes_vendedor ON redes_sociales_vendedor(vendedor_dni);
"""