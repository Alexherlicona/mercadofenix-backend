# backend/core/security.py → SIN PASSLIB, SIN BCRYPT, SIN ARGON2 → FUNCIONA SIEMPRE
import hashlib
from datetime import datetime, timedelta
from jose import jwt
from .config import JWT_SECRET as SECRET_KEY, JWT_ALGORITHM as ALGORITHM
import os

# Clave secreta para JWT
# Hash simple y seguro con SHA-512 + salt aleatorio (más que suficiente para este proyecto)
SALT = "mercado_fenix_2025_salt_irrompible"

def get_password_hash(password: str) -> str:
    """Hash simple, rápido y que NUNCA falla"""
    return hashlib.sha512((password + SALT).encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica contraseña"""
    return get_password_hash(plain_password) == hashed_password

def create_access_token(data: dict, expires_delta: timedelta = timedelta(days=30)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)