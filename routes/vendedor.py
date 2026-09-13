# backend/routes/vendedor.py
# Router con prefix="/vendedor" → main.py agrega "/api" → /api/vendedor/...
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile, Request
from crud.producto import crear_producto
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from core.database import get_db
from models.vendedor import Vendedor
from core.security import get_password_hash, verify_password, create_access_token
from core.auth import get_current_vendedor
from models.producto import Producto, FotoProducto
from typing import List, Optional
import shutil
from datetime import datetime, timedelta
import os
from sqlalchemy import func

# ── Helper Cloudinary ─────────────────────────────────────────────────────────
async def _subir_foto_cloudinary(archivo, public_id: str) -> str:
    """
    Sube una foto de producto a Cloudinary.
    Fallback a disco si Cloudinary no está configurado o falla.
    """
    try:
        import cloudinary.uploader
        contenido = archivo.file.read()
        resultado = cloudinary.uploader.upload(
            contenido,
            folder="mercadofenix/productos",
            public_id=public_id,
            overwrite=True,
            resource_type="image",
        )
        return resultado["secure_url"]
    except Exception as e:
        print(f"[Cloudinary] Error subiendo foto {public_id}: {e}")
        # Fallback a disco
        archivo.file.seek(0)
        ext = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else "jpg"
        if ext not in ["jpg", "jpeg", "png", "webp"]: ext = "jpg"
        ruta = f"public/uploads/productos/{public_id}.{ext}"
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            shutil.copyfileobj(archivo.file, f)
        return f"/uploads/productos/{public_id}.{ext}"


def _eliminar_foto(url: str):
    """Elimina una foto de Cloudinary o disco según la URL."""
    if not url:
        return
    if url.startswith("http"):
        try:
            import cloudinary.uploader
            partes = url.split("/upload/")
            if len(partes) == 2:
                public_id = partes[1].rsplit(".", 1)[0]
                if "/" in public_id and public_id.split("/")[0].startswith("v"):
                    public_id = public_id.split("/", 1)[1]
                cloudinary.uploader.destroy(public_id)
        except Exception as e:
            print(f"[Cloudinary] Error eliminando {url}: {e}")
    else:
        ruta = f"public{url}" if url.startswith("/") else url
        if os.path.exists(ruta):
            os.remove(ruta)

# prefix="/vendedor" + main.py prefix="/api" = /api/vendedor/...
router = APIRouter(prefix="/vendedor")


# ── Rate limiting helpers ─────────────────────────────────────────────────────
MAX_INTENTOS_POR_ID  = 5   # máx intentos por teléfono/email en la ventana
MAX_INTENTOS_POR_IP  = 20  # máx intentos por IP (cubre múltiples cuentas)
VENTANA_MINUTOS      = 15  # ventana deslizante en minutos

def _registrar_intento(db: Session, identifier: str, ip: str, exitoso: bool):
    """Guarda el intento en login_intentos y limpia registros viejos."""
    try:
        db.execute(text(
            "INSERT INTO login_intentos (identifier, ip, exitoso) VALUES (:id, :ip, :ok)"
        ), {"id": identifier.lower(), "ip": ip, "ok": exitoso})
        # Limpiar intentos de más de 24 h (mantenimiento inline)
        db.execute(text(
            "DELETE FROM login_intentos WHERE creado_en < NOW() - INTERVAL '24 hours'"
        ))
        db.commit()
    except Exception:
        db.rollback()   # no romper el flujo si falla el log

def _verificar_rate_limit(db: Session, identifier: str, ip: str):
    """
    Lanza 429 si se superan los intentos fallidos en la ventana.
    Bloquea por identifier (teléfono/email) Y por IP.
    """
    ventana = datetime.utcnow() - timedelta(minutes=VENTANA_MINUTOS)
    try:
        intentos_id = db.execute(text(
            "SELECT COUNT(*) FROM login_intentos "
            "WHERE identifier = :id AND exitoso = false AND creado_en > :v"
        ), {"id": identifier.lower(), "v": ventana}).scalar() or 0

        intentos_ip = db.execute(text(
            "SELECT COUNT(*) FROM login_intentos "
            "WHERE ip = :ip AND exitoso = false AND creado_en > :v"
        ), {"ip": ip, "v": ventana}).scalar() or 0

        if intentos_id >= MAX_INTENTOS_POR_ID:
            raise HTTPException(
                status_code=429,
                detail=f"Demasiados intentos fallidos. Espera {VENTANA_MINUTOS} minutos antes de volver a intentarlo.",
                headers={"Retry-After": str(VENTANA_MINUTOS * 60)}
            )
        if intentos_ip >= MAX_INTENTOS_POR_IP:
            raise HTTPException(
                status_code=429,
                detail="Demasiadas solicitudes desde tu red. Espera 15 minutos.",
                headers={"Retry-After": str(VENTANA_MINUTOS * 60)}
            )
    except HTTPException:
        raise
    except Exception:
        pass   # si falla la consulta, no bloquear al usuario legítimo

