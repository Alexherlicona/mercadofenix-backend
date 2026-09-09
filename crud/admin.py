# backend/crud/admin.py (nuevo archivo completo)
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models.vendedor import Vendedor
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import List, Optional

def get_vendedores(
    db: Session,
    search: Optional[str] = None,
    departamento: Optional[str] = None,
    plan: Optional[str] = None,
    limit: int = 100
) -> List[Vendedor]:
    query = db.query(Vendedor)

    if search:
        s = f"%{search.lower()}%"
        query = query.filter(
            or_(
                Vendedor.nombre_tienda.ilike(s),
                Vendedor.dni.ilike(s),
                Vendedor.propietario.ilike(s),
                Vendedor.telefono.ilike(s)
            )
        )

    if departamento and departamento != "todos":
        query = query.filter(Vendedor.departamento == departamento)

    if plan and plan != "todos":
        query = query.filter(Vendedor.plan == plan)

    return query.limit(limit).all()

def toggle_activo(db: Session, dni: str) -> Optional[Vendedor]:
    vendedor = db.query(Vendedor).filter(Vendedor.dni == dni).first()
    if not vendedor:
        return None
    vendedor.activo = not vendedor.activo
    db.commit()
    db.refresh(vendedor)
    return vendedor

def extender_meses(db: Session, dni: str, meses: int, nuevo_plan: str) -> Optional[Vendedor]:
    vendedor = db.query(Vendedor).filter(Vendedor.dni == dni).first()
    if not vendedor or meses <= 0:
        return None

    fecha_actual = datetime.utcnow()
    fecha_inicio = max(vendedor.fecha_expiracion or fecha_actual, fecha_actual)
    nueva_expiracion = fecha_inicio + relativedelta(months=meses)

    nuevo_pago = {
        "inicio": fecha_inicio.isoformat(),
        "fin": nueva_expiracion.isoformat(),
        "plan": nuevo_plan
    }

    vendedor.meses_pagados.append(nuevo_pago)
    vendedor.fecha_expiracion = nueva_expiracion
    vendedor.plan = nuevo_plan
    vendedor.activo = True
    vendedor.fecha_pago = fecha_actual

    db.commit()
    db.refresh(vendedor)
    return vendedor