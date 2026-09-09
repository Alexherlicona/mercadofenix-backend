# backend/routes/public.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import desc, and_, func
from core.database import get_db
from models.producto import Producto, FotoProducto
from models.vendedor import Vendedor
from datetime import datetime
from typing import List
from core.slug import slug_tienda

router = APIRouter(prefix="/api/public", tags=["público"])

# === ENDPOINTS QUE NECESITAS PARA EL HOME ===
@router.get("/destacados")
async def get_destacados(db: Session = Depends(get_db)):
    productos = db.query(Producto)\
        .options(joinedload(Producto.fotos))\
        .join(Vendedor)\
        .filter(
            Producto.activo == True,
            Vendedor.activo == True,
            Producto.destacado == True
        )\
        .order_by(desc(Producto.ventas_count))\
        .limit(12)\
        .all()

    return [producto_to_dict(p) for p in productos]


@router.get("/ofertas")
async def get_ofertas(db: Session = Depends(get_db)):
    productos = db.query(Producto)\
        .options(joinedload(Producto.fotos))\
        .join(Vendedor)\
        .filter(
            Producto.activo == True,
            Vendedor.activo == True,
            Producto.precio_con_descuento.isnot(None)
        )\
        .order_by(desc(Producto.porcentaje_descuento))\
        .limit(12)\
        .all()

    return [producto_to_dict(p) for p in productos]


@router.get("/nuevos")
async def get_nuevos(db: Session = Depends(get_db)):
    productos = db.query(Producto)\
        .options(joinedload(Producto.fotos))\
        .join(Vendedor)\
        .filter(
            Producto.activo == True,
            Vendedor.activo == True
        )\
        .order_by(desc(Producto.creado_en))\
        .limit(12)\
        .all()

    return [producto_to_dict(p) for p in productos]



@router.get("/fotos/{foto_id}")
async def get_foto_producto(foto_id: int, db: Session = Depends(get_db)):
    foto = db.query(FotoProducto).filter(FotoProducto.id == foto_id).first()
    if not foto:
        raise HTTPException(404, "Foto no encontrada")
    return {"url": foto.url}



# === Utilidad para convertir a JSON ===
# ============================================================
# PARCHE para backend/routes/public.py
# Dos cambios — ambos van DENTRO del archivo que ya tienes y
# que YA está montado en main.py con prefix="/api/public"
# (confirmado porque /api/public/destacados, /ofertas, etc. funcionan).
# ============================================================


# ── CAMBIO 1 ────────────────────────────────────────────────────────────────
# En la función producto_to_dict(), agregar "stock" al diccionario.
# Esto es la causa raíz real: el listado nunca mandaba stock al frontend,
# por eso ProductModal y ProductCard siempre lo veían como undefined/0.
#
# Buscar esta función y reemplazarla completa:

def producto_to_dict(producto: Producto):
    fotos_url = [f.url for f in sorted(producto.fotos, key=lambda x: x.orden)]

    es_digital = producto.tipo == "digital"

    return {
        "id": str(producto.id),
        "nombre": producto.nombre,
        "precio": float(producto.precio),
        "precio_oferta": float(producto.precio_con_descuento) if producto.precio_con_descuento else None,
        "porcentaje_descuento": float(producto.porcentaje_descuento) if producto.porcentaje_descuento else 0,
        "descripcion": producto.descripcion or "",
        "fotos": fotos_url,
        "nombre_tienda": producto.vendedor.nombre_tienda,
        "logo_tienda": producto.vendedor.logo_url,
        "tipo": producto.tipo,
        "categoria": producto.categoria,
        "variantes": producto.variantes or {},
        "es_nuevo": (datetime.now() - producto.creado_en.replace(tzinfo=None)).days <= 7,
        "ventas_count": producto.ventas_count,
        # ── NUEVO: stock real, directo del modelo (models/producto.py → Integer, default=1) ──
        "stock": None if es_digital else (producto.stock if producto.stock is not None else 0),
        "ilimitado": es_digital,
    }


# ── CAMBIO 2 ────────────────────────────────────────────────────────────────
# Agregar estos dos endpoints nuevos al final del archivo (antes o después
# de get_tienda_con_productos, da igual). Usan el MISMO router que ya existe
# arriba (router = APIRouter(prefix="/api/public", ...)) — no crear otro router.
#
# Rutas finales: GET /api/public/producto/{id}/stock
#                POST /api/public/productos/stock-batch
#
# (Si prefieres mantener exactamente las rutas que ya probé en el navegador
#  — /api/productos/{id}/stock — usa la Opción B más abajo en su lugar.)

