# backend/crud/pedidos.py
from sqlalchemy.orm import Session
from models.pedido import Pedido, PedidoItem
from models.direccion import Direccion
from models.carrito import CarritoItem
from models.producto import Producto
from models.chat import ChatSala
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List


def crear_pedidos_por_vendedor(
    db: Session,
    cliente_id: int,
    direccion_id: Optional[int],
    direccion_alternativa: Optional[str],
    items_data: list,
    tipo_entrega: str,
    metodo_pago: str,
    nota_cliente: Optional[str] = None,
    es_digital: bool = False,          # ← NUEVO
) -> List[Pedido]:
    """
    Divide los items por vendedor y crea UN PEDIDO POR CADA TIENDA.
    Para productos digitales: sin costo de envío, descarga pendiente de habilitación.
    """
    # 1. Agrupar items por vendedor
    items_por_vendedor: dict = {}
    for item in items_data:
        producto = db.query(Producto).filter(Producto.id == item["producto_id"]).first()
        if not producto:
            continue
        vendedor_dni = producto.vendedor_id
        items_por_vendedor.setdefault(vendedor_dni, []).append(item)

    if not items_por_vendedor:
        raise ValueError("Ninguno de los productos del pedido existe")

    pedidos_creados: List[Pedido] = []

    for vendedor_dni, items_vendedor in items_por_vendedor.items():
        subtotal = sum(
            Decimal(str(item["precio_unitario"])) * item["cantidad"]
            for item in items_vendedor
        )

        # Productos digitales: sin costo de envío
        costo_envio = Decimal("0.00") if es_digital else (
            Decimal("50.00") if tipo_entrega == "domicilio" else Decimal("0.00")
        )
        total = subtotal + costo_envio

        pedido = Pedido(
            cliente_id=cliente_id,
            vendedor_id=vendedor_dni,
            direccion_id=direccion_id,
            direccion_alternativa=direccion_alternativa,
            estado="pendiente",
            tipo_entrega=tipo_entrega,
            metodo_pago=metodo_pago,
            subtotal=subtotal,
            costo_envio=costo_envio,
            total=total,
            nota_cliente=nota_cliente,
            fecha_pedido=datetime.utcnow(),
            es_digital=es_digital,              # ← NUEVO
            descarga_habilitada=False,           # ← NUEVO
        )
        db.add(pedido)
        db.flush()

        for item in items_vendedor:
            subtotal_item = Decimal(str(item["precio_unitario"])) * item["cantidad"]
            db.add(PedidoItem(
                pedido_id=pedido.id,
                producto_id=item["producto_id"],
                nombre_producto=item["nombre_producto"],
                precio_unitario=Decimal(str(item["precio_unitario"])),
                cantidad=item["cantidad"],
                subtotal=subtotal_item,
                color=item.get("color"),
                talla=item.get("talla"),
            ))

        # Sala de chat automática
        sala = ChatSala(
            pedido_id=pedido.id,
            cliente_id=cliente_id,
            vendedor_id=vendedor_dni,
        )
        db.add(sala)
        pedidos_creados.append(pedido)

    db.commit()
    for p in pedidos_creados:
        db.refresh(p)

    return pedidos_creados


def obtener_pedido(db: Session, pedido_id: int, cliente_id: int) -> Optional[Pedido]:
    return db.query(Pedido).filter(
        Pedido.id == pedido_id,
        Pedido.cliente_id == cliente_id
    ).first()


def obtener_pedidos_cliente(db: Session, cliente_id: int, limit: int = 50) -> list:
    return db.query(Pedido).filter(
        Pedido.cliente_id == cliente_id,
        Pedido.activo == True
    ).order_by(Pedido.fecha_pedido.desc()).limit(limit).all()


def actualizar_estado_pedido(
    db: Session, pedido_id: int,
    nuevo_estado: str,
    nota_vendedor: Optional[str] = None
) -> Optional[Pedido]:
    pedido = db.query(Pedido).filter(Pedido.id == pedido_id).first()
    if not pedido:
        return None
    pedido.estado = nuevo_estado
    if nota_vendedor:
        pedido.nota_vendedor = nota_vendedor
    if nuevo_estado == "confirmado":
        pedido.fecha_confirmacion = datetime.utcnow()
    elif nuevo_estado == "entregado":
        pedido.fecha_entrega_real = datetime.utcnow()
    db.commit()
    db.refresh(pedido)
    return pedido