def _get_ip(request: Request) -> str:
    """Obtener IP real respetando X-Forwarded-For de proxies/Nginx."""
    ff = request.headers.get("X-Forwarded-For")
    if ff:
        return ff.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.post("/register")           # → POST /api/vendedor/register
async def register_vendedor(
    dni: str = Form(...),
    rtn: str = Form(...),
    propietario: str = Form(...),
    nombre_tienda: str = Form(...),
    telefono: str = Form(...),
    email: str = Form(...),
    departamento: str = Form(...),
    municipio: str = Form(...),
    direccion_exacta: str = Form(...),
    password: str = Form(...),
    tipo_pago: str = Form(...),
    tipo_entrega: str = Form(...),
    # Ubicación de la tienda (opcional pero recomendada)
    latitud: Optional[float] = Form(None),
    longitud: Optional[float] = Form(None),
    google_maps_url: Optional[str] = Form(None),
    # Archivos
    logo: Optional[UploadFile] = File(None),
    documento_identidad: UploadFile = File(...),    # OBLIGATORIO
    db: Session = Depends(get_db)
):
    # ── Validaciones básicas ──────────────────────────────────────────────────
    if len(dni) != 13:
        raise HTTPException(400, "DNI debe tener exactamente 13 dígitos")
    if len(rtn) != 14:
        raise HTTPException(400, "RTN debe tener exactamente 14 dígitos")
    if len(telefono) != 8:
        raise HTTPException(400, "Teléfono debe tener 8 dígitos")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "Correo electrónico inválido")
    if len(password) < 8:
        raise HTTPException(400, "La contraseña debe tener al menos 8 caracteres")

    # ── Documento de identidad obligatorio ───────────────────────────────────
    if not documento_identidad or not documento_identidad.filename:
        raise HTTPException(400, "Debes subir una foto de tu documento de identidad")
    ext_doc = documento_identidad.filename.split(".")[-1].lower()
    if ext_doc not in ["jpg", "jpeg", "png", "webp", "pdf"]:
        raise HTTPException(400, "El documento debe ser JPG, PNG, WEBP o PDF")

    # ── Unicidad ─────────────────────────────────────────────────────────────
    if db.query(Vendedor).filter(Vendedor.dni == dni).first():
        raise HTTPException(400, "Este DNI ya está registrado")
    if db.query(Vendedor).filter(Vendedor.telefono == telefono).first():
        raise HTTPException(400, "Este teléfono ya está registrado")

    # Verificar email usando text() para columna que puede no existir en el modelo viejo
    try:
        existe_email = db.execute(
            text("SELECT 1 FROM vendedores WHERE email = :e LIMIT 1"),
            {"e": email.lower()}
        ).first()
        if existe_email:
            raise HTTPException(400, "Este correo ya está registrado")
    except HTTPException:
        raise
    except Exception:
        pass  # columna aún no existe → ignorar

    os.makedirs("public/logos",       exist_ok=True)
    os.makedirs("public/documentos",  exist_ok=True)

    # ── Guardar logo (opcional) ───────────────────────────────────────────────
    logo_url = None
    if logo and logo.filename:
        if not logo.content_type.startswith("image/"):
            raise HTTPException(400, "El logo debe ser una imagen")
        ext_logo = logo.filename.split(".")[-1].lower()
        if ext_logo not in ["jpg", "jpeg", "png", "webp"]:
            ext_logo = "jpg"
        path_logo = f"public/logos/{dni}.{ext_logo}"
        with open(path_logo, "wb") as f:
            f.write(await logo.read())
        logo_url = f"/logos/{dni}.{ext_logo}"

    # ── Guardar documento de identidad ────────────────────────────────────────
    path_doc = f"public/documentos/{dni}_doc.{ext_doc}"
    with open(path_doc, "wb") as f:
        f.write(await documento_identidad.read())
    documento_url = f"/documentos/{dni}_doc.{ext_doc}"

    # ── Normalizar campos opcionales ──────────────────────────────────────────
    lat  = latitud  if latitud  is not None else None
    lng  = longitud if longitud is not None else None
    maps = google_maps_url.strip() if google_maps_url else None

    # ── Crear vendedor ────────────────────────────────────────────────────────
    nuevo = Vendedor(
        dni=dni, rtn=rtn, propietario=propietario, nombre_tienda=nombre_tienda,
        telefono=telefono, departamento=departamento, municipio=municipio,
        direccion_exacta=direccion_exacta, password_hash=get_password_hash(password),
        logo_url=logo_url, activo=False, solicitud_pendiente=True, meses_pagados=0,
        tipo_pago=tipo_pago, tipo_entrega=tipo_entrega,
    )
    db.add(nuevo)
    db.flush()

    # Asignar campos nuevos con UPDATE para mayor compatibilidad
    try:
        db.execute(text(
            "UPDATE vendedores SET email=:e, documento_url=:d, latitud=:lat, longitud=:lng, google_maps_url=:maps "
            "WHERE dni=:dni"
        ), {"e": email.lower(), "d": documento_url, "lat": lat, "lng": lng, "maps": maps, "dni": dni})
    except Exception:
        pass  # si la migración SQL no se corrió aún, el registro igual funciona

    db.commit()
    return {"msg": "Solicitud enviada con éxito. El administrador revisará tu documento y aprobará tu tienda."}


