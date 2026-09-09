# backend/crud/producto.py
from sqlalchemy.orm import Session
from models.producto import Producto, FotoProducto
import shutil, os, json
from datetime import datetime

UPLOAD_DIR  = "public/uploads/productos"
DIGITAL_DIR = "public/digitales"
os.makedirs(UPLOAD_DIR,  exist_ok=True)
os.makedirs(DIGITAL_DIR, exist_ok=True)

# Extensiones permitidas para productos digitales
EXTENSIONES_DIGITALES = {
    # Archivos comprimidos / proyectos
    "zip", "rar", "7z", "tar", "gz", "tgz",
    # Documentos
    "pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "rtf", "odt", "csv",
    # Imágenes / diseño
    "psd", "ai", "xd", "fig", "sketch", "eps", "svg", "png", "jpg", "jpeg", "webp",
    # Video / audio
    "mp4", "mov", "avi", "mkv", "mp3", "wav", "flac", "m4a",
    # Código
    "py", "js", "ts", "html", "css", "json", "xml", "sql", "sh", "ipynb",
    # eBooks
    "epub", "mobi",
    # Otros
    "apk", "exe", "dmg",
}

def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

def _formato_legible(ext: str) -> str:
    mapa = {
        "zip":"ZIP","rar":"RAR","7z":"7-Zip","tar":"TAR","gz":"GZip",
        "pdf":"PDF","docx":"Word","xlsx":"Excel","pptx":"PowerPoint","txt":"Texto plano",
        "psd":"Photoshop","ai":"Illustrator","xd":"Adobe XD","fig":"Figma","sketch":"Sketch",
        "mp4":"Video MP4","mov":"Video MOV","mp3":"Audio MP3","wav":"Audio WAV",
        "py":"Python","js":"JavaScript","ts":"TypeScript","html":"HTML","ipynb":"Jupyter Notebook",
        "epub":"ePub","mobi":"Kindle",
    }
    return mapa.get(ext, ext.upper())


