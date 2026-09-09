# backend/routes/carrito.py
from fastapi import APIRouter, Request, Response, Depends, Header
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from core.database import get_db
from models.carrito import Carrito, CarritoItem
from models.producto import FotoProducto, Producto
from models.cliente import Cliente
from typing import Optional
from jose import jwt, JWTError
from core.security import SECRET_KEY, ALGORITHM
import uuid

router = APIRouter(prefix="/api/carrito", tags=["carrito"])


# ─── HELPER: obtener cliente desde token (sin lanzar error si no hay token) ───
def get_cliente_opcional(request: Request, db: Session) -> Optional[Cliente]:
    """
    Intenta autenticar al cliente desde el header Authorization.
    Si no hay token o es inválido, retorna None (usuario anónimo).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        telefono = payload.get("sub")
        role = payload.get("role")
        if not telefono or (role is not None and role != "cliente"):
            return None
        return db.query(Cliente).filter(Cliente.telefono == telefono).first()
    except JWTError:
        return None


# ─── HELPER: obtener o crear carrito ─────────────────────────────────────────
def get_or_create_carrito(
    db: Session,
    session_id: str,
    cliente_id: Optional[int]
) -> Carrito:
    """
    Lógica de resolución del carrito:
    1. Si el cliente está autenticado, busca su carrito por cliente_id.
    2. Si no tiene carrito propio aún, busca el carrito anónimo de la sesión
       y lo adopta (asigna cliente_id).
    3. Si hay carrito anónimo Y carrito del cliente, fusiona los items del
       anónimo al del cliente y elimina el anónimo.
    4. Si nadie tiene carrito, crea uno nuevo.
    """
    if cliente_id:
        carrito_cliente = db.query(Carrito).filter(
            Carrito.cliente_id == cliente_id
        ).first()

        carrito_anonimo = db.query(Carrito).filter(
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first() if session_id else None

        if carrito_cliente and carrito_anonimo:
            # Fusionar: mover items del anónimo al del cliente
            for item_anonimo in carrito_anonimo.items:
                # Ver si ya existe el mismo producto+variante en el carrito del cliente
                item_existente = db.query(CarritoItem).filter(
                    CarritoItem.carrito_id == carrito_cliente.id,
                    CarritoItem.producto_id == item_anonimo.producto_id,
                    CarritoItem.color == item_anonimo.color,
                    CarritoItem.talla == item_anonimo.talla
                ).first()

                if item_existente:
                    item_existente.cantidad += item_anonimo.cantidad
                else:
                    db.add(CarritoItem(
                        carrito_id=carrito_cliente.id,
                        producto_id=item_anonimo.producto_id,
                        cantidad=item_anonimo.cantidad,
                        precio_unitario=item_anonimo.precio_unitario,
                        nombre_producto=item_anonimo.nombre_producto,
                        nombre_tienda=item_anonimo.nombre_tienda,
                        imagen_principal=item_anonimo.imagen_principal,
                        color=item_anonimo.color,
                        talla=item_anonimo.talla,
                    ))

            db.delete(carrito_anonimo)
            db.commit()
            db.refresh(carrito_cliente)
            return carrito_cliente

        if carrito_cliente:
            return carrito_cliente

        if carrito_anonimo:
            # Adoptar el carrito anónimo
            carrito_anonimo.cliente_id = cliente_id
            db.commit()
            db.refresh(carrito_anonimo)
            return carrito_anonimo

        # Crear carrito nuevo para el cliente
        nuevo = Carrito(session_id=str(uuid.uuid4()), cliente_id=cliente_id)
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)
        return nuevo

    else:
        # Usuario anónimo: buscar por session_id sin cliente
        carrito = db.query(Carrito).filter(
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first()

        if not carrito:
            carrito = Carrito(session_id=session_id, cliente_id=None)
            db.add(carrito)
            db.commit()
            db.refresh(carrito)

        return carrito


# ─── POST /add ────────────────────────────────────────────────────────────────
@router.post("/add")
async def add_to_cart(request: Request, response: Response, db: Session = Depends(get_db)):
    data = await request.json()
    cliente = get_cliente_opcional(request, db)

    # Gestionar cookie de sesión (sirve para anónimos y como fallback)
    session_id = request.cookies.get("cart_session")
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(
            key="cart_session",
            value=session_id,
            httponly=True,
            max_age=60 * 60 * 24 * 30,
            samesite="lax",
            secure=False
        )

    cart = get_or_create_carrito(db, session_id, cliente.id if cliente else None)

    # Buscar item existente (mismo producto + variantes)
    existing_item = db.query(CarritoItem).filter(
        CarritoItem.carrito_id == cart.id,
        CarritoItem.producto_id == data["producto_id"],
        CarritoItem.color == (data.get("color") or None),
        CarritoItem.talla == (data.get("talla") or None)
    ).first()

    if existing_item:
        existing_item.cantidad += data.get("cantidad", 1)
    else:
        producto = db.query(Producto).filter(Producto.id == data["producto_id"]).first()
        imagen = None
        if producto:
            foto = db.query(FotoProducto).filter(
                FotoProducto.producto_id == producto.id
            ).order_by(FotoProducto.orden).first()
            if foto:
                imagen = foto.url

        db.add(CarritoItem(
            carrito_id=cart.id,
            producto_id=data["producto_id"],
            cantidad=data.get("cantidad", 1),
            precio_unitario=data["precio"],
            nombre_producto=data["nombre"],
            nombre_tienda=data["nombre_tienda"],
            imagen_principal=imagen or "/placeholder.jpg",
            color=data.get("color"),
            talla=data.get("talla"),
        ))

    db.commit()
    db.refresh(cart)

    total_items = sum(i.cantidad for i in cart.items)
    return {"msg": "agregado", "total_items": total_items}


# ─── GET /mi-carrito ──────────────────────────────────────────────────────────
@router.get("/mi-carrito")
async def get_cart(request: Request, db: Session = Depends(get_db)):
    cliente = get_cliente_opcional(request, db)
    session_id = request.cookies.get("cart_session")

    if not session_id and not cliente:
        return {"items": [], "total": 0.0}

    # Buscar carrito según autenticación
    if cliente:
        cart = db.query(Carrito).options(joinedload(Carrito.items)).filter(
            Carrito.cliente_id == cliente.id
        ).first()
    else:
        cart = db.query(Carrito).options(joinedload(Carrito.items)).filter(
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first()

    if not cart:
        return {"items": [], "total": 0.0}

    items = []
    total = 0.0
    for item in cart.items:
        item_total = float(item.precio_unitario) * item.cantidad
        total += item_total
        items.append({
            "id": item.id,
            "producto_id": str(item.producto_id),
            "nombre_producto": item.nombre_producto,
            "nombre_tienda": item.nombre_tienda,
            "imagen_principal": item.imagen_principal,
            "cantidad": item.cantidad,
            "precio_unitario": float(item.precio_unitario),
            "total_item": item_total,
            "color": item.color,
            "talla": item.talla
        })

    return {"items": items, "total": round(total, 2)}


# ─── PUT /update/{item_id} ────────────────────────────────────────────────────
@router.put("/update/{item_id}")
async def update_cart_item(item_id: int, request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    nueva_cantidad = max(1, data.get("cantidad", 1))
    cliente = get_cliente_opcional(request, db)
    session_id = request.cookies.get("cart_session")

    # Verificar que el item pertenece al carrito correcto del usuario
    if cliente:
        item = db.query(CarritoItem).join(Carrito).filter(
            CarritoItem.id == item_id,
            Carrito.cliente_id == cliente.id
        ).first()
    else:
        if not session_id:
            return {"error": "no session"}
        item = db.query(CarritoItem).join(Carrito).filter(
            CarritoItem.id == item_id,
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first()

    if item:
        item.cantidad = nueva_cantidad
        db.commit()
        return {"msg": "actualizado"}
    return {"error": "no encontrado"}


# ─── DELETE /remove/{item_id} ─────────────────────────────────────────────────
@router.delete("/remove/{item_id}")
async def remove_from_cart(item_id: int, request: Request, db: Session = Depends(get_db)):
    cliente = get_cliente_opcional(request, db)
    session_id = request.cookies.get("cart_session")

    if cliente:
        item = db.query(CarritoItem).join(Carrito).filter(
            CarritoItem.id == item_id,
            Carrito.cliente_id == cliente.id
        ).first()
    else:
        if not session_id:
            return {"error": "no session"}
        item = db.query(CarritoItem).join(Carrito).filter(
            CarritoItem.id == item_id,
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first()

    if item:
        db.delete(item)
        db.commit()
        return {"msg": "eliminado"}
    return {"error": "no encontrado"}


# ─── POST /vaciar ─────────────────────────────────────────────────────────────
@router.post("/vaciar")
async def vaciar_carrito(request: Request, db: Session = Depends(get_db)):
    """Vaciar el carrito después de confirmar un pedido"""
    cliente = get_cliente_opcional(request, db)
    session_id = request.cookies.get("cart_session")

    if cliente:
        cart = db.query(Carrito).filter(Carrito.cliente_id == cliente.id).first()
    elif session_id:
        cart = db.query(Carrito).filter(
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first()
    else:
        return {"msg": "no hay carrito"}

    if cart:
        db.query(CarritoItem).filter(CarritoItem.carrito_id == cart.id).delete()
        db.commit()

    return {"msg": "carrito vaciado"}