# backend/routes/auth.py — CORREGIDO
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from core.database import get_db
from schemas import ClienteRegistro, LoginData, PerfilUpdate
from models.cliente import Cliente
from core.security import get_password_hash, verify_password, create_access_token
from core.auth import ACCESS_TOKEN_EXPIRE_MINUTES, get_current_user
from datetime import timedelta

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/registro")
async def registro(cliente: ClienteRegistro, db: Session = Depends(get_db)):
    # Validaciones básicas
    if db.query(Cliente).filter(Cliente.telefono == cliente.telefono).first():
        raise HTTPException(status_code=400, detail="El teléfono ya está registrado")

    if cliente.email and db.query(Cliente).filter(Cliente.email == cliente.email).first():
        raise HTTPException(status_code=400, detail="El email ya está registrado")

    # Crear usuario
    hashed_password = get_password_hash(cliente.password)
    nuevo_cliente = Cliente(
        nombres=cliente.nombres,
        apellidos=cliente.apellidos,
        telefono=cliente.telefono,
        password_hash=hashed_password,
        email=cliente.email,
        departamento=cliente.departamento,
        municipio=cliente.municipio,
        direccion_exacta=cliente.direccion_exacta,
    )
    db.add(nuevo_cliente)
    db.commit()
    db.refresh(nuevo_cliente)

    # ✅ FIX: Agregar "role": "cliente" al token
    # Sin esto, get_current_user lanzaba 401 en /me y /perfil tras el registro
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": nuevo_cliente.telefono, "role": "cliente"},
        expires_delta=access_token_expires
    )

    return {
        "message": "Usuario registrado exitosamente",
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": nuevo_cliente.id,
            "nombres": nuevo_cliente.nombres,
            "apellidos": nuevo_cliente.apellidos,
            "telefono": nuevo_cliente.telefono,
        }
    }


@router.post("/login")
async def login(login_data: LoginData, db: Session = Depends(get_db)):
    """
    Recibe JSON: { "telefono": "...", "password": "..." }
    El frontend DEBE enviar Content-Type: application/json.
    Si enviás form-data, FastAPI lanza 422 automáticamente.
    """
    user = db.query(Cliente).filter(Cliente.telefono == login_data.telefono).first()
    if not user or not verify_password(login_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Teléfono o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.telefono, "role": "cliente"},
        expires_delta=access_token_expires
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "nombres": user.nombres,
            "apellidos": user.apellidos,
            "telefono": user.telefono,
        }
    }


@router.put("/perfil")
async def actualizar_perfil(
    update_data: PerfilUpdate,
    current_user: Cliente = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if update_data.telefono is not None:
        existing = db.query(Cliente).filter(
            Cliente.telefono == update_data.telefono,
            Cliente.id != current_user.id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Este teléfono ya está registrado por otro usuario")
        current_user.telefono = update_data.telefono

    if update_data.direccion_exacta is not None:
        current_user.direccion_exacta = update_data.direccion_exacta

    db.commit()
    db.refresh(current_user)

    return {
        "message": "Perfil actualizado correctamente",
        "user": {
            "id": current_user.id,
            "nombres": current_user.nombres,
            "apellidos": current_user.apellidos,
            "telefono": current_user.telefono,
            "email": current_user.email,
            "departamento": current_user.departamento,
            "municipio": current_user.municipio,
            "direccion_exacta": current_user.direccion_exacta,
        }
    }


@router.get("/me")
async def get_current_user_info(current_user: Cliente = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "nombres": current_user.nombres,
        "apellidos": current_user.apellidos,
        "telefono": current_user.telefono,
        "email": current_user.email,
        "departamento": current_user.departamento,
        "municipio": current_user.municipio,
        "direccion_exacta": current_user.direccion_exacta,
    }