def crear_producto(db: Session, vendedor_id: str, datos: dict,
                   fotos=None, archivo_digital=None, portada_digital=None):

    precio_base  = float(datos["precio"])
    porcentaje   = float(datos.get("porcentaje_descuento", 0))
    precio_desc  = round(precio_base * (1 - porcentaje / 100), 2) if porcentaje > 0 else None

    # ── Guardar archivo digital ──────────────────────────────────────────────
    archivo_key     = None
    formato_archivo = None
    tamano_bytes    = None

    if archivo_digital and hasattr(archivo_digital, "filename"):
        ext = _ext(archivo_digital.filename)
        ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{vendedor_id}_{ts}.{ext}"
        path = os.path.join(DIGITAL_DIR, filename)
        content = archivo_digital.file.read()
        with open(path, "wb") as f:
            f.write(content)
        archivo_key     = f"/digitales/{filename}"
        formato_archivo = ext
        tamano_bytes    = len(content)

    # ── Archivos incluidos (varios archivos en ZIP + metadatos) ──────────────
    archivos_incluidos = datos.get("archivos_incluidos", [])
    if isinstance(archivos_incluidos, str):
        try:    archivos_incluidos = json.loads(archivos_incluidos)
        except: archivos_incluidos = []

    # ── Crear objeto Producto ────────────────────────────────────────────────
    producto = Producto(
        vendedor_id = vendedor_id,

        # Clasificación
        tipo        = datos["tipo"],
        categoria   = datos["categoria"],
        nombre      = datos["nombre"],
        subtitulo   = datos.get("subtitulo"),
        idioma      = datos.get("idioma", "Español"),
        etiquetas   = datos.get("etiquetas", []),
        moneda      = datos.get("moneda", "HNL"),

        # Precios
        precio               = precio_base,
        precio_original      = precio_base if porcentaje > 0 else None,
        precio_con_descuento = precio_desc,
        porcentaje_descuento = porcentaje,
        permite_oferta       = datos.get("permite_oferta", True),
        precio_minimo_oferta = datos.get("precio_minimo_oferta"),

        # Texto
        descripcion = datos.get("descripcion"),

        # ── FÍSICO ──────────────────────────────────────────────────────────
        stock               = datos.get("stock", 1) if datos["tipo"] == "fisico" else None,
        stock_minimo_alerta = datos.get("stock_minimo_alerta", 0),
        permite_preventa    = datos.get("permite_preventa", False),
        variantes           = datos.get("variantes", {}),
        condicion           = datos.get("condicion", "nuevo"),
        sku                 = datos.get("sku"),
        codigo_barras       = datos.get("codigo_barras"),
        marca               = datos.get("marca"),
        modelo              = datos.get("modelo"),
        pais_origen         = datos.get("pais_origen"),
        material            = datos.get("material"),
        peso_gramos         = datos.get("peso_gramos"),
        largo_cm            = datos.get("largo_cm"),
        ancho_cm            = datos.get("ancho_cm"),
        alto_cm             = datos.get("alto_cm"),
        garantia_meses      = datos.get("garantia_meses", 0),
        descripcion_garantia = datos.get("descripcion_garantia"),

        # ── DIGITAL ─────────────────────────────────────────────────────────
        archivo_key        = archivo_key,
        formato_archivo    = formato_archivo or datos.get("formato_archivo"),
        tamano_bytes       = tamano_bytes,
        num_archivos       = datos.get("num_archivos"),
        archivos_incluidos = archivos_incluidos,
        version            = datos.get("version"),
        requiere_software  = datos.get("requiere_software", []),
        compatibilidad     = datos.get("compatibilidad", []),
        lenguajes          = datos.get("lenguajes", []),
        frameworks         = datos.get("frameworks", []),
        nivel_dificultad   = datos.get("nivel_dificultad"),
        incluye_soporte    = datos.get("incluye_soporte", False),
        dias_soporte       = datos.get("dias_soporte"),
        duracion_minutos   = datos.get("duracion_minutos"),
        num_lecciones      = datos.get("num_lecciones"),
        num_paginas        = datos.get("num_paginas"),
        isbn               = datos.get("isbn"),
        autor              = datos.get("autor"),
        editorial          = datos.get("editorial"),
        fecha_publicacion  = datos.get("fecha_publicacion"),
        max_descargas      = datos.get("max_descargas"),
        dias_acceso        = datos.get("dias_acceso"),
        preview_url        = datos.get("preview_url"),
        licencia           = datos.get("licencia", "personal"),
        licencia_detalle   = datos.get("licencia_detalle"),
        permite_reventa    = datos.get("permite_reventa", False),
        permite_modificar  = datos.get("permite_modificar", True),
    )

    db.add(producto)
    db.flush()  # obtener el ID antes de guardar fotos

    # ── Guardar fotos (físico) ───────────────────────────────────────────────
    if fotos:
        for i, foto in enumerate(fotos):
            if not hasattr(foto, "filename") or not foto.filename:
                continue
            ext      = _ext(foto.filename) or "webp"
            filename = f"{producto.id}_{i}.{ext}"
            path     = os.path.join(UPLOAD_DIR, filename)
            with open(path, "wb") as f:
                shutil.copyfileobj(foto.file, f)
            db.add(FotoProducto(
                producto_id = producto.id,
                url         = f"/uploads/productos/{filename}",
                orden       = i,
            ))

    # ── Guardar portada del producto digital ─────────────────────────────────
    if portada_digital and hasattr(portada_digital, "filename") and portada_digital.filename:
        ext      = _ext(portada_digital.filename) or "jpg"
        filename = f"{producto.id}_portada.{ext}"
        path     = os.path.join(UPLOAD_DIR, filename)
        with open(path, "wb") as f:
            shutil.copyfileobj(portada_digital.file, f)
        db.add(FotoProducto(
            producto_id = producto.id,
            url         = f"/uploads/productos/{filename}",
            orden       = 0,
        ))

    db.commit()
    db.refresh(producto)
    return producto


