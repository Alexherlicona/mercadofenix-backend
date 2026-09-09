# backend/core/config.py
import os
from dotenv import load_dotenv

# MÉTODO INFALIBLE: Busca el .env subiendo carpetas hasta encontrarlo
current_dir = os.path.dirname(__file__)
project_root = current_dir

# Sube hasta encontrar el .env (máximo 5 niveles)
for _ in range(5):
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        break
    project_root = os.path.dirname(project_root)
else:
    # Si no lo encuentra, falla fuerte para que sepas
    raise FileNotFoundError(" No se encontró el archivo .env en ningún nivel superior")

# Carga el .env
load_dotenv(env_path)

# Verifica que realmente se cargó
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(" ERROR: DATABASE_URL no está en el .env o está vacía")

# Imprime para que veas que SÍ funcionó
print("\n DATABASE_URL CARGADA CORRECTAMENTE!")
print(f" Conexión: {DATABASE_URL.split('@')[1].split('/')[0] if '@' in DATABASE_URL else 'OK'}\n")

# Exportamos las variables
DATABASE_URL = DATABASE_URL
JWT_SECRET = os.getenv("JWT_SECRET", "super-secreto-mercado-fenix-2025-admin-only")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