@router.get("/producto/{producto_id}/stock")
async def get_stock_producto(producto_id: str, db: Session = Depends(get_db)):
    """
    Stock real y actual de un producto, por ID exacto.
    Usado por ProductModal para no depender de lo que traiga el objeto
    producto recibido por props (que puede venir de un listado distinto).
    """
    producto = db.query(Producto).filter(Producto.id == producto_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    es_digital = producto.tipo == "digital"
    stock_val = None if es_digital else (producto.stock if producto.stock is not None else 0)

    return {
        "id": str(producto.id),
        "tipo": producto.tipo,
        "stock": stock_val,
        "ilimitado": es_digital,
        "agotado": (not es_digital) and stock_val is not None and stock_val <= 0,
    }


@router.post("/productos/stock-batch")
async def get_stock_batch(producto_ids: List[str], db: Session = Depends(get_db)):
    """
    Stock real de varios productos a la vez. Usado por el carrito para
    no hacer un fetch por cada item — una sola llamada con todos los IDs.
    Body: ["uuid1", "uuid2", "uuid3"]
    """
    if not producto_ids:
        return {}

    productos = db.query(Producto).filter(Producto.id.in_(producto_ids)).all()
    resultado = {}
    for p in productos:
        es_digital = p.tipo == "digital"
        stock_val = None if es_digital else (p.stock if p.stock is not None else 0)
        resultado[str(p.id)] = {
            "stock": stock_val,
            "ilimitado": es_digital,
            "activo": p.activo,
            "agotado": (not es_digital) and stock_val is not None and stock_val <= 0,
        }
    return resultado


# ============================================================
# OPCIÓN B — si prefieres NO cambiar las rutas del frontend
# (ProductModal y carrito ya están configurados para llamar a
# /api/productos/{id}/stock y /api/productos/stock-batch, SIN
# el segmento "public"), entonces usa estas rutas en su lugar:
#
# @router.get("/../productos/{producto_id}/stock")  ← esto NO funciona en FastAPI
#
# La forma correcta es declarar las rutas con el path completo
# usando un router SEPARADO sin prefix, o ajustar el prefix.
# La opción más simple: deja el Cambio 2 tal cual (con prefix
# /api/public) y actualiza el frontend para apuntar a esas rutas
# en vez de /api/productos/... — ver instrucciones después de
# este archivo.
# ============================================================
    
# En el mismo routes/public.py
@router.get("/producto/{producto_id}")
async def get_producto(producto_id: str, db: Session = Depends(get_db)):
    producto = db.query(Producto)\
        .options(joinedload(Producto.fotos))\
        .join(Vendedor)\
        .filter(
            Producto.id == producto_id,
            Producto.activo == True,
            Vendedor.activo == True
        )\
        .first()
    
    if not producto:
        raise HTTPException(404, "Producto no encontrado")
    
    return producto_to_dict(producto)

@router.get("/productos")
async def get_all_productos(db: Session = Depends(get_db)):
    productos = db.query(Producto)\
        .options(joinedload(Producto.fotos))\
        .join(Vendedor)\
        .filter(
            Producto.activo == True,
            Vendedor.activo == True
        )\
        .order_by(desc(Producto.ventas_count))\
        .all()

    return {
        "productos": [producto_to_dict(p) for p in productos]
    }
    
@router.get("/tiendas")
async def get_tiendas(db: Session = Depends(get_db)):
    tiendas = db.query(Vendedor)\
        .filter(Vendedor.activo == True)\
        .order_by(desc(Vendedor.visitas_totales))\
        .all()
 
    tiendas_publicas = []
    for t in tiendas:
        num_productos = db.query(func.count(Producto.id))\
            .filter(
                Producto.vendedor_id == t.dni,
                Producto.activo == True
            )\
            .scalar() or 0
 
        tiendas_publicas.append({
            "slug": slug_tienda(t.nombre_tienda, t.municipio),  # identificador público
            "logo_url": t.logo_url,
            "nombre_tienda": t.nombre_tienda,
            "departamento": t.departamento,
            "ciudad": t.municipio,
            "tipo_pago": t.tipo_pago or [],
            "tipo_entrega": t.tipo_entrega or [],
            "rating": 0.0,
            "num_productos": num_productos
        })
 
    return tiendas_publicas
 
 
@router.get("/tienda/{slug}")
async def get_tienda_con_productos(slug: str, db: Session = Depends(get_db)):
    """Info de una tienda + sus productos activos, buscando por slug (sin exponer DNI)."""
    tiendas = db.query(Vendedor).filter(Vendedor.activo == True).all()
 
    tienda = None
    for t in tiendas:
        if slug_tienda(t.nombre_tienda, t.municipio) == slug:
            tienda = t
            break
 
    if not tienda:
        raise HTTPException(404, "Tienda no encontrada")
 
    tienda.visitas_totales = (tienda.visitas_totales or 0) + 1
    db.commit()
 
    productos = db.query(Producto)\
        .options(joinedload(Producto.fotos))\
        .filter(
            Producto.vendedor_id == tienda.dni,
            Producto.activo == True
        )\
        .order_by(desc(Producto.ventas_count))\
        .all()
 
    return {
        "tienda": {
            "slug": slug,
            "nombre_tienda": tienda.nombre_tienda,
            "propietario": tienda.propietario,
            "logo_url": tienda.logo_url,
            "departamento": tienda.departamento,
            "municipio": tienda.municipio,
            "direccion_exacta": tienda.direccion_exacta,
            "telefono": tienda.telefono,
            "tipo_pago": tienda.tipo_pago or [],
            "tipo_entrega": tienda.tipo_entrega or [],
            "visitas_totales": tienda.visitas_totales,
            "num_productos": len(productos),
        },
        "productos": [producto_to_dict(p) for p in productos]
    }