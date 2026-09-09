# backend/core/slug.py
import re
import unicodedata


def generar_slug(texto: str) -> str:
    """
    Convierte un texto en slug URL-safe.
    'Tienda María & Hijos' → 'tienda-maria-hijos'
    Quita acentos, pasa a minúsculas, reemplaza espacios y símbolos por guiones.
    """
    # Normalizar y quitar acentos
    texto = unicodedata.normalize("NFKD", texto)
    texto = texto.encode("ascii", "ignore").decode("ascii")
    # Minúsculas
    texto = texto.lower().strip()
    # Reemplazar todo lo que no sea alfanumérico por guiones
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    # Quitar guiones de los extremos
    texto = texto.strip("-")
    return texto


def slug_tienda(nombre_tienda: str, municipio: str) -> str:
    """
    Genera el slug único de una tienda combinando nombre + municipio.
    'Zapatería El Sol' en 'Tegucigalpa' → 'zapateria-el-sol-tegucigalpa'
    Como el nombre es único por municipio, esta combinación es única en la plataforma.
    """
    return f"{generar_slug(nombre_tienda)}-{generar_slug(municipio)}"