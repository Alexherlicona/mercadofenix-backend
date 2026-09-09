# backend/routes/pedidos.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from core.database import get_db
from core.auth import get_current_user, get_current_vendedor
from models.cliente import Cliente
from models.pedido import Pedido
from models.direccion import Direccion
from models.producto import Producto
from schemas import PedidoCreate, PedidoOut, PedidoUpdateEstado
from crud.pedidos import crear_pedidos_por_vendedor, obtener_pedido, obtener_pedidos_cliente, actualizar_estado_pedido
from typing import List
from datetime import datetime, timedelta

router = APIRouter(prefix="/api/pedidos", tags=["pedidos"])


# ── Helper: detectar si todos los items de un pedido son digitales ────────────
def _todos_digitales(items_data: list, db: Session) -> bool:
    for item in items_data:
        p = db.query(Producto).filter(Producto.id == item["producto_id"]).first()
        if not p or p.tipo != "digital":
            return False
    return True


# ==================== CREAR PEDIDO ====================
@router.post("/crear")
async def crear_nuevo_pedido(
    pedido_data: PedidoCreate,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if not pedido_data.items or len(pedido_data.items) == 0:
        raise HTTPException(status_code=400, detail="El pedido debe tener al menos un item")

    # Preparar items
    items_para_pedido = [
        {
            "producto_id":    str(item.producto_id),
            "nombre_producto": item.nombre_producto,
            "precio_unitario": item.precio_unitario,
            "cantidad":        item.cantidad,
            "color":           item.color,
            "talla":           item.talla,
        }
        for item in pedido_data.items
    ]

    es_digital = _todos_digitales(items_para_pedido, db)

    # Productos digitales no necesitan dirección física
    if not es_digital:
        if not pedido_data.direccion_id and not pedido_data.direccion_alternativa:
            raise HTTPException(
                status_code=400,
                detail="Debes seleccionar una dirección o escribir una nueva"
            )
        if pedido_data.direccion_id:
            direccion = db.query(Direccion).filter(
                Direccion.id == pedido_data.direccion_id,
                Direccion.cliente_id == current_user.id
            ).first()
            if not direccion:
                raise HTTPException(status_code=404, detail="Dirección no encontrada")

    # tipo_entrega para digitales es "digital"
    tipo_entrega = "digital" if es_digital else pedido_data.tipo_entrega
    if not es_digital and tipo_entrega not in ["domicilio", "tienda", "oficina_fenix"]:
        raise HTTPException(status_code=400, detail="Tipo de entrega inválido")

    if pedido_data.metodo_pago not in ["efectivo", "transferencia", "tigo_money"]:
        raise HTTPException(status_code=400, detail="Método de pago inválido")

    try:
        pedidos = crear_pedidos_por_vendedor(
            db=db,
            cliente_id=current_user.id,
            direccion_id=pedido_data.direccion_id if not es_digital else None,
            direccion_alternativa=pedido_data.direccion_alternativa if not es_digital else None,
            items_data=items_para_pedido,
            tipo_entrega=tipo_entrega,
            metodo_pago=pedido_data.metodo_pago,
            nota_cliente=pedido_data.nota_cliente,
            es_digital=es_digital,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear pedido: {str(e)}")

    total_general = sum(float(p.total) for p in pedidos)

    return {
        "mensaje":      "Pedido creado exitosamente",
        "pedido_id":    pedidos[0].id,
        "pedidos_ids":  [p.id for p in pedidos],
        "num_pedidos":  len(pedidos),
        "total":        total_general,
        "estado":       "pendiente",
        "es_digital":   es_digital,
    }


# ==================== OBTENER PEDIDOS DEL CLIENTE ====================
@router.get("/mis-pedidos")
async def mis_pedidos(
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pedidos = obtener_pedidos_cliente(db, current_user.id)
    result  = []
    for p in pedidos:
        result.append({
            "id":                  p.id,
            "estado":              p.estado,
            "tipo_entrega":        p.tipo_entrega,
            "metodo_pago":         p.metodo_pago,
            "subtotal":            float(p.subtotal),
            "total":               float(p.total),
            "es_digital":          getattr(p, "es_digital", False),
            "descarga_habilitada": getattr(p, "descarga_habilitada", False),
            "descarga_token":      p.descarga_token if getattr(p, "descarga_habilitada", False) else None,
            "fecha_pedido":        p.fecha_pedido,
            "fecha_entrega_real":  p.fecha_entrega_real,
            "items_count":         len(p.items),
        })
    return {"pedidos": result}


# ==================== DETALLE DE UN PEDIDO (cliente) ====================
@router.get("/{pedido_id}")
async def obtener_detalle_pedido(
    pedido_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    pedido = obtener_pedido(db, pedido_id, current_user.id)
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    items = [
        {
            "id": item.id,
            "producto_id":     str(item.producto_id),
            "nombre_producto": item.nombre_producto,
            "precio_unitario": float(item.precio_unitario),
            "cantidad":        item.cantidad,
            "subtotal":        float(item.subtotal),
            "color":           item.color,
            "talla":           item.talla,
        }
        for item in pedido.items
    ]

    direccion_info = None
    if pedido.direccion_id:
        d = db.query(Direccion).filter(Direccion.id == pedido.direccion_id).first()
        if d:
            direccion_info = {
                "nombre": d.nombre_direccion, "departamento": d.departamento,
                "municipio": d.municipio, "direccion_exacta": d.direccion_exacta,
                "telefono": d.telefono_contacto,
            }

    return {
        "id":                  pedido.id,
        "estado":              pedido.estado,
        "tipo_entrega":        pedido.tipo_entrega,
        "metodo_pago":         pedido.metodo_pago,
        "subtotal":            float(pedido.subtotal),
        "costo_envio":         float(pedido.costo_envio),
        "total":               float(pedido.total),
        "items":               items,
        "es_digital":          getattr(pedido, "es_digital", False),
        "descarga_habilitada": getattr(pedido, "descarga_habilitada", False),
        "descarga_token":      pedido.descarga_token if getattr(pedido, "descarga_habilitada", False) else None,
        "direccion":           pedido.direccion_alternativa or direccion_info or "No especificada",
        "nota_cliente":        pedido.nota_cliente,
        "nota_vendedor":       pedido.nota_vendedor,
        "fecha_pedido":        pedido.fecha_pedido,
        "fecha_confirmacion":  pedido.fecha_confirmacion,
        "fecha_entrega_real":  pedido.fecha_entrega_real,
    }


# ==================== PEDIDOS DEL VENDEDOR ====================
@router.get("/vendedor/pendientes")
async def pedidos_pendientes_vendedor(
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    pedidos = db.query(Pedido).filter(
        Pedido.vendedor_id == current_vendedor.dni,
        Pedido.estado.in_(["pendiente", "confirmado", "en_preparacion"])
    ).order_by(Pedido.fecha_pedido.desc()).all()

    return {
        "pedidos": [
            {
                "id":          p.id,
                "cliente_id":  p.cliente_id,
                "estado":      p.estado,
                "total":       float(p.total),
                "fecha":       p.fecha_pedido,
                "items_count": len(p.items),
                "es_digital":  getattr(p, "es_digital", False),
            }
            for p in pedidos
        ]
    }


@router.get("/vendedor/detalle/{pedido_id}")
async def obtener_detalle_pedido_vendedor(
    pedido_id: int,
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    from models.cliente import Cliente as ClienteModel

    pedido = db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.vendedor_id == current_vendedor.dni
    ).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")

    cliente = db.query(ClienteModel).filter(ClienteModel.id == pedido.cliente_id).first()
    cliente_info = None
    if cliente:
        cliente_info = {
            "nombres":   cliente.nombres, "apellidos": cliente.apellidos,
            "telefono":  cliente.telefono, "email":    cliente.email,
        }

    direccion_info = None
    if pedido.direccion_id:
        d = db.query(Direccion).filter(Direccion.id == pedido.direccion_id).first()
        if d:
            direccion_info = {
                "nombre": d.nombre_direccion, "departamento": d.departamento,
                "municipio": d.municipio, "direccion_exacta": d.direccion_exacta,
                "referencia": d.referencia, "telefono": d.telefono_contacto,
            }

    items = [
        {
            "id": item.id, "producto_id": str(item.producto_id),
            "nombre_producto": item.nombre_producto,
            "precio_unitario": float(item.precio_unitario),
            "cantidad": item.cantidad, "subtotal": float(item.subtotal),
            "color": item.color, "talla": item.talla,
        }
        for item in pedido.items
    ]

    return {
        "id":                     pedido.id,
        "estado":                 pedido.estado,
        "tipo_entrega":           pedido.tipo_entrega,
        "metodo_pago":            pedido.metodo_pago,
        "subtotal":               float(pedido.subtotal),
        "costo_envio":            float(pedido.costo_envio),
        "total":                  float(pedido.total),
        "items":                  items,
        "cliente":                cliente_info,
        "direccion_guardada":     direccion_info,
        "direccion_alternativa":  pedido.direccion_alternativa,
        "nota_cliente":           pedido.nota_cliente,
        "nota_vendedor":          pedido.nota_vendedor,
        "es_digital":             getattr(pedido, "es_digital", False),
        "descarga_habilitada":    getattr(pedido, "descarga_habilitada", False),
        "descarga_token":         pedido.descarga_token if getattr(pedido, "descarga_habilitada", False) else None,
        "fecha_pedido":           pedido.fecha_pedido,
        "fecha_confirmacion":     pedido.fecha_confirmacion,
        "fecha_entrega_estimada": pedido.fecha_entrega_estimada,
        "fecha_entrega_real":     pedido.fecha_entrega_real,
    }


@router.put("/{pedido_id}/estado")
async def actualizar_estado(
    pedido_id: int,
    update_data: PedidoUpdateEstado,
    current_vendedor = Depends(get_current_vendedor),
    db: Session = Depends(get_db)
):
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if pedido.vendedor_id != current_vendedor.dni:
        raise HTTPException(status_code=403, detail="No tienes permiso")

    estados_validos = ["pendiente","confirmado","en_preparacion","en_camino","entregado","cancelado"]
    if update_data.estado not in estados_validos:
        raise HTTPException(status_code=400, detail=f"Estado inválido")

    pedido = actualizar_estado_pedido(db, pedido_id, update_data.estado, update_data.nota_vendedor)
    return {"mensaje": "Estado actualizado", "pedido_id": pedido.id, "nuevo_estado": pedido.estado}


# ==================== BORRADO ====================
@router.delete("/{pedido_id}/cliente")
async def borrar_pedido_cliente(pedido_id: int, current_user: Cliente = Depends(get_current_user), db: Session = Depends(get_db)):
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id, Pedido.cliente_id == current_user.id).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if pedido.estado not in ("entregado", "cancelado"):
        raise HTTPException(status_code=400, detail="Solo puedes eliminar pedidos entregados o cancelados")
    pedido.activo = False
    db.commit()
    return {"mensaje": "Pedido eliminado de tu historial"}


@router.delete("/{pedido_id}/vendedor")
async def borrar_pedido_vendedor(pedido_id: int, current_vendedor = Depends(get_current_vendedor), db: Session = Depends(get_db)):
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id, Pedido.vendedor_id == current_vendedor.dni).first()
    if not pedido:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    if pedido.estado not in ("entregado", "cancelado"):
        raise HTTPException(status_code=400, detail="Solo puedes eliminar pedidos entregados o cancelados")
    pedido.activo = False
    db.commit()
    return {"mensaje": "Pedido eliminado de tu historial"}


@router.delete("/admin/limpiar-entregados")
async def limpiar_pedidos_entregados(db: Session = Depends(get_db)):
    limite   = datetime.utcnow() - timedelta(days=7)
    pedidos  = db.query(Pedido).filter(Pedido.activo == True, Pedido.estado.in_(["entregado","cancelado"]), Pedido.fecha_entrega_real <= limite).all()
    pedidos2 = db.query(Pedido).filter(Pedido.activo == True, Pedido.estado == "cancelado", Pedido.fecha_entrega_real == None, Pedido.fecha_pedido <= limite).all()
    total    = len(pedidos) + len(pedidos2)
    for p in pedidos + pedidos2:
        p.activo = False
    db.commit()
    return {"mensaje": f"{total} pedidos archivados automáticamente"}