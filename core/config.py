# backend/core/config.py
import os
from dotenv import load_dotenv
from pathlib import Path

# En desarrollo local carga el .env — en Render lo ignora y usa las variables del sistema
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

# Variables exportadas
DATABASE_URL  = os.getenv("DATABASE_URL", "")
JWT_SECRET    = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")

# Validación — falla claro si falta algo crítico
if not DATABASE_URL:
    raise ValueError("DATABASE_URL no está configurada")
if not JWT_SECRET:
    raise ValueError("JWT_SECRET no está configurada")

print(f"✓ Config cargada — DB: {DATABASE_URL.split('@')[-1].split('/')[0] if '@' in DATABASE_URL else 'OK'}")