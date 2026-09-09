# backend/routes/vendedor.py
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from core.database import get_db
from core.auth import get_current_vendedor
from crud.producto import crear_producto
from models.producto import Producto
from sqlalchemy.orm import joinedload

router = APIRouter(prefix="/vendedor", tags=["vendedor"])

@router.post("/productos")
async def crear_nuevo_producto(
    request: Request,
    db: Session = Depends(get_db),
    vendedor = Depends(get_current_vendedor)
):
    # Obtener form data (maneja str y UploadFile)
    form_data = await request.form()

    # Campos conocidos
    known_fields = ["tipo", "categoria", "nombre", "precio", "descripcion", "descuento", "stock", "licencia"]
    
    datos = {field: form_data.get(field) for field in known_fields}
    datos["descuento"] = float(datos["descuento"] or 0)
    datos["precio"] = float(datos["precio"])
    if datos["tipo"] == "fisico":
        datos["stock"] = int(datos["stock"] or 1)
    else:
        datos["stock"] = None

    # Variantes (campos extra dinámicos)
    variantes = {}
    for key, value in form_data.items():
        if key not in known_fields and key not in ["fotos", "archivo"]:
            variantes[key] = value  # value es str

    datos["variantes"] = variantes

    # Fotos y archivo (son listas o single UploadFile)
    fotos = form_data.getlist("fotos")
    archivo_digital = form_data.get("archivo")

    # Validaciones
    if not datos["tipo"] or not datos["categoria"] or not datos["nombre"] or not datos["precio"]:
        raise HTTPException(400, "Campos requeridos faltantes")
    if datos["tipo"] == "digital" and not archivo_digital:
        raise HTTPException(400, "Archivo digital requerido")
    if datos["tipo"] == "fisico" and len(fotos) == 0:
        raise HTTPException(400, "Al menos una foto requerida")

    # Crear
    producto = crear_producto(
        db=db,
        vendedor_id=vendedor.dni,
        datos=datos,
        fotos=fotos if datos["tipo"] == "fisico" else None,
        archivo_digital=archivo_digital if datos["tipo"] == "digital" else None
    )

    return {"mensaje": "Producto creado con éxito", "id": producto.id}

@router.get("/productos/buscar")
def buscar_productos(q: str, limit: int = 5, db: Session = Depends(get_db)):
    results = db.query(Producto).filter(
        Producto.nombre.ilike(f"%{q}%"),
        Producto.activo == True
    ).options(joinedload(Producto.fotos)).limit(limit).all()
    return [{"id": str(p.id), "nombre": p.nombre, "categoria": p.categoria,
             "precio": float(p.precio), "descripcion": p.descripcion or "",
             "tipo": p.tipo, "stock": p.stock,
             "fotos": [{"url": f.url} for f in p.fotos[:1]],
             "variantes": p.variantes or {}} for p in results]