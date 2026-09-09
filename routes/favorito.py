# backend/routes/favorito.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from core.database import get_db
from core.auth import get_current_user  # ← Tu dependencia existente
from models.cliente import Cliente
from models.producto import Producto
from models.favorito import Favorito

router = APIRouter(prefix="/api/favoritos", tags=["favoritos"])

@router.get("/")
async def obtener_favoritos(
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    favoritos = db.query(Favorito).filter(
        Favorito.cliente_id == current_user.id
    ).all()

    producto_ids = [f.producto_id for f in favoritos]

    if not producto_ids:
        return {"favoritos": []}

    productos = db.query(Producto)\
        .filter(Producto.id.in_(producto_ids))\
        .options(joinedload(Producto.fotos))\
        .all()

    result = []
    for prod in productos:
        # Corrección aquí ↓
        precio_float = float(prod.precio)
        descuento = float(prod.porcentaje_descuento or 0)
        precio_final = precio_float * (1 - descuento / 100)

        result.append({
            "id": str(prod.id),
            "nombre": prod.nombre,
            "categoria": prod.categoria,
            "precio": precio_float,
            "porcentaje_descuento": descuento,
            "precio_final": round(precio_final, 2),
            "descripcion": prod.descripcion or "",
            "stock": prod.stock,
            "fotos": sorted(
                [{"url": f.url, "orden": f.orden} for f in prod.fotos],
                key=lambda x: x["orden"]
            ) if prod.fotos else []
        })

    return {"favoritos": result}

@router.post("/add/{producto_id}")
async def agregar_favorito(
    producto_id: str,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Validar que el producto exista (esto está bien)
    producto = db.query(Producto).filter(Producto.id == producto_id).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    # Ver si ya existe
    existe = db.query(Favorito).filter(
        Favorito.cliente_id == current_user.id,
        Favorito.producto_id == producto_id
    ).first()

    if existe:
        return {"msg": "Ya está en tus favoritos", "status": "already_exists"}  # ← 200 OK

    # Si no existe, crear
    nuevo = Favorito(
        cliente_id=current_user.id,
        producto_id=producto_id
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)

    return {"msg": "Agregado a favoritos ❤️", "status": "added"}


@router.delete("/remove/{producto_id}")
async def eliminar_favorito(
    producto_id: str,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    favorito = db.query(Favorito).filter(
        Favorito.cliente_id == current_user.id,
        Favorito.producto_id == producto_id
    ).first()

    if not favorito:
        raise HTTPException(404, "No tienes este producto en favoritos")

    db.delete(favorito)
    db.commit()

    return {"msg": "Eliminado de favoritos"}