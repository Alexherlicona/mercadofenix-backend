# backend/core/security.py
import hashlib
import os
from datetime import datetime, timedelta
from jose import jwt

try:
    from passlib.context import CryptContext
    _pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    _HAS_PASSLIB = True
except Exception:
    _pwd_context = None
    _HAS_PASSLIB = False

from .config import JWT_SECRET as SECRET_KEY, JWT_ALGORITHM as ALGORITHM

# Fallback salt solo para migración/compatibilidad si no hay bcrypt
SALT = os.getenv("PASSWORD_SALT", "mercado_fenix_2025_salt_irrompible")

def get_password_hash(password: str) -> str:
    if _HAS_PASSLIB and _pwd_context is not None:
        try:
            return _pwd_context.hash(password)
        except Exception:
            pass
    # Fallback (débil) - solo si bcrypt no disponible
    return hashlib.sha512((password + SALT).encode()).hexdigest()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not hashed_password:
        return False
    # Si parece bcrypt
    if hashed_password.startswith("$2b$") or hashed_password.startswith("$2a$") or hashed_password.startswith("$2y$"):
        if _HAS_PASSLIB and _pwd_context is not None:
            try:
                return _pwd_context.verify(plain_password, hashed_password)
            except Exception:
                return False
    # Legacy SHA-512
    try:
        return get_password_hash(plain_password) == hashed_password or hashlib.sha512((plain_password + SALT).encode()).hexdigest() == hashed_password
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta = timedelta(days=7)):
    to_encode = data.copy()
    expire = datetime.utcnow() + expires_delta
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)