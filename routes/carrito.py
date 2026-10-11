# backend/routes/carrito.py
from fastapi import APIRouter, Request, Response, Depends, Header, HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from core.database import get_db
from models.carrito import Carrito, CarritoItem
from models.producto import FotoProducto, Producto
from models.cliente import Cliente
from typing import Optional
from jose import jwt, JWTError
from core.security import SECRET_KEY, ALGORITHM
import uuid
import os
import re
import unicodedata
from models.vendedor import Vendedor
router = APIRouter(prefix="/api/carrito", tags=["carrito"])

COOKIE_SECURE   = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE = "none" if COOKIE_SECURE else "lax"

def get_session_id(request: Request) -> Optional[str]:
    """Header primero (funciona entre dominios); cookie como respaldo."""
    return request.headers.get("X-Cart-Session") or request.cookies.get("cart_session")


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
        role = payload.get("role")
        if role is not None and role != "cliente":
            return None

        cliente_id = payload.get("cliente_id")
        sub = payload.get("sub")

        if cliente_id:
            cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
            if cliente:
                return cliente
        if sub:
            return db.query(Cliente).filter(
                or_(Cliente.telefono == sub, Cliente.email == sub)
            ).first()
        return None
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
            carrito_anonimo.cliente_id = cliente_id
            carrito_anonimo.session_id = str(uuid.uuid4())  # libera el de la cookie
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
        carrito = db.query(Carrito).filter(
            Carrito.session_id == session_id,
            Carrito.cliente_id == None
        ).first()
        if carrito:
            return carrito

        # Si ese session_id ya lo usa el carrito de un cliente (cookie vieja
        # tras cerrar sesión), este visitante necesita una sesión nueva.
        if db.query(Carrito.id).filter(Carrito.session_id == session_id).first():
            session_id = str(uuid.uuid4())

        carrito = Carrito(session_id=session_id, cliente_id=None)
        db.add(carrito)
        try:
            db.commit()
        except IntegrityError:
            # Doble clic / dos peticiones simultáneas: gana la primera
            db.rollback()
            carrito = db.query(Carrito).filter(
                Carrito.session_id == session_id,
                Carrito.cliente_id == None
            ).first()
            if not carrito:
                raise
            return carrito
        db.refresh(carrito)
        return carrito


# ─── POST /add ────────────────────────────────────────────────────────────────
@router.post("/add")
async def add_to_cart(request: Request, response: Response, db: Session = Depends(get_db)):
    data = await request.json()
    cliente = get_cliente_opcional(request, db)

    # Gestionar cookie de sesión (sirve para anónimos y como fallback)
    session_id = get_session_id(request) or str(uuid.uuid4())

    cart = get_or_create_carrito(db, session_id, cliente.id if cliente else None)

    # Cookie solo como respaldo para invitados
    if not cliente and request.cookies.get("cart_session") != cart.session_id:
        response.set_cookie(
            key="cart_session",
            value=cart.session_id,
            httponly=True,
            max_age=60 * 60 * 24 * 30,
            samesite=COOKIE_SAMESITE,
            secure=COOKIE_SECURE,
        )

    cart = get_or_create_carrito(db, session_id, cliente.id if cliente else None)
    
    if not cliente and cart.session_id != session_id:
        response.set_cookie(
            key="cart_session",
            value=cart.session_id,
            httponly=True,
            max_age=60 * 60 * 24 * 30,
            samesite=COOKIE_SAMESITE,
            secure=COOKIE_SECURE,
        )

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
    return {
        "msg": "agregado",
        "total_items": total_items,
        # El frontend se queda con el ID real si el backend tuvo que rotarlo
        "session_id": cart.session_id if not cliente else None,
    }


