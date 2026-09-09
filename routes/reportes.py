# backend/routes/reportes.py
# Agregar en main.py:
#   from routes.reportes import router as reportes_router
#   app.include_router(reportes_router, prefix="/api")
#
# NO modifica ningún archivo existente.

import os, shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from typing import Optional
from datetime import datetime

from core.database import get_db
from core.auth import get_current_user, get_current_vendedor, get_current_admin
from models.reporte import Reporte, Sugerencia
from models.vendedor import Vendedor
from models.cliente import Cliente

router = APIRouter()

UPLOAD_DIR = "public/evidencias"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── helpers ───────────────────────────────────────────────────────────────────
def _reporte_dict(r: Reporte) -> dict:
    return {
        "id":             r.id,
        "cliente_id":     r.cliente_id,
        "nombre_reporter":r.nombre_reporter,
        "email_reporter": r.email_reporter,
        "tipo_reporte":   r.tipo_reporte,
        "vendedor_dni":   r.vendedor_dni,
        "vendedor_nombre":r.vendedor_nombre,
        "pedido_id":      r.pedido_id,
        "titulo":         r.titulo,
        "descripcion":    r.descripcion,
        "evidencia_url":  r.evidencia_url,
        "estado":         r.estado,
        "prioridad":      r.prioridad,
        "nota_admin":     r.nota_admin,
        "creado_en":      r.creado_en.isoformat() if r.creado_en else None,
        "actualizado_en": r.actualizado_en.isoformat() if r.actualizado_en else None,
    }

def _sugerencia_dict(s: Sugerencia) -> dict:
    return {
        "id":            s.id,
        "vendedor_dni":  s.vendedor_dni,
        "nombre_tienda": s.nombre_tienda,
        "tipo":          s.tipo,
        "titulo":        s.titulo,
        "descripcion":   s.descripcion,
        "estado":        s.estado,
        "prioridad":     s.prioridad,
        "nota_admin":    s.nota_admin,
        "creado_en":     s.creado_en.isoformat() if s.creado_en else None,
        "actualizado_en":s.actualizado_en.isoformat() if s.actualizado_en else None,
    }


# ════════════════════════════════════════════════════════════════════════════
# REPORTES — cliente
# ════════════════════════════════════════════════════════════════════════════

@router.post("/reportes")
async def crear_reporte(
    request:      Request,
    tipo_reporte: str            = Form(...),
    vendedor_dni: Optional[str]  = Form(None),
    pedido_id:    Optional[int]  = Form(None),
    titulo:       str            = Form(...),
    descripcion:  str            = Form(...),
    nombre:       Optional[str]  = Form(None),
    email:        Optional[str]  = Form(None),
    evidencia:    Optional[UploadFile] = File(None),
    db:           Session        = Depends(get_db),
):
    """
    Endpoint público — cliente registrado o anónimo puede reportar.
    Si hay token válido lo usa para obtener datos del cliente.
    """
    # Intentar auth opcional
    cliente_id    = None
    nombre_final  = (nombre or "").strip() or "Anónimo"
    email_final   = (email  or "").strip() or None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            from core.auth import oauth2_scheme
            from core.security import SECRET_KEY, ALGORITHM
            from jose import jwt, JWTError
            token   = auth_header.split(" ")[1]
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            tel     = payload.get("sub")
            if tel:
                c = db.query(Cliente).filter(Cliente.telefono == tel).first()
                if c:
                    cliente_id   = c.id
                    nombre_final = f"{c.nombres} {c.apellidos}".strip() or nombre_final
                    email_final  = email_final or c.email
        except Exception:
            pass

    # Validaciones
    if not titulo.strip():
        raise HTTPException(400, "El título es requerido")
    if not descripcion.strip():
        raise HTTPException(400, "La descripción es requerida")
    if len(descripcion) < 20:
        raise HTTPException(400, "Describe el problema con al menos 20 caracteres")

    # Snapshot del nombre del vendedor
    vendedor_nombre = None
    if vendedor_dni:
        v = db.query(Vendedor).filter(Vendedor.dni == vendedor_dni).first()
        vendedor_nombre = v.nombre_tienda if v else None

    # Guardar evidencia
    evidencia_url = None
    if evidencia and evidencia.filename:
        ext = evidencia.filename.split(".")[-1].lower()
        if ext not in ["jpg","jpeg","png","webp","gif","pdf","mp4"]:
            raise HTTPException(400, "Formato de evidencia no soportado")
        fname = f"{int(datetime.utcnow().timestamp())}_{evidencia.filename}"
        path  = os.path.join(UPLOAD_DIR, fname)
        with open(path, "wb") as f:
            shutil.copyfileobj(evidencia.file, f)
        evidencia_url = f"/evidencias/{fname}"

    reporte = Reporte(
        cliente_id      = cliente_id,
        nombre_reporter = nombre_final,
        email_reporter  = email_final,
        tipo_reporte    = tipo_reporte,
        vendedor_dni    = vendedor_dni or None,
        vendedor_nombre = vendedor_nombre,
        pedido_id       = pedido_id,
        titulo          = titulo.strip(),
        descripcion     = descripcion.strip(),
        evidencia_url   = evidencia_url,
    )
    db.add(reporte)
    db.commit()
    return {"msg": "Reporte enviado. El equipo lo revisará pronto.", "id": reporte.id}


# ════════════════════════════════════════════════════════════════════════════
# SUGERENCIAS — vendedor
# ════════════════════════════════════════════════════════════════════════════

@router.post("/vendedor/sugerencias")
async def crear_sugerencia(
    tipo:        str     = Form(...),
    titulo:      str     = Form(...),
    descripcion: str     = Form(...),
    db:          Session = Depends(get_db),
    v:           Vendedor = Depends(get_current_vendedor),
):
    if not titulo.strip():
        raise HTTPException(400, "El título es requerido")
    if len(descripcion.strip()) < 20:
        raise HTTPException(400, "Describe con al menos 20 caracteres")

    s = Sugerencia(
        vendedor_dni  = v.dni,
        nombre_tienda = v.nombre_tienda,
        tipo          = tipo,
        titulo        = titulo.strip(),
        descripcion   = descripcion.strip(),
    )
    db.add(s)
    db.commit()
    return {"msg": "Enviado correctamente. Gracias por tu opinión.", "id": s.id}


@router.get("/vendedor/sugerencias")
async def mis_sugerencias(
    db: Session = Depends(get_db),
    v:  Vendedor = Depends(get_current_vendedor),
):
    rows = db.query(Sugerencia).filter(
        Sugerencia.vendedor_dni == v.dni
    ).order_by(desc(Sugerencia.creado_en)).limit(50).all()
    return [_sugerencia_dict(s) for s in rows]


# ════════════════════════════════════════════════════════════════════════════
# ADMIN — ver y gestionar reportes y sugerencias
# ════════════════════════════════════════════════════════════════════════════

@router.get("/admin/reportes")
async def admin_list_reportes(
    estado:   Optional[str] = None,
    tipo:     Optional[str] = None,
    search:   Optional[str] = None,
    db:       Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    q = db.query(Reporte)
    if estado: q = q.filter(Reporte.estado == estado)
    if tipo:   q = q.filter(Reporte.tipo_reporte == tipo)
    if search:
        s = f"%{search.lower()}%"
        q = q.filter(
            Reporte.titulo.ilike(s) |
            Reporte.nombre_reporter.ilike(s) |
            Reporte.vendedor_nombre.ilike(s)
        )
    rows = q.order_by(desc(Reporte.creado_en)).limit(200).all()
    return [_reporte_dict(r) for r in rows]


@router.put("/admin/reportes/{reporte_id}")
async def admin_update_reporte(
    reporte_id: int,
    data:       dict,
    db:         Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    r = db.query(Reporte).filter(Reporte.id == reporte_id).first()
    if not r:
        raise HTTPException(404, "Reporte no encontrado")
    if "estado"     in data: r.estado     = data["estado"]
    if "prioridad"  in data: r.prioridad  = data["prioridad"]
    if "nota_admin" in data: r.nota_admin = data["nota_admin"]
    if data.get("estado") == "resuelto":
        r.resuelto_por = admin.id
    db.commit()
    return {"msg": "Actualizado", "reporte": _reporte_dict(r)}


@router.get("/admin/sugerencias")
async def admin_list_sugerencias(
    estado: Optional[str] = None,
    tipo:   Optional[str] = None,
    db:     Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    q = db.query(Sugerencia)
    if estado: q = q.filter(Sugerencia.estado == estado)
    if tipo:   q = q.filter(Sugerencia.tipo   == tipo)
    rows = q.order_by(desc(Sugerencia.creado_en)).limit(200).all()
    return [_sugerencia_dict(s) for s in rows]


@router.put("/admin/sugerencias/{sug_id}")
async def admin_update_sugerencia(
    sug_id: int,
    data:   dict,
    db:     Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    s = db.query(Sugerencia).filter(Sugerencia.id == sug_id).first()
    if not s:
        raise HTTPException(404, "Sugerencia no encontrada")
    if "estado"     in data: s.estado     = data["estado"]
    if "prioridad"  in data: s.prioridad  = data["prioridad"]
    if "nota_admin" in data: s.nota_admin = data["nota_admin"]
    if data.get("estado") in ("implementada", "en_proceso"):
        s.respondido_por = admin.id
    db.commit()
    return {"msg": "Actualizado", "sugerencia": _sugerencia_dict(s)}


@router.get("/admin/reportes/stats")
async def admin_reportes_stats(
    db: Session = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Conteos rápidos para el badge del menú."""
    total_reportes   = db.query(func.count(Reporte.id)).scalar() or 0
    pendientes_rep   = db.query(func.count(Reporte.id)).filter(Reporte.estado == "pendiente").scalar() or 0
    total_sug        = db.query(func.count(Sugerencia.id)).scalar() or 0
    nuevas_sug       = db.query(func.count(Sugerencia.id)).filter(Sugerencia.estado == "nueva").scalar() or 0
    return {
        "reportes_total":     total_reportes,
        "reportes_pendientes": pendientes_rep,
        "sugerencias_total":   total_sug,
        "sugerencias_nuevas":  nuevas_sug,
        "sin_leer":            pendientes_rep + nuevas_sug,
    }