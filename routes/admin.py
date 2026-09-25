# backend/routes/admin.py — VERSIÓN COMPLETA CON DATOS REALES
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text, desc, or_
from core.database import get_db
from models.admin import Admin
from models.vendedor import Vendedor
from models.producto import Producto
from models.pedido import Pedido, PedidoItem
from models.cliente import Cliente
from models.chat import ChatSala, ChatMensaje
from models.pagos import Pago
from core.security import get_password_hash, verify_password, create_access_token
from core.auth import get_current_admin, get_current_vendedor
from crud.admin import get_vendedores, toggle_activo, extender_meses
from datetime import datetime, timedelta
from typing import Optional
from dateutil.relativedelta import relativedelta

router = APIRouter()

# ── Helpers ───────────────────────────────────────────────────────────────────
def _v_dict(v: Vendedor) -> dict:
    """Serializar vendedor completo para el admin."""
    from sqlalchemy.inspection import inspect as sa_inspect
    cols = {c.key for c in sa_inspect(v).mapper.column_attrs}
    dias = None
    if getattr(v, "fecha_expiracion", None):
        delta = v.fecha_expiracion.replace(tzinfo=None) - datetime.utcnow()
        dias  = max(0, delta.days)
    return {
        "id":             v.dni,
        "dni":            v.dni,
        "rtn":            v.rtn,
        "propietario":    v.propietario,
        "nombreTienda":   v.nombre_tienda,
        "telefono":       v.telefono,
        "email":          getattr(v, "email", None),
        "ciudad":         v.municipio,
        "departamento":   v.departamento,
        "direccionTienda": v.direccion_exacta,
        "logo":           v.logo_url,
        "documento_url":  getattr(v, "documento_url", None),
        "latitud":        getattr(v, "latitud", None),
        "longitud":       getattr(v, "longitud", None),
        "google_maps_url": getattr(v, "google_maps_url", None),
        "plan":           v.plan,
        "activo":         v.activo,
        "solicitud_pendiente": v.solicitud_pendiente,
        "fechaRegistro":  v.fecha_solicitud.isoformat() if v.fecha_solicitud else None,
        "fechaExpiracion": v.fecha_expiracion.isoformat() if getattr(v,"fecha_expiracion",None) else None,
        "fechaAprobacion": v.fecha_aprobacion.isoformat() if v.fecha_aprobacion else None,
        "aprobado_por":   v.aprobado_por,
        "diasRestantes":  dias,
        "productosCount": len(v.productos) if hasattr(v, "productos") else 0,
        "visitasTotales": v.visitas_totales or 0,
        "mesesPagados":   [],  # Se carga por separado desde tabla pagos
        "ips":            v.ips or [],
    }


# ════════════════════════════════════════════════════════════════════════════
# AUTH
# ════════════════════════════════════════════════════════════════════════════
@router.post("/admin/register")
async def register_admin(request: dict, db: Session = Depends(get_db)):
    usuario  = request.get("usuario")
    password = request.get("password")
    if not usuario or not password:
        raise HTTPException(400, "Faltan usuario o contraseña")
    if db.query(Admin).filter(Admin.usuario == usuario).first():
        raise HTTPException(400, "El usuario ya existe")
    db.add(Admin(usuario=usuario, password_hash=get_password_hash(password)))
    db.commit()
    return {"msg": "Admin creado con éxito"}


@router.post("/admin/login")
async def login_admin(request: dict, db: Session = Depends(get_db)):
    usuario  = request.get("usuario")
    password = request.get("password")
    if not usuario or not password:
        raise HTTPException(400, "Faltan datos")
    admin = db.query(Admin).filter(Admin.usuario == usuario).first()
    if not admin or not verify_password(password, admin.password_hash):
        raise HTTPException(401, "Usuario o contraseña incorrecta")
    token = create_access_token({"sub": usuario, "role": "admin"})
    return {"access_token": token, "token_type": "bearer"}