@router.post("/login")              # → POST /api/vendedor/login
async def login_vendedor(
    request: Request,
    telefono: str = Form(None),   # puede venir teléfono
    email: str = Form(None),      # o correo electrónico
    identifier: str = Form(None), # o un campo genérico "identifier"
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Login del vendedor. Acepta teléfono O correo electrónico.
    Protegido contra fuerza bruta: máx 5 intentos por cuenta en 15 min.
    """
    ip = _get_ip(request)

    # Resolver qué identificador se envió
    ident = (identifier or telefono or email or "").strip()
    if not ident:
        raise HTTPException(400, "Ingresa tu teléfono o correo electrónico")

    # Verificar rate limit ANTES de consultar la BD
    _verificar_rate_limit(db, ident, ip)

    # Buscar vendedor por teléfono O por email
    v = db.query(Vendedor).filter(Vendedor.telefono == ident).first()
    if not v:
        # Intentar por email (usando text() por si la columna fue recién agregada)
        try:
            row = db.execute(
                text("SELECT dni FROM vendedores WHERE email = :e LIMIT 1"),
                {"e": ident.lower()}
            ).first()
            if row:
                v = db.query(Vendedor).filter(Vendedor.dni == row.dni).first()
        except Exception:
            pass

    # Contraseña incorrecta o usuario no encontrado
    if not v or not verify_password(password, v.password_hash):
        _registrar_intento(db, ident, ip, exitoso=False)
        # Mensaje genérico — no revelar si el usuario existe
        raise HTTPException(401, "Credenciales incorrectas")

    # Estado del vendedor
    if not v.activo:
        _registrar_intento(db, ident, ip, exitoso=False)
        raise HTTPException(403, "Tu tienda no está activa. Contacta al administrador.")
    # solicitud_pendiente solo bloquea si activo es False también
    # Si el admin activó manualmente el toggle, el vendedor puede entrar
    if v.solicitud_pendiente and not v.activo:
        _registrar_intento(db, ident, ip, exitoso=False)
        raise HTTPException(403, "Tu solicitud está en revisión. Te notificaremos cuando sea aprobada.")

    # Login exitoso — limpiar conteo de intentos (reset implícito al registrar éxito)
    _registrar_intento(db, ident, ip, exitoso=True)

    token = create_access_token({"sub": v.dni, "role": "vendedor"})
    return {
        "access_token": token,
        "token_type":   "bearer",
        "vendedor": {
            "dni":          v.dni,
            "nombre_tienda": v.nombre_tienda,
            "propietario":  v.propietario,
        }
    }


@router.get("/me")                  # → GET /api/vendedor/me
async def get_me(v: Vendedor = Depends(get_current_vendedor)):
    return {
        "dni": v.dni, "rtn": v.rtn, "propietario": v.propietario,
        "nombre_tienda": v.nombre_tienda, "telefono": v.telefono,
        "departamento": v.departamento, "municipio": v.municipio,
        "direccion_exacta": v.direccion_exacta, "logo_url": v.logo_url,
        "activo": v.activo, "plan": v.plan, "meses_pagados": v.meses_pagados,
        "fecha_pago": v.fecha_pago.isoformat() if v.fecha_pago else None,
        "fecha_expiracion": v.fecha_expiracion.isoformat() if v.fecha_expiracion else None,
        "tipo_pago": v.tipo_pago, "tipo_entrega": v.tipo_entrega,
    }


@router.put("/perfil")              # → PUT /api/vendedor/perfil
async def actualizar_perfil(
    nombre_tienda:   str            = Form(...),
    propietario:     str            = Form(...),
    telefono:        str            = Form(...),
    municipio:       str            = Form(...),
    direccion_exacta:str            = Form(...),
    email:           Optional[str]  = Form(None),
    google_maps_url: Optional[str]  = Form(None),
    latitud:         Optional[float]= Form(None),
    longitud:        Optional[float]= Form(None),
    tipo_pago:       Optional[str]  = Form(None),
    tipo_entrega:    Optional[str]  = Form(None),
    logo:            Optional[UploadFile] = File(None),
    cv:  Vendedor  = Depends(get_current_vendedor),
    db:  Session   = Depends(get_db)
):
    if len(telefono) != 8 or not telefono.isdigit():
        raise HTTPException(400, detail="Teléfono debe tener 8 dígitos")
 
    if db.query(Vendedor).filter(
        func.lower(func.trim(Vendedor.nombre_tienda)) == nombre_tienda.strip().lower(),
        func.lower(func.trim(Vendedor.municipio)) == municipio.strip().lower(),
        Vendedor.dni != cv.dni
    ).first():
        raise HTTPException(400, detail=f"Ya existe una tienda llamada '{nombre_tienda}' en {municipio}.")
 
    if db.query(Vendedor).filter(Vendedor.telefono == telefono, Vendedor.dni != cv.dni).first():
        raise HTTPException(400, detail="Este teléfono ya está registrado por otra tienda")
 
    # Email — verificar duplicado si cambió
    if email and email.strip():
        email = email.strip().lower()
        try:
            row = db.execute(
                text("SELECT dni FROM vendedores WHERE email = :e AND dni != :dni LIMIT 1"),
                {"e": email, "dni": cv.dni}
            ).first()
            if row:
                raise HTTPException(400, detail="Este correo ya está registrado por otra tienda")
        except HTTPException:
            raise
        except Exception:
            pass
 
    cv.nombre_tienda    = nombre_tienda.strip()
    cv.propietario      = propietario.strip()
    cv.telefono         = telefono
    cv.direccion_exacta = direccion_exacta.strip()
    if municipio: cv.municipio = municipio.strip()
    if tipo_pago:       cv.tipo_pago    = tipo_pago
    if tipo_entrega:    cv.tipo_entrega = tipo_entrega
 
    # Campos opcionales con text() para columnas que pueden no estar en el modelo viejo
    updates = {}
    if email:           updates["email"]          = email
    if google_maps_url: updates["google_maps_url"] = google_maps_url.strip()
    if latitud  is not None: updates["latitud"]   = latitud
    if longitud is not None: updates["longitud"]  = longitud
 
    if updates:
        try:
            sets = ", ".join(f"{k} = :{k}" for k in updates)
            updates["dni"] = cv.dni
            db.execute(text(f"UPDATE vendedores SET {sets} WHERE dni = :dni"), updates)
        except Exception:
            pass  # columnas opcionales — no bloquear si no existen
 
    if logo and logo.filename:
        if not logo.content_type.startswith("image/"):
            raise HTTPException(400, detail="Solo se permiten imágenes")
        logo_dir = "public/logos"
        os.makedirs(logo_dir, exist_ok=True)
        if cv.logo_url:
            viejo = f"public{cv.logo_url}"
            if os.path.exists(viejo): os.remove(viejo)
        ext = logo.filename.split(".")[-1].lower()
        if ext not in ["jpg", "jpeg", "png", "webp"]: ext = "jpg"
        path = os.path.join(logo_dir, f"{cv.dni}.{ext}")
        with open(path, "wb") as f:
            f.write(await logo.read())
        cv.logo_url = f"/logos/{cv.dni}.{ext}"
 
    db.commit()
    db.refresh(cv)
    return {"msg": "Perfil actualizado con éxito"}


# ── Productos ─────────────────────────────────────────────────────────────────

@router.post("/productos")          # → POST /api/vendedor/productos
async def publicar_producto(
    request: Request,
    db: Session = Depends(get_db),
    vendedor: Vendedor = Depends(get_current_vendedor)
):
    import json as _json

    form = await request.form()
    tipo      = form.get("tipo")
    categoria = form.get("categoria")
    nombre    = form.get("nombre")
    precio    = form.get("precio")

    if not all([tipo, categoria, nombre, precio]):
        raise HTTPException(400, "Faltan datos obligatorios")

    # Helper: parsea un campo que puede llegar como JSON string o valor directo
    def _list(key: str) -> list:
        val = form.get(key, "")
        if not val:
            return []
        if isinstance(val, list):
            return val
        try:
            parsed = _json.loads(val)
            return parsed if isinstance(parsed, list) else [str(parsed)]
        except Exception:
            return [s.strip() for s in str(val).split(",") if s.strip()]

    def _bool(key: str, default: bool = False) -> bool:
        val = str(form.get(key, "")).lower()
        if val in ("true", "1", "yes"): return True
        if val in ("false", "0", "no"): return False
        return default

    def _int_or_none(key: str):
        val = form.get(key, "")
        try:    return int(val) if val else None
        except: return None

    # Todos los campos conocidos — no caen en variantes
    KNOWN = {
        "tipo","categoria","nombre","precio","descuento","descripcion",
        "stock","stock_minimo_alerta","condicion","licencia","subtitulo",
        "idioma","etiquetas","marca","modelo","sku","material",
        "peso_gramos","largo_cm","ancho_cm","alto_cm",
        "garantia_meses","descripcion_garantia",
        "version","compatibilidad","lenguajes","frameworks",
        "requiere_software","nivel_dificultad","incluye_soporte","dias_soporte",
        "duracion_minutos","num_lecciones","num_paginas","autor","editorial","isbn",
        "max_descargas","dias_acceso","preview_url","permite_reventa","permite_modificar",
        "resolucion","bpm","genero_musical","especificaciones",
        "fotos","archivo","portada_digital",
    }

    # Variantes: solo pares que NO son campos conocidos
    variantes = {}
    for k, v in form.multi_items():
        if k not in KNOWN and v and not hasattr(v, "filename"):
            variantes[k] = str(v)

    datos = {
        # Básicos
        "tipo":                tipo,
        "categoria":           categoria,
        "nombre":              nombre.strip(),
        "subtitulo":           form.get("subtitulo") or None,
        "idioma":              form.get("idioma", "Español"),
        "etiquetas":           _list("etiquetas"),
        "precio":              float(precio),
        "porcentaje_descuento": float(form.get("descuento", 0) or 0),
        "descripcion":         form.get("descripcion", ""),
        "variantes":           variantes,

        # Físico
        "stock":               int(form.get("stock", 1)) if tipo == "fisico" else None,
        "stock_minimo_alerta": _int_or_none("stock_minimo_alerta") or 0,
        "condicion":           form.get("condicion", "nuevo"),
        "marca":               form.get("marca") or None,
        "modelo":              form.get("modelo") or None,
        "sku":                 form.get("sku") or None,
        "material":            form.get("material") or None,
        "peso_gramos":         _int_or_none("peso_gramos"),
        "largo_cm":            form.get("largo_cm") or None,
        "ancho_cm":            form.get("ancho_cm") or None,
        "alto_cm":             form.get("alto_cm") or None,
        "garantia_meses":      _int_or_none("garantia_meses") or 0,
        "descripcion_garantia": form.get("descripcion_garantia") or None,

        # Digital
        "licencia":            form.get("licencia") or "personal",
        "version":             form.get("version") or None,
        "compatibilidad":      _list("compatibilidad"),
        "lenguajes":           _list("lenguajes"),
        "frameworks":          _list("frameworks"),
        "requiere_software":   _list("requiere_software"),
        "nivel_dificultad":    form.get("nivel_dificultad") or None,
        "incluye_soporte":     _bool("incluye_soporte"),
        "dias_soporte":        _int_or_none("dias_soporte"),
        "duracion_minutos":    _int_or_none("duracion_minutos"),
        "num_lecciones":       _int_or_none("num_lecciones"),
        "num_paginas":         _int_or_none("num_paginas"),
        "autor":               form.get("autor") or None,
        "editorial":           form.get("editorial") or None,
        "isbn":                form.get("isbn") or None,
        "max_descargas":       _int_or_none("max_descargas"),
        "dias_acceso":         _int_or_none("dias_acceso"),
        "preview_url":         form.get("preview_url") or None,
        "permite_reventa":     _bool("permite_reventa", False),
        "permite_modificar":   _bool("permite_modificar", True),
    }

    fotos             = form.getlist("fotos")     if tipo == "fisico"  else None
    archivo           = form.get("archivo")       if tipo == "digital" else None
    portada_digital   = form.get("portada_digital") if tipo == "digital" else None

    if tipo == "fisico"  and not fotos:   raise HTTPException(400, "Falta al menos una foto")
    if tipo == "digital" and not archivo: raise HTTPException(400, "Falta el archivo digital")

    prod = crear_producto(db=db, vendedor_id=vendedor.dni, datos=datos, fotos=fotos,
                          archivo_digital=archivo, portada_digital=portada_digital)
    return {"mensaje": "Producto publicado con éxito!", "id": str(prod.id)}


@router.get("/mis-productos")       # → GET /api/vendedor/mis-productos
async def mis_productos(
    db: Session = Depends(get_db),
    vendedor: Vendedor = Depends(get_current_vendedor)
):
    productos = (
        db.query(Producto)
        .filter(Producto.vendedor_id == vendedor.dni)
        .options(joinedload(Producto.fotos))
        .order_by(Producto.creado_en.desc())
        .all()
    )
    return [
        {
            "id": str(p.id),
            "tipo": p.tipo, "nombre": p.nombre, "categoria": p.categoria,
            "precio": float(p.precio),
            "porcentaje_descuento": float(p.porcentaje_descuento) if p.porcentaje_descuento else 0,
            "descripcion": p.descripcion or "",
            "stock": p.stock, "activo": p.activo,
            "creado_en": p.creado_en.isoformat() if p.creado_en else None,
            "fotos": [
                {"id": f.id, "url": f.url, "orden": f.orden}
                for f in sorted(p.fotos, key=lambda x: x.orden)
            ],
        }
        for p in productos
    ]


@router.get("/productos/{producto_id}")   # → GET /api/vendedor/productos/{id}
async def obtener_producto(
    producto_id: str,
    db: Session = Depends(get_db),
    vendedor: Vendedor = Depends(get_current_vendedor)
):
    p = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.vendedor_id == vendedor.dni
    ).options(joinedload(Producto.fotos)).first()
    if not p:
        raise HTTPException(404, "Producto no encontrado")
    return {
        "id": str(p.id), "tipo": p.tipo, "nombre": p.nombre, "categoria": p.categoria,
        "precio": float(p.precio),
        "porcentaje_descuento": float(p.porcentaje_descuento) if p.porcentaje_descuento else 0,
        "descripcion": p.descripcion or "", "stock": p.stock,
        "licencia": p.licencia or "personal", "archivo_key": p.archivo_key,
        "variantes": p.variantes or {},
        "fotos": [
            {"id": f.id, "url": f.url, "orden": f.orden}
            for f in sorted(p.fotos, key=lambda x: x.orden)
        ],
    }


@router.put("/productos/{producto_id}")   # → PUT /api/vendedor/productos/{id}
async def editar_producto(
    producto_id: str,
    request: Request,
    db: Session = Depends(get_db),
    vendedor: Vendedor = Depends(get_current_vendedor)
):
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.vendedor_id == vendedor.dni
    ).options(joinedload(Producto.fotos)).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    form = await request.form()

    # 1. Eliminar fotos marcadas
    for fid_str in form.getlist("eliminar_fotos"):
        if not fid_str: continue
        try:
            foto = db.query(FotoProducto).filter(
                FotoProducto.id == int(fid_str),
                FotoProducto.producto_id == producto.id
            ).first()
            if foto:
                _eliminar_foto(foto.url)
                db.delete(foto)
        except Exception as e:
            print(f"Error eliminando foto {fid_str}: {e}")
    db.flush()

    # 2. Actualizar campos
    producto.nombre               = form.get("nombre",      producto.nombre)
    producto.categoria            = form.get("categoria",   producto.categoria)
    producto.precio               = float(form.get("precio", producto.precio))
    producto.porcentaje_descuento = float(form.get("descuento", 0) or 0)
    producto.descripcion          = form.get("descripcion", producto.descripcion or "")
    if producto.tipo == "fisico" and form.get("stock"):
        producto.stock = int(form.get("stock"))

    # 3. Aplicar orden drag & drop
    orden_ids = form.getlist("orden_fotos")
    if orden_ids:
        for idx, fid_str in enumerate(orden_ids):
            try:
                foto = db.query(FotoProducto).filter(
                    FotoProducto.id == int(fid_str),
                    FotoProducto.producto_id == producto.id
                ).first()
                if foto: foto.orden = idx
            except Exception: pass
    else:
        for idx, foto in enumerate(
            db.query(FotoProducto)
            .filter(FotoProducto.producto_id == producto.id)
            .order_by(FotoProducto.orden).all()
        ):
            foto.orden = idx

    # 4. Añadir fotos nuevas
    nuevo_orden = db.query(FotoProducto).filter(FotoProducto.producto_id == producto.id).count()
    for foto_file in form.getlist("fotos"):
        if not hasattr(foto_file, "filename") or not foto_file.filename: continue
        public_id = f"{producto.id}_{nuevo_orden}_{int(datetime.now().timestamp())}"
        url = await _subir_foto_cloudinary(foto_file, public_id)
        db.add(FotoProducto(producto_id=producto.id, url=url, orden=nuevo_orden))
        nuevo_orden += 1

    db.commit()
    return {"mensaje": "Producto actualizado con éxito"}


@router.delete("/productos/{producto_id}")  # → DELETE /api/vendedor/productos/{id}
async def eliminar_producto(
    producto_id: str,
    db: Session = Depends(get_db),
    vendedor: Vendedor = Depends(get_current_vendedor)
):
    producto = db.query(Producto).filter(
        Producto.id == producto_id,
        Producto.vendedor_id == vendedor.dni
    ).options(joinedload(Producto.fotos)).first()
    if not producto:
        raise HTTPException(404, "Producto no encontrado")

    for foto in producto.fotos:
        _eliminar_foto(foto.url)
    if producto.archivo_key and not producto.archivo_key.startswith("http"):
        if os.path.exists(f"public{producto.archivo_key}"):
            os.remove(f"public{producto.archivo_key}")

    db.delete(producto)
    db.commit()
    return {"mensaje": "Producto eliminado"}

@router.get("/estadisticas")
async def estadisticas_vendedor(
    db: Session = Depends(get_db),
    vendedor: Vendedor = Depends(get_current_vendedor),
):
    from models.pedido import Pedido
    from datetime import timedelta, timezone
 
    dni  = vendedor.dni
    hoy  = datetime.now(timezone.utc)
    hace_30 = hoy - timedelta(days=30)
    hace_7  = hoy - timedelta(days=7)
 
    # ── PRODUCTOS ─────────────────────────────────────────────────────────────
    productos_q = db.query(Producto).filter(Producto.vendedor_id == dni).all()
 
    total_prod = len(productos_q)
    activos    = sum(1 for p in productos_q if p.activo)
    sin_stock  = sum(1 for p in productos_q if p.tipo == "fisico" and (p.stock or 0) == 0)
    stock_bajo = sum(1 for p in productos_q if p.tipo == "fisico" and 0 < (p.stock or 0) <= (p.stock_minimo_alerta or 3))
    fisicos    = sum(1 for p in productos_q if p.tipo == "fisico")
    digitales  = sum(1 for p in productos_q if p.tipo == "digital")
 
    cats: dict = {}
    for p in productos_q:
        k = p.categoria or "Sin categoría"
        cats[k] = cats.get(k, 0) + 1
    categorias = [{"categoria": k, "total": v} for k, v in sorted(cats.items(), key=lambda x: -x[1])]
 
    top_vendidos = []
    for p in sorted(productos_q, key=lambda x: -(x.ventas_count or 0))[:5]:
        foto = p.fotos[0].url if p.fotos else None
        top_vendidos.append({
            "id": str(p.id), "nombre": p.nombre, "categoria": p.categoria or "",
            "precio": float(p.precio), "ventas": p.ventas_count or 0,
            "stock": p.stock, "tipo": p.tipo, "foto": foto,
        })
 
    # ── PEDIDOS ───────────────────────────────────────────────────────────────
    pedidos_q = db.query(Pedido).filter(Pedido.vendedor_id == dni).all()
 
    def _cmp(fecha):
        """Normaliza TIMESTAMPTZ o naive para comparar con hoy (aware)."""
        if fecha is None:
            return None
        if hasattr(fecha, 'tzinfo') and fecha.tzinfo is None:
            return fecha.replace(tzinfo=timezone.utc)
        return fecha
 
    total_ped  = len(pedidos_q)
    entregados = sum(1 for p in pedidos_q if p.estado == "entregado")
    pendientes = sum(1 for p in pedidos_q if p.estado in ("pendiente", "confirmado", "en_preparacion"))
    cancelados = sum(1 for p in pedidos_q if p.estado == "cancelado")
    en_camino  = sum(1 for p in pedidos_q if p.estado == "en_camino")
    ultimos_30d_p = sum(1 for p in pedidos_q if _cmp(p.fecha_pedido) and _cmp(p.fecha_pedido) >= hace_30)
 
    estados_count: dict = {}
    for p in pedidos_q:
        estados_count[p.estado] = estados_count.get(p.estado, 0) + 1
 
    colores_estado = {
        "pendiente": "#f59e0b", "confirmado": "#3b82f6",
        "en_preparacion": "#8b5cf6", "en_camino": "#06b6d4",
        "entregado": "#10b981", "cancelado": "#ef4444",
    }
    estados = [{"estado": k, "total": v, "color": colores_estado.get(k, "#6b7280")} for k, v in estados_count.items()]
 
    metodos_count: dict = {}
    for p in pedidos_q:
        metodos_count[p.metodo_pago or "N/A"] = metodos_count.get(p.metodo_pago or "N/A", 0) + 1
    metodos_pago = [{"metodo": k, "total": v} for k, v in metodos_count.items()]
 
    # ── INGRESOS ──────────────────────────────────────────────────────────────
    entregados_q = [p for p in pedidos_q if p.estado == "entregado"]
 
    total_ingresos  = sum(float(p.total or 0) for p in entregados_q)
    ingresos_30d    = sum(float(p.total or 0) for p in entregados_q if _cmp(p.fecha_pedido) and _cmp(p.fecha_pedido) >= hace_30)
    ingresos_7d     = sum(float(p.total or 0) for p in entregados_q if _cmp(p.fecha_pedido) and _cmp(p.fecha_pedido) >= hace_7)
    ticket_promedio = (total_ingresos / len(entregados_q)) if entregados_q else 0
 
    from datetime import timedelta as td
    grafica_30d = []
    for i in range(29, -1, -1):
        dia = (hoy - td(days=i)).date()
        total_dia = sum(
            float(p.total or 0) for p in entregados_q
            if p.fecha_pedido and _cmp(p.fecha_pedido).date() == dia
        )
        grafica_30d.append({"dia": dia.strftime("%d/%m"), "total": round(total_dia, 2)})
 
    # ── TIENDA ────────────────────────────────────────────────────────────────
    exp = getattr(vendedor, "fecha_expiracion", None)
    if exp and hasattr(exp, 'tzinfo') and exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
 
    tienda = {
        "plan": vendedor.plan or "prueba",
        "fecha_expiracion": exp.isoformat() if exp else None,
        "visitas_totales": vendedor.visitas_totales or 0,
        "activa": vendedor.activo,
    }
 
    # ── SUGERENCIAS INTELIGENTES ──────────────────────────────────────────────
    sugerencias = []
 
    if sin_stock > 0:
        sugerencias.append({"tipo": "critica", "icono": "⚠️",
            "titulo": f"{sin_stock} producto{'s' if sin_stock > 1 else ''} sin stock",
            "desc": "Los clientes no pueden comprarlos. Reabastece para no perder ventas.",
            "accion": "Ver productos", "url": "/vendedor/dashboard/productos"})
 
    if stock_bajo > 0:
        sugerencias.append({"tipo": "alerta", "icono": "📦",
            "titulo": f"{stock_bajo} producto{'s' if stock_bajo > 1 else ''} con stock bajo",
            "desc": "Quedan pocas unidades. Considera reabastecerte pronto.",
            "accion": "Gestionar inventario", "url": "/vendedor/dashboard/productos"})
 
    if pendientes > 0:
        sugerencias.append({"tipo": "alerta", "icono": "🛒",
            "titulo": f"{pendientes} pedido{'s' if pendientes > 1 else ''} sin atender",
            "desc": "Confirma y procesa los pedidos pendientes.",
            "accion": "Ver pedidos", "url": "/vendedor/dashboard/pedidos"})
 
    if total_prod == 0:
        sugerencias.append({"tipo": "info", "icono": "🚀",
            "titulo": "Publica tu primer producto",
            "desc": "Las tiendas con al menos 5 productos reciben 3x más visitas.",
            "accion": "Publicar producto", "url": "/vendedor/dashboard/productos/nuevo"})
    elif activos < 5:
        sugerencias.append({"tipo": "info", "icono": "💡",
            "titulo": "Agrega más productos",
            "desc": "Las tiendas con más variedad venden más.",
            "accion": "Nuevo producto", "url": "/vendedor/dashboard/productos/nuevo"})
 
    if exp:
        dias_restantes = (exp - hoy).days
        if 0 < dias_restantes <= 7:
            sugerencias.append({"tipo": "critica", "icono": "⏰",
                "titulo": f"Tu plan vence en {dias_restantes} día{'s' if dias_restantes != 1 else ''}",
                "desc": "Renueva para que tu tienda siga activa.",
                "accion": "Renovar plan", "url": "/vendedor/suscripcion"})
 
    if not sugerencias:
        sugerencias.append({"tipo": "info", "icono": "🌟",
            "titulo": "¡Tu tienda está en buen estado!",
            "desc": "Comparte tu tienda en redes sociales para aumentar ventas.",
            "accion": "Compartir", "url": "/vendedor/dashboard/redes-sociales"})
 
    return {
        "productos": {
            "total": total_prod, "activos": activos, "sin_stock": sin_stock,
            "stock_bajo": stock_bajo, "fisicos": fisicos, "digitales": digitales,
            "categorias": categorias, "top_vendidos": top_vendidos,
        },
        "pedidos": {
            "total": total_ped, "entregados": entregados, "pendientes": pendientes,
            "cancelados": cancelados, "en_camino": en_camino,
            "ultimos_30d": ultimos_30d_p, "estados": estados, "metodos_pago": metodos_pago,
        },
        "ingresos": {
            "total": round(total_ingresos, 2), "ultimos_30d": round(ingresos_30d, 2),
            "ultimos_7d": round(ingresos_7d, 2), "ticket_promedio": round(ticket_promedio, 2),
            "grafica_30d": grafica_30d,
        },
        "tienda": tienda,
        "sugerencias": sugerencias,
    }


# ── URL pública de la tienda ──────────────────────────────────────────────────

@router.get("/mi-url")          # → GET /api/vendedor/mi-url
async def mi_url_tienda(
    vendedor: Vendedor = Depends(get_current_vendedor),
):
    """
    Devuelve la URL pública única de la tienda del vendedor autenticado.
    Usa slug_tienda(nombre_tienda, municipio) para construir la dirección.
    """
    from core.slug import slug_tienda as _slug

    slug        = _slug(vendedor.nombre_tienda, vendedor.municipio)
    frontend    = os.getenv("FRONTEND_URL", "http://localhost:3000")
    url_publica = f"{frontend}/fenix/tiendas/{slug}"

    return {
        "slug":       slug,
        "url":        url_publica,
        "nombre":     vendedor.nombre_tienda,
        "municipio":  vendedor.municipio,
    }