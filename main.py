# backend/main.py — CORREGIDO
from fastapi import FastAPI, UploadFile, File, Form
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from scheduler import iniciar_scheduler
import os
from routes.admin import router as admin_router
from routes.vendedor import router as vendedor_router
from routes.public import router as public_router
from routes.carrito import router as carrito_router
from routes.auth import router as auth_router
from routes.favorito import router as favorito_router
from routes.pedidos import router as pedidos_router
from routes.direcciones import router as direcciones_router
from routes.chat import router as chat_router
from routes.social import router as social_router
from routes.descargas import router as descargas_router
from routes.reportes import router as reportes_router
from routes.google_auth import router as google_router

app = FastAPI(title="Mercado Fénix 2025")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === ARCHIVOS ESTÁTICOS ===
logo_dir = os.path.join(os.path.dirname(__file__), "public", "logos")
os.makedirs(logo_dir, exist_ok=True)
os.makedirs("public/uploads/comprobantes", exist_ok=True)

app.mount("/logos", StaticFiles(directory=logo_dir, html=False), name="logos")
app.mount("/uploads", StaticFiles(directory="public/uploads"), name="uploads")
app.mount("/digitales", StaticFiles(directory="public/digitales"), name="digitales")


# === ROUTERS ===
app.include_router(admin_router, prefix="/api")

# ✅ FIX: vendedor_router estaba registrado DOS veces con prefijos distintos,
# causando que las rutas se duplicaran y generaran conflictos en el routing.
# Elegí /api/vendedor como prefijo canónico. Si tus rutas internas ya incluyen
# /vendedor, dejá solo prefix="/api". Ajustá según tu routes/vendedor.py.
app.include_router(vendedor_router, prefix="/api")
app.include_router(vendedor_router, prefix="/api/vendedor")  # ELIMINAR ESTE REGISTRO DUPLICADO SI YA TENÉS /api/vendedor EN ELLO
app.include_router(reportes_router, prefix="/api")  # Asegúrate de que reportes_router tenga rutas únicas y no se dupliquen con admin_router o vendedor_router
app.include_router(public_router)
app.include_router(carrito_router)
app.include_router(auth_router)
app.include_router(favorito_router)
app.include_router(pedidos_router)
app.include_router(direcciones_router)
app.include_router(chat_router)
app.include_router(social_router)
app.include_router(descargas_router)
app.include_router(google_router, prefix="/api")
@app.get("/")
async def root():
    return {"message": "Mercado Fénix API - PEDIDOS IMPLEMENTADOS ✅ - 2025 🔥"}


vendedores_db = {}

@app.on_event("startup")
async def startup_event():
    iniciar_scheduler()


@app.post("/api/facturas/generar")
async def generar_factura(
    vendedor_id: str = Form(...),
    emisor: str = Form(...),
    plan: str = Form(...),
    inicio: str = Form(...),
    fin: str = Form(...),
    meses: int = Form(...),
    total: float = Form(...),
    pdf: UploadFile = File(...)
):
    pdf_path = f"facturas/factura_{vendedor_id}_{datetime.now().strftime('%Y%m%d')}.pdf"
    os.makedirs("facturas", exist_ok=True)
    with open(pdf_path, "wb") as f:
        f.write(await pdf.read())

    inicio_dt = datetime.strptime(inicio, "%Y-%m-%d")
    fin_dt = datetime.strptime(fin, "%Y-%m-%d")
    dias_nuevos = meses * 30

    if vendedor_id in vendedores_db and vendedores_db[vendedor_id].get("fecha_expiracion"):
        base = datetime.fromisoformat(vendedores_db[vendedor_id]["fecha_expiracion"])
        nueva_exp = base + timedelta(days=dias_nuevos) if base > datetime.now() else datetime.now() + timedelta(days=dias_nuevos)
    else:
        nueva_exp = datetime.now() + timedelta(days=dias_nuevos)

    vendedores_db[vendedor_id] = {
        "plan": plan,
        "fecha_expiracion": nueva_exp.isoformat(),
        "activo": True
    }

    return {"message": "Factura generada y cuenta activada", "expiracion": nueva_exp.isoformat()}