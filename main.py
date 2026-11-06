# backend/main.py — CORREGIDO
from fastapi import FastAPI, UploadFile, File, Form
from datetime import datetime, timedelta
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from scheduler import iniciar_scheduler
from notifications.scheduler import start_scheduler
import os
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from routes.admin import router as admin_router
from routes.vendedor import router as vendedor_router
from routes.public import router as public_router
from routes.carrito import router as carrito_router
from routes.auth import router as auth_router
from routes.favorito import router as favorito_router
from routes.pedidos import router as pedidos_router
from routes.direcciones import router as direcciones_router
from routes.chat import router as chat_router
from routes.social import router as social_router, router_publico as social_publico_router
from routes.descargas import router as descargas_router
from routes.reportes import router as reportes_router
from routes.google_auth import router as google_router
import cloudinary
from routes.notificaciones import router as notificaciones_router
cloudinary.config(
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key    = os.getenv("CLOUDINARY_API_KEY"),
    api_secret = os.getenv("CLOUDINARY_API_SECRET"),
)

app = FastAPI(title="Mercado Fénix 2025")

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "https://mercadofenix-backend.onrender.com",
    "https://mercadofenix.vercel.app",
]
env_origins = os.getenv("CORS_ORIGINS")
if env_origins:
    for o in env_origins.split(","):
        o2 = o.strip()
        if o2 and o2 not in origins:
            origins.append(o2)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Cart-Session"],
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
app.include_router(vendedor_router, prefix="/api")  # evita duplicados; usa rutas internas
app.include_router(reportes_router, prefix="/api")
app.include_router(public_router)
app.include_router(carrito_router)
app.include_router(auth_router)
app.include_router(favorito_router)
app.include_router(pedidos_router)
app.include_router(direcciones_router)
app.include_router(chat_router)
app.include_router(social_router)
app.include_router(social_publico_router, prefix="/api")
app.include_router(descargas_router)
app.include_router(google_router, prefix="/api")
app.include_router(notificaciones_router)
@app.get("/")
async def root():
    return {"message": "Mercado Fénix API - PEDIDOS IMPLEMENTADOS ✅ - 2025 🔥"}


@app.get("/ping")
async def ping():
    """Endpoint ligero sin DB ni auth para mantener vivo el backend en Render (free tier)."""
    return {"status": "ok", "message": "Backend despierto"}


# === DESPERTADOR / KEEP-ALIVE PARA RENDER (free tier se duerme tras inactividad) ===
_keepalive_scheduler = AsyncIOScheduler(timezone="America/Tegucigalpa")


async def _keepalive_ping():
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        return
    url = url.rstrip("/") + "/ping"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                print("[KEEP-ALIVE] Ping exitoso a", url)
            else:
                print(f"[KEEP-ALIVE] Ping respondió {resp.status_code}")
    except Exception as e:
        print(f"[KEEP-ALIVE] Error haciendo ping: {e}")


def iniciar_keepalive():
    """Arranca el auto-ping solo si estamos en Render (RENDER_EXTERNAL_URL definido)."""
    if not os.getenv("RENDER_EXTERNAL_URL"):
        print("[KEEP-ALIVE] No está en Render, se omite auto-ping.")
        return
    if _keepalive_scheduler.running:
        return
    interval = int(os.getenv("RENDER_KEEPALIVE_INTERVAL_MIN", "10"))
    _keepalive_scheduler.add_job(
        _keepalive_ping,
        trigger=IntervalTrigger(minutes=interval),
        id="keepalive_render",
        replace_existing=True,
    )
    _keepalive_scheduler.start()
    print(f"[KEEP-ALIVE] Iniciado — auto-ping cada {interval} min a {os.getenv('RENDER_EXTERNAL_URL')}/ping")


vendedores_db = {}

@app.on_event("startup")
async def startup_event():
    iniciar_scheduler()
    
@app.on_event("startup")
async def begin_event():
    start_scheduler

@app.on_event("startup")
async def start_keepalive():
    iniciar_keepalive()

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