# ─── GET /mi-carrito ──────────────────────────────────────────────────────────
@router.get("/mi-carrito")
async def get_cart(request: Request, db: Session = Depends(get_db)):
    cliente = get_cliente_opcional(request, db)
    session_id = get_session_id(request)

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
    session_id = get_session_id(request)

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
    session_id = get_session_id(request)

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
    session_id = get_session_id(request)

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
# ─── POST /merge ──────────────────────────────────────────────────────────────
@router.post("/merge")
async def merge_cart(request: Request, db: Session = Depends(get_db)):
    """Se llama justo después de iniciar sesión: pasa el carrito de invitado al usuario."""
    cliente = get_cliente_opcional(request, db)
    if not cliente:
        raise HTTPException(status_code=401, detail="Debes iniciar sesión")

    session_id = get_session_id(request)
    cart = get_or_create_carrito(db, session_id, cliente.id)
    db.refresh(cart)
    return {"total_items": sum(i.cantidad for i in cart.items)}

# ─── Opciones de checkout según lo que configuró cada vendedor ────────────────
PAGO_TODOS             = ["efectivo", "transferencia"]
ENTREGA_VENDEDOR_TODOS = ["domicilio", "tienda"]
ENTREGA_PLATAFORMA     = ["oficina_fenix"]  # no depende del vendedor


def _norm(valor) -> str:
    t = unicodedata.normalize("NFKD", str(valor or ""))
    return t.encode("ascii", "ignore").decode().lower()


def parsear_pago(valor) -> list[str]:
    t = _norm(valor)
    if not t.strip() or re.search(r"ambos|ambas|todos|todas", t):
        return PAGO_TODOS[:]
    res = []
    if "efectivo" in t:
        res.append("efectivo")
    if "transfer" in t or "deposito" in t:
        res.append("transferencia")
    return res or PAGO_TODOS[:]  # valor irreconocible: no bloquear la venta


def parsear_entrega(valor) -> list[str]:
    t = _norm(valor)
    if not t.strip() or re.search(r"ambos|ambas|todos|todas", t):
        return ENTREGA_VENDEDOR_TODOS[:]
    res = []
    if "domicilio" in t or "envio" in t:
        res.append("domicilio")
    if any(k in t for k in ("tienda", "retiro", "recoger", "recojo")):
        res.append("tienda")
    return res or ENTREGA_VENDEDOR_TODOS[:]


# ─── GET /opciones-checkout ───────────────────────────────────────────────────
@router.get("/opciones-checkout")
async def opciones_checkout(request: Request, db: Session = Depends(get_db)):
    cliente = get_cliente_opcional(request, db)
    if not cliente:
        raise HTTPException(status_code=401, detail="Debes iniciar sesión")

    cart = db.query(Carrito).options(joinedload(Carrito.items)).filter(
        Carrito.cliente_id == cliente.id
    ).first()

    vendedores = []
    if cart and cart.items:
        producto_ids = {i.producto_id for i in cart.items}
        filas = db.query(Producto.vendedor_id).filter(Producto.id.in_(producto_ids)).distinct().all()
        vendedor_ids = [f[0] for f in filas if f[0] is not None]
        if vendedor_ids:
            vendedores = db.query(Vendedor).filter(Vendedor.id.in_(vendedor_ids)).all()

    tiendas = []
    pago_set = None
    entrega_set = None
    for v in vendedores:
        pago = parsear_pago(v.tipo_pago)
        entrega = parsear_entrega(v.tipo_entrega)
        tiendas.append({
            "nombre": getattr(v, "nombre_tienda", None) or getattr(v, "nombre", None) or "Tienda",
            "pago": pago,
            "entrega": entrega,
        })
        pago_set = set(pago) if pago_set is None else pago_set & set(pago)
        entrega_set = set(entrega) if entrega_set is None else entrega_set & set(entrega)

    if pago_set is None:
        pago_set = set(PAGO_TODOS)
    if entrega_set is None:
        entrega_set = set(ENTREGA_VENDEDOR_TODOS)

    return {
        "pago": [p for p in PAGO_TODOS if p in pago_set],
        "entrega": [e for e in ENTREGA_VENDEDOR_TODOS if e in entrega_set] + ENTREGA_PLATAFORMA,
        "tiendas": tiendas,
        # True si las tiendas del carrito no comparten ningún método de pago
        "conflicto_pago": len(pago_set) == 0,
    }