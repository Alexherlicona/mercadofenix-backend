# backend/core/auth.py — CORREGIDO
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session
from core.database import get_db
from models.admin import Admin
from models.vendedor import Vendedor
from models.cliente import Cliente
from passlib.context import CryptContext
from core.security import SECRET_KEY, ALGORITHM
from sqlalchemy import or_

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 60  # 60 días

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


# ==================== ADMIN ====================
async def get_current_admin(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado como administrador",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        usuario: str = payload.get("sub")
        role: str = payload.get("role")
        if not usuario or role != "admin":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    admin = db.query(Admin).filter(Admin.usuario == usuario).first()
    if not admin:
        raise credentials_exception
    return admin


# ==================== VENDEDOR ====================
async def get_current_vendedor(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autorizado como vendedor",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        dni: str = payload.get("sub")
        role: str = payload.get("role")
        if not dni or role != "vendedor":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    vendedor = db.query(Vendedor).filter(Vendedor.dni == dni).first()
    if not vendedor or not vendedor.activo:
        raise credentials_exception
    return vendedor


# ==================== CLIENTE ====================
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudieron validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        role = payload.get("role")
        cliente_id = payload.get("cliente_id")

        if not sub and not cliente_id:
            raise credentials_exception
        if role is not None and role != "cliente":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = None
    if cliente_id:
        user = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not user and sub:
        user = db.query(Cliente).filter(
            or_(Cliente.telefono == sub, Cliente.email == sub)
        ).first()
    if not user:
        raise credentials_exception
    return user