# ════════════════════════════════════════════════════════════════════════════
# DASHBOARD — métricas reales
# ════════════════════════════════════════════════════════════════════════════
@router.get("/admin/dashboard")
async def dashboard_stats(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    hoy     = datetime.utcnow().date()
    semana  = datetime.utcnow() - timedelta(days=7)
    mes     = datetime.utcnow() - timedelta(days=30)

    total_vendedores  = db.query(func.count(Vendedor.dni)).scalar() or 0
    activos           = db.query(func.count(Vendedor.dni)).filter(Vendedor.activo == True).scalar() or 0
    pendientes        = db.query(func.count(Vendedor.dni)).filter(Vendedor.solicitud_pendiente == True).scalar() or 0
    total_clientes    = db.query(func.count(Cliente.id)).scalar() or 0
    total_productos   = db.query(func.count(Producto.id)).scalar() or 0
    total_pedidos     = db.query(func.count(Pedido.id)).scalar() or 0

    # Por expirar en 7 días
    pronto_expirar = db.query(func.count(Vendedor.dni)).filter(
        Vendedor.activo == True,
        Vendedor.fecha_expiracion != None,
        Vendedor.fecha_expiracion <= datetime.utcnow() + timedelta(days=7)
    ).scalar() or 0

    # Pedidos de hoy
    pedidos_hoy = db.query(func.count(Pedido.id)).filter(
        func.date(Pedido.fecha_pedido) == hoy
    ).scalar() or 0

    # Pedidos pendientes
    pedidos_pendientes = db.query(func.count(Pedido.id)).filter(
        Pedido.estado == "pendiente"
    ).scalar() or 0

    # Vendedores nuevos esta semana
    nuevos_semana = db.query(func.count(Vendedor.dni)).filter(
        Vendedor.fecha_solicitud >= semana
    ).scalar() or 0

    # Clientes nuevos este mes
    clientes_mes = db.query(func.count(Cliente.id)).filter(
        Cliente.creado_en >= mes
    ).scalar() or 0

    # Por departamento
    por_depto = db.query(
        Vendedor.departamento, func.count(Vendedor.dni).label("total")
    ).group_by(Vendedor.departamento).order_by(desc("total")).limit(8).all()

    # Registro de vendedores últimos 6 meses
    registros_mensuales = []
    for i in range(5, -1, -1):
        inicio_mes = datetime.utcnow() - relativedelta(months=i)
        inicio_mes = inicio_mes.replace(day=1, hour=0, minute=0, second=0)
        fin_mes    = (inicio_mes + relativedelta(months=1))
        cnt = db.query(func.count(Vendedor.dni)).filter(
            Vendedor.fecha_solicitud >= inicio_mes,
            Vendedor.fecha_solicitud < fin_mes
        ).scalar() or 0
        registros_mensuales.append({
            "mes":   inicio_mes.strftime("%b %Y"),
            "total": cnt,
        })

    return {
        "vendedores":        total_vendedores,
        "activos":           activos,
        "pendientes":        pendientes,
        "pronto_expirar":    pronto_expirar,
        "clientes":          total_clientes,
        "productos":         total_productos,
        "pedidos_total":     total_pedidos,
        "pedidos_hoy":       pedidos_hoy,
        "pedidos_pendientes": pedidos_pendientes,
        "nuevos_semana":     nuevos_semana,
        "clientes_mes":      clientes_mes,
        "por_departamento":  [{"departamento": r[0] or "N/A", "total": r[1]} for r in por_depto],
        "registros_mensuales": registros_mensuales,
    }


# ════════════════════════════════════════════════════════════════════════════
# SOLICITUDES
# ════════════════════════════════════════════════════════════════════════════
@router.get("/admin/solicitudes-pendientes")
async def get_solicitudes(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    rows = db.query(Vendedor).filter(
        Vendedor.solicitud_pendiente == True
    ).order_by(Vendedor.fecha_solicitud.desc()).all()
    return [_v_dict(v) for v in rows]


@router.post("/admin/aprobar-vendedor")
async def aprobar_vendedor(data: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    v = db.query(Vendedor).filter(Vendedor.dni == data["dni"]).first()
    if not v:
        raise HTTPException(404, "Vendedor no encontrado")
    v.activo            = True
    v.solicitud_pendiente = False
    v.fecha_aprobacion  = datetime.utcnow()
    v.aprobado_por      = admin.usuario
    # 3 meses gratis
    v.fecha_expiracion  = datetime.utcnow() + relativedelta(months=3)
    v.plan              = "prueba"
    db.commit()
    return {"msg": "Vendedor aprobado. 3 meses gratis activado."}


@router.post("/admin/rechazar-vendedor")
async def rechazar_vendedor(data: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    v = db.query(Vendedor).filter(Vendedor.dni == data["dni"]).first()
    if not v:
        raise HTTPException(404, "Vendedor no encontrado")
    db.delete(v)
    db.commit()
    return {"msg": f"Vendedor rechazado. Motivo: {data.get('motivo','Sin motivo')}"}


# ════════════════════════════════════════════════════════════════════════════
# VENDEDORES
# ════════════════════════════════════════════════════════════════════════════
@router.get("/vendedores")
async def list_vendedores(
    search: Optional[str] = None,
    departamento: Optional[str] = None,
    plan: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    q = db.query(Vendedor)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(
            Vendedor.nombre_tienda.ilike(s),
            Vendedor.propietario.ilike(s),
            Vendedor.dni.ilike(s),
            Vendedor.telefono.ilike(s)
        ))
    if departamento and departamento != "todos":
        q = q.filter(Vendedor.departamento == departamento)
    if plan and plan != "todos":
        q = q.filter(Vendedor.plan == plan)
    return [_v_dict(v) for v in q.order_by(Vendedor.fecha_solicitud.desc()).limit(200).all()]


@router.put("/vendedores/{dni}/toggle")
async def toggle_vendedor(dni: str, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    v = db.query(Vendedor).filter(Vendedor.dni == dni).first()
    if not v:
        raise HTTPException(404, "Vendedor no encontrado")
    v.activo = not v.activo
    # Al activar manualmente, limpiar solicitud_pendiente para que el login no bloquee
    if v.activo:
        v.solicitud_pendiente = False
    db.commit()
    return {"activo": v.activo, "solicitud_pendiente": v.solicitud_pendiente}


@router.post("/vendedores/{dni}/extender")
async def extender_plan(dni: str, data: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Registrar pago en tabla pagos y extender fecha_expiracion del vendedor."""
    v = db.query(Vendedor).filter(Vendedor.dni == dni).first()
    if not v:
        raise HTTPException(404, "Vendedor no encontrado")

    meses  = int(data.get("meses", 1))
    plan   = data.get("plan", "basico")
    metodo = (data.get("metodo_pago") or data.get("metodo") or "efectivo").lower().replace(" ","_")
    emisor = data.get("emisor") or admin.usuario
    monto  = float(data.get("monto", 0))

    # Mapear método al CHECK constraint de la BD
    metodo_map = {
        "efectivo":             "efectivo",
        "transferencia":        "transferencia",
        "transferencia_bancaria": "transferencia",
        "tigo_money":           "tigo_money",
        "tigo":                 "tigo_money",
        "banco":                "banco",
        "tarjeta":              "tarjeta",
        "tarjeta_de_credito":   "tarjeta",
    }
    metodo = metodo_map.get(metodo, "efectivo")

    # Mapear plan al CHECK constraint (basico|pro|premium|prueba)
    plan_map = {
        "basico": "basico", "l300": "basico", "300": "basico",
        "pro":    "pro",    "l500": "pro",    "500": "pro",
        "premium":"premium","l800": "premium","800": "premium",
        "prueba": "prueba",
    }
    plan = plan_map.get(plan.lower(), "basico")

    base      = datetime.utcnow()
    inicio    = max(v.fecha_expiracion.replace(tzinfo=None) if getattr(v,"fecha_expiracion",None) else base, base)
    nueva_exp = inicio + relativedelta(months=meses)

    # Insertar en tabla pagos
    nuevo_pago = Pago(
        vendor_dni            = dni,
        plan                  = plan,
        meses_pagados         = meses,
        monto                 = round(monto, 2),
        metodo_pago           = metodo,
        aprobado              = True,
        fecha_pago            = base.date(),
        fecha_aprobacion      = base,
        fecha_inicio_periodo  = inicio,
        fecha_fin_periodo     = nueva_exp,
        emisor                = emisor,
    )
    db.add(nuevo_pago)

    # Actualizar vendedor
    v.fecha_expiracion = nueva_exp
    v.plan             = plan
    v.activo           = True
    v.fecha_pago       = base

    db.commit()
    return {
        "msg":           f"Plan extendido {meses} mes(es). Expira: {nueva_exp.strftime('%d/%m/%Y')}",
        "nueva_expiracion": nueva_exp.isoformat(),
        "plan":          plan,
    }


@router.delete("/vendedores/{dni}")
async def eliminar_vendedor(dni: str, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    v = db.query(Vendedor).filter(Vendedor.dni == dni).first()
    if not v:
        raise HTTPException(404, "Vendedor no encontrado")
    db.delete(v)
    db.commit()
    return {"msg": "Vendedor eliminado"}


# ════════════════════════════════════════════════════════════════════════════
# CLIENTES
# ════════════════════════════════════════════════════════════════════════════
@router.get("/admin/clientes")
async def list_clientes(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    q = db.query(Cliente)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(
            Cliente.nombres.ilike(s),
            Cliente.apellidos.ilike(s),
            Cliente.telefono.ilike(s),
            Cliente.email.ilike(s)
        ))
    clientes = q.order_by(desc(Cliente.creado_en)).limit(200).all()
    result = []
    for c in clientes:
        pedidos_count = db.query(func.count(Pedido.id)).filter(Pedido.cliente_id == c.id).scalar() or 0
        result.append({
            "id": c.id, "nombres": c.nombres, "apellidos": c.apellidos,
            "telefono": c.telefono, "email": c.email,
            "departamento": c.departamento, "municipio": c.municipio,
            "creado_en": c.creado_en.isoformat() if c.creado_en else None,
            "pedidos_count": pedidos_count,
        })
    return result


# ════════════════════════════════════════════════════════════════════════════
# PEDIDOS
# ════════════════════════════════════════════════════════════════════════════
@router.get("/admin/pedidos")
async def list_pedidos(
    estado: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    q = db.query(Pedido)
    if estado:
        q = q.filter(Pedido.estado == estado)
    pedidos = q.order_by(desc(Pedido.fecha_pedido)).limit(200).all()
    result  = []
    for p in pedidos:
        cliente  = db.query(Cliente).filter(Cliente.id == p.cliente_id).first()
        vendedor = db.query(Vendedor).filter(Vendedor.dni == p.vendedor_id).first()
        result.append({
            "id":          p.id,
            "estado":      p.estado,
            "total":       float(p.total),
            "metodo_pago": p.metodo_pago,
            "tipo_entrega": p.tipo_entrega,
            "es_digital":  getattr(p, "es_digital", False),
            "fecha":       p.fecha_pedido.isoformat() if p.fecha_pedido else None,
            "cliente":     f"{cliente.nombres} {cliente.apellidos}" if cliente else "N/A",
            "vendedor":    vendedor.nombre_tienda if vendedor else "N/A",
            "items_count": len(p.items),
        })
    return result


# ════════════════════════════════════════════════════════════════════════════
# PRODUCTOS
# ════════════════════════════════════════════════════════════════════════════
@router.get("/admin/productos")
async def list_productos(
    search: Optional[str] = None,
    categoria: Optional[str] = None,
    tipo: Optional[str] = None,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    q = db.query(Producto)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(or_(Producto.nombre.ilike(s), Producto.categoria.ilike(s)))
    if categoria:
        q = q.filter(Producto.categoria == categoria)
    if tipo:
        q = q.filter(Producto.tipo == tipo)
    productos = q.order_by(desc(Producto.creado_en)).limit(200).all()
    result = []
    for p in productos:
        vendedor = db.query(Vendedor).filter(Vendedor.dni == p.vendedor_id).first()
        foto = p.fotos[0].url if p.fotos else None
        result.append({
            "id":         str(p.id),
            "nombre":     p.nombre,
            "categoria":  p.categoria,
            "tipo":       p.tipo,
            "precio":     float(p.precio),
            "stock":      p.stock,
            "activo":     p.activo,
            "destacado":  p.destacado,
            "ventas":     p.ventas_count or 0,
            "vistas":     p.vistas_count or 0,
            "creado_en":  p.creado_en.isoformat() if p.creado_en else None,
            "vendedor":   vendedor.nombre_tienda if vendedor else "N/A",
            "foto":       foto,
        })
    return result


@router.put("/admin/productos/{producto_id}/toggle")
async def toggle_producto(producto_id: str, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    p = db.query(Producto).filter(Producto.id == producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    p.activo = not p.activo
    db.commit()
    return {"activo": p.activo}


@router.put("/admin/productos/{producto_id}/destacado")
async def toggle_destacado(producto_id: str, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    p = db.query(Producto).filter(Producto.id == producto_id).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    p.destacado = not p.destacado
    db.commit()
    return {"destacado": p.destacado}


# ════════════════════════════════════════════════════════════════════════════
# PAGOS (historial de pagos de vendedores)
# ════════════════════════════════════════════════════════════════════════════
@router.get("/admin/pagos")
async def list_pagos(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Lista todos los pagos desde la tabla pagos, ordenados por fecha desc."""
    rows = db.query(Pago).order_by(desc(Pago.created_at)).limit(500).all()
    result = []
    for p in rows:
        v = db.query(Vendedor).filter(Vendedor.dni == p.vendor_dni).first()
        result.append({
            "id":              p.id,
            "vendedor_dni":    p.vendor_dni,
            "vendedor_nombre": v.nombre_tienda if v else "N/A",
            "propietario":     v.propietario   if v else "N/A",
            "plan":            p.plan,
            "meses":           p.meses_pagados,
            "monto":           float(p.monto),
            "metodo":          p.metodo_pago,
            "emisor":          p.emisor or "N/A",
            "aprobado":        p.aprobado,
            "fecha_pago":      p.fecha_pago.isoformat() if p.fecha_pago else None,
            "inicio":          p.fecha_inicio_periodo.isoformat() if p.fecha_inicio_periodo else None,
            "fin":             p.fecha_fin_periodo.isoformat()    if p.fecha_fin_periodo    else None,
            "creado_en":       p.created_at.isoformat()           if p.created_at           else None,
        })
    return result


@router.post("/pagos")
async def registrar_pago_legacy(data: dict, db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """Compatibilidad con la página de pagos anterior."""
    dni   = data.get("vendedor_id") or data.get("dni")
    meses = int(data.get("meses", 1))
    plan  = "L" + str(data.get("plan", "299")).replace("L","")
    return await extender_plan(dni, {
        "meses": meses, "plan": plan,
        "monto": data.get("monto", 0),
        "metodo_pago": data.get("metodo", "Efectivo"),
        "emisor": data.get("emisor", "Admin"),
    }, db=db, admin=admin)


# ════════════════════════════════════════════════════════════════════════════
# ESTADÍSTICAS AVANZADAS
# ════════════════════════════════════════════════════════════════════════════


@router.get("/admin/vendedor/{dni}/pedidos-completados")
async def pedidos_completados_vendedor(
    dni: str,
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin)
):
    """
    Pedidos con estado 'entregado' de un vendedor específico.
    Incluye total de ventas, cliente, ítems y método de pago.
    """
    pedidos = db.query(Pedido).filter(
        Pedido.vendedor_id == dni,
        Pedido.estado == "entregado",
    ).order_by(desc(Pedido.fecha_entrega_real)).limit(100).all()

    result = []
    for p in pedidos:
        cliente = db.query(Cliente).filter(Cliente.id == p.cliente_id).first()
        result.append({
            "id":            p.id,
            "total":         float(p.total),
            "metodo_pago":   p.metodo_pago,
            "fecha_entrega": p.fecha_entrega_real.isoformat() if p.fecha_entrega_real else None,
            "items_count":   len(p.items),
            "cliente":       f"{cliente.nombres} {cliente.apellidos}" if cliente else "Cliente",
            "es_digital":    getattr(p, "es_digital", False),
        })
    return result

@router.get("/admin/estadisticas")
async def estadisticas(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    # Ingresos desde tabla pagos
    from sqlalchemy import cast, Numeric as SANumeric
    ingresos_total = float(db.query(func.coalesce(func.sum(Pago.monto), 0)).scalar() or 0)
    mes_inicio     = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0)
    ingresos_mes   = float(
        db.query(func.coalesce(func.sum(Pago.monto), 0))
        .filter(Pago.created_at >= mes_inicio)
        .scalar() or 0
    )

    # Ventas por mes (pedidos)
    ventas_mensuales = []
    for i in range(5, -1, -1):
        inicio = (datetime.utcnow() - relativedelta(months=i)).replace(day=1,hour=0,minute=0,second=0)
        fin    = inicio + relativedelta(months=1)
        cnt    = db.query(func.count(Pedido.id)).filter(
            Pedido.fecha_pedido >= inicio, Pedido.fecha_pedido < fin
        ).scalar() or 0
        ventas_mensuales.append({"mes": inicio.strftime("%b"), "pedidos": cnt})

    # Métodos de pago pedidos
    metodos = db.query(Pedido.metodo_pago, func.count(Pedido.id).label("c"))\
        .group_by(Pedido.metodo_pago).all()

    # Categorías de productos
    cats = db.query(Producto.categoria, func.count(Producto.id).label("c"))\
        .group_by(Producto.categoria).order_by(desc("c")).limit(8).all()

    # Vendedores por plan
    planes = db.query(Vendedor.plan, func.count(Vendedor.dni).label("c"))\
        .filter(Vendedor.activo == True)\
        .group_by(Vendedor.plan).all()

    return {
        "ingresos_total":    round(ingresos_total, 2),
        "ingresos_mes":      round(ingresos_mes, 2),
        "ventas_mensuales":  ventas_mensuales,
        "metodos_pago":      [{"metodo": r[0] or "N/A", "total": r[1]} for r in metodos],
        "categorias":        [{"nombre": r[0] or "Otra", "total": r[1]} for r in cats],
        "planes":            [{"plan": r[0] or "prueba", "total": r[1]} for r in planes],
    }


# ════════════════════════════════════════════════════════════════════════════
# PLANES Y RESTRICCIONES (referencia para el backend)
# ════════════════════════════════════════════════════════════════════════════
RESTRICCIONES_PLAN = {
    "prueba":  {"max_productos": 30,      "max_destacados": 0,      "duracion_meses": 3},
    "basico":  {"max_productos": 30,     "max_destacados": 2,      "duracion_meses": None},
    "pro":     {"max_productos": 150,    "max_destacados": 10,     "duracion_meses": None},
    "premium": {"max_productos": 999999, "max_destacados": 999999, "duracion_meses": None},
}


@router.get("/admin/planes")
async def get_planes():
    """Devuelve los planes disponibles con precios y restricciones."""
    return {
        "prueba": {
            "nombre": "Prueba Gratuita", "precio": 0,   "duracion": "3 meses",
            "max_productos": 30, "max_destacados": 5,
            "descripcion": "Para comenzar. 3 meses sin costo.",
        },
        "basico": {
            "nombre": "Básico",  "precio": 300, "duracion": "mensual",
            "max_productos": 30, "max_destacados": 5,
            "descripcion": "Para tiendas pequeñas que quieren crecer.",
        },
        "pro": {
            "nombre": "Pro",     "precio": 500, "duracion": "mensual",
            "max_productos": 150, "max_destacados": 15,
            "descripcion": "Para tiendas en crecimiento con más visibilidad.",
        },
        "premium": {
            "nombre": "Premium", "precio": 800, "duracion": "mensual",
            "max_productos": 999999, "max_destacados": 999999,
            "descripcion": "Sin límites. Todo incluido.",
        },
    }


@router.post("/admin/desactivar-expirados")
async def desactivar_expirados(db: Session = Depends(get_db), admin=Depends(get_current_admin)):
    """
    Desactiva automáticamente vendedores con suscripción vencida.
    Llamar desde un scheduler (APScheduler) cada hora.
    """
    ahora    = datetime.utcnow()
    vencidos = db.query(Vendedor).filter(
        Vendedor.activo == True,
        Vendedor.fecha_expiracion != None,
        Vendedor.fecha_expiracion < ahora,
    ).all()

    count = 0
    for v in vencidos:
        v.activo = False
        count += 1

    db.commit()
    return {"desactivados": count, "timestamp": ahora.isoformat()}


@router.get("/vendedor/plan-restricciones")
async def mis_restricciones(vendedor: Vendedor = Depends(get_current_vendedor)):
    """El vendedor consulta sus límites actuales según su plan."""
    plan = vendedor.plan or "prueba"
    r    = RESTRICCIONES_PLAN.get(plan, RESTRICCIONES_PLAN["prueba"])
    return {
        "plan":            plan,
        "activo":          vendedor.activo,
        "fecha_expiracion": vendedor.fecha_expiracion.isoformat() if getattr(vendedor,"fecha_expiracion",None) else None,
        "max_productos":   r["max_productos"],
        "max_destacados":  r["max_destacados"],
        "puede_destacar":  r["max_destacados"] > 0,
        "es_verificado":   plan in ("pro","premium"),
        "soporte_prioritario": plan in ("pro","premium"),
        "prioridad_catalogo": plan == "premium",
    }