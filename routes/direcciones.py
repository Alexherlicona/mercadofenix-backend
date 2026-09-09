# backend/routes/direcciones.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from core.database import get_db
from core.auth import get_current_user
from models.cliente import Cliente
from models.direccion import Direccion
from schemas import DireccionCreate, DireccionUpdate, DireccionOut
from typing import List

router = APIRouter(prefix="/api/direcciones", tags=["direcciones"])

# ==================== CREAR DIRECCIÓN ====================
@router.post("/crear")
async def crear_direccion(
    dir_data: DireccionCreate,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Crear una nueva dirección guardada para el cliente"""
    
    # Si es principal, desmarcar otras
    if dir_data.es_principal:
        db.query(Direccion).filter(
            Direccion.cliente_id == current_user.id,
            Direccion.es_principal == True
        ).update({"es_principal": False})
    
    nueva_dir = Direccion(
        cliente_id=current_user.id,
        nombre_direccion=dir_data.nombre_direccion,
        departamento=dir_data.departamento,
        municipio=dir_data.municipio,
        direccion_exacta=dir_data.direccion_exacta,
        referencia=dir_data.referencia,
        telefono_contacto=dir_data.telefono_contacto,
        es_principal=dir_data.es_principal
    )
    db.add(nueva_dir)
    db.commit()
    db.refresh(nueva_dir)
    
    return {
        "mensaje": "Dirección guardada",
        "id": nueva_dir.id
    }

# ==================== OBTENER MIS DIRECCIONES ====================
@router.get("/")
async def mis_direcciones(
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener todas las direcciones guardadas del cliente"""
    direcciones = db.query(Direccion).filter(
        Direccion.cliente_id == current_user.id
    ).order_by(Direccion.es_principal.desc()).all()
    
    return {
        "direcciones": [
            {
                "id": d.id,
                "nombre_direccion": d.nombre_direccion,
                "departamento": d.departamento,
                "municipio": d.municipio,
                "direccion_exacta": d.direccion_exacta,
                "referencia": d.referencia,
                "telefono_contacto": d.telefono_contacto,
                "es_principal": d.es_principal
            }
            for d in direcciones
        ]
    }

# ==================== OBTENER UNA DIRECCIÓN ====================
@router.get("/{dir_id}")
async def obtener_direccion(
    dir_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Obtener detalles de una dirección específica"""
    direccion = db.query(Direccion).filter(
        Direccion.id == dir_id,
        Direccion.cliente_id == current_user.id
    ).first()
    
    if not direccion:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    
    return {
        "id": direccion.id,
        "nombre_direccion": direccion.nombre_direccion,
        "departamento": direccion.departamento,
        "municipio": direccion.municipio,
        "direccion_exacta": direccion.direccion_exacta,
        "referencia": direccion.referencia,
        "telefono_contacto": direccion.telefono_contacto,
        "es_principal": direccion.es_principal
    }

# ==================== ACTUALIZAR DIRECCIÓN ====================
@router.put("/{dir_id}")
async def actualizar_direccion(
    dir_id: int,
    update_data: DireccionUpdate,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Actualizar una dirección existente"""
    direccion = db.query(Direccion).filter(
        Direccion.id == dir_id,
        Direccion.cliente_id == current_user.id
    ).first()
    
    if not direccion:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    
    # Si se marca como principal, desmarcar otras
    if update_data.es_principal:
        db.query(Direccion).filter(
            Direccion.cliente_id == current_user.id,
            Direccion.id != dir_id,
            Direccion.es_principal == True
        ).update({"es_principal": False})
    
    # Actualizar campos
    for field, value in update_data.dict(exclude_unset=True).items():
        setattr(direccion, field, value)
    
    db.commit()
    db.refresh(direccion)
    
    return {"mensaje": "Dirección actualizada"}

# ==================== ELIMINAR DIRECCIÓN ====================
@router.delete("/{dir_id}")
async def eliminar_direccion(
    dir_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Eliminar una dirección"""
    direccion = db.query(Direccion).filter(
        Direccion.id == dir_id,
        Direccion.cliente_id == current_user.id
    ).first()
    
    if not direccion:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    
    db.delete(direccion)
    db.commit()
    
    return {"mensaje": "Dirección eliminada"}

# ==================== MARCAR COMO PRINCIPAL ====================
@router.patch("/{dir_id}/principal")
async def marcar_principal(
    dir_id: int,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Marcar una dirección como principal"""
    direccion = db.query(Direccion).filter(
        Direccion.id == dir_id,
        Direccion.cliente_id == current_user.id
    ).first()
    
    if not direccion:
        raise HTTPException(status_code=404, detail="Dirección no encontrada")
    
    # Desmarcar otras como principales
    db.query(Direccion).filter(
        Direccion.cliente_id == current_user.id,
        Direccion.id != dir_id
    ).update({"es_principal": False})
    
    direccion.es_principal = True
    db.commit()
    
    return {"mensaje": "Dirección marcada como principal"}