def serializar_producto(p: Producto) -> dict:
    """Serialización completa — usar en GET /productos/{id}"""
    return {
        "id":          str(p.id),
        "slug":        p.slug,
        "vendedor_id": p.vendedor_id,

        # Clasificación
        "tipo":        p.tipo,
        "categoria":   p.categoria,
        "nombre":      p.nombre,
        "subtitulo":   p.subtitulo,
        "idioma":      p.idioma,
        "etiquetas":   p.etiquetas or [],
        "moneda":      p.moneda,

        # Precios
        "precio":                float(p.precio),
        "precio_original":       float(p.precio_original)      if p.precio_original      else None,
        "precio_con_descuento":  float(p.precio_con_descuento) if p.precio_con_descuento else None,
        "porcentaje_descuento":  float(p.porcentaje_descuento) if p.porcentaje_descuento else 0,
        "permite_oferta":        p.permite_oferta,
        "precio_minimo_oferta":  float(p.precio_minimo_oferta) if p.precio_minimo_oferta else None,

        "descripcion":   p.descripcion or "",
        "activo":        p.activo,
        "destacado":     p.destacado,

        # Métricas
        "ventas_count":      p.ventas_count,
        "vistas_count":      p.vistas_count,
        "favoritos_count":   p.favoritos_count,
        "calificacion_prom": float(p.calificacion_prom) if p.calificacion_prom else 0,
        "total_resenas":     p.total_resenas,

        "creado_en":      p.creado_en.isoformat()      if p.creado_en      else None,
        "actualizado_en": p.actualizado_en.isoformat() if p.actualizado_en else None,

        # Fotos
        "fotos": [f.to_dict() for f in sorted(p.fotos, key=lambda x: x.orden)],

        # ── Físico ───────────────────────────────────────────────────────
        "stock":                p.stock,
        "stock_minimo_alerta":  p.stock_minimo_alerta,
        "permite_preventa":     p.permite_preventa,
        "variantes":            p.variantes or {},
        "condicion":            p.condicion,
        "sku":                  p.sku,
        "codigo_barras":        p.codigo_barras,
        "marca":                p.marca,
        "modelo":               p.modelo,
        "pais_origen":          p.pais_origen,
        "material":             p.material,
        "peso_gramos":          p.peso_gramos,
        "largo_cm":             float(p.largo_cm)  if p.largo_cm  else None,
        "ancho_cm":             float(p.ancho_cm)  if p.ancho_cm  else None,
        "alto_cm":              float(p.alto_cm)   if p.alto_cm   else None,
        "garantia_meses":       p.garantia_meses,
        "descripcion_garantia": p.descripcion_garantia,

        # ── Digital ──────────────────────────────────────────────────────
        "archivo_key":        p.archivo_key,
        "formato_archivo":    p.formato_archivo,
        "formato_legible":    _formato_legible(p.formato_archivo) if p.formato_archivo else None,
        "tamano_bytes":       p.tamano_bytes,
        "tamano_mb":          round(p.tamano_bytes / 1024 / 1024, 2) if p.tamano_bytes else None,
        "num_archivos":       p.num_archivos,
        "archivos_incluidos": p.archivos_incluidos or [],
        "version":            p.version,
        "requiere_software":  p.requiere_software or [],
        "compatibilidad":     p.compatibilidad or [],
        "lenguajes":          p.lenguajes or [],
        "frameworks":         p.frameworks or [],
        "nivel_dificultad":   p.nivel_dificultad,
        "incluye_soporte":    p.incluye_soporte,
        "dias_soporte":       p.dias_soporte,
        "duracion_minutos":   p.duracion_minutos,
        "num_lecciones":      p.num_lecciones,
        "num_paginas":        p.num_paginas,
        "isbn":               p.isbn,
        "autor":              p.autor,
        "editorial":          p.editorial,
        "fecha_publicacion":  p.fecha_publicacion.isoformat() if p.fecha_publicacion else None,
        "max_descargas":      p.max_descargas,
        "dias_acceso":        p.dias_acceso,
        "preview_url":        p.preview_url,
        "licencia":           p.licencia,
        "licencia_detalle":   p.licencia_detalle,
        "permite_reventa":    p.permite_reventa,
        "permite_modificar":  p.permite_modificar,
    }