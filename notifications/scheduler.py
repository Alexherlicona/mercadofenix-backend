# backend/notifications/scheduler.py
#
# Tarea periódica: generar sugerencias de productos según el historial de
# compras de cada cliente, una vez al día.
#
# Requiere: pip install apscheduler
#
# En main.py, al arrancar la app (después de crear `app = FastAPI()`):
#
#   from notifications.scheduler import iniciar_scheduler
#
#   @app.on_event("startup")
#   async def _startup():
#       iniciar_scheduler()
#
# ── LIMITACIÓN IMPORTANTE ─────────────────────────────────────────────────────
# Este scheduler vive DENTRO del proceso de un solo worker de uvicorn/gunicorn.
# Si despliegas con varios workers (--workers N) o varias instancias/réplicas
# detrás de un balanceador, el job se dispararía una vez POR worker, mandando
# la misma sugerencia varias veces al mismo cliente.
#
# Para ese caso, usa en su lugar el endpoint protegido
# POST /api/notificaciones/admin/generar-sugerencias (ver routes/notificaciones.py)
# llamado UNA vez al día desde un cron externo (cron-job.org, GitHub Actions
# con `schedule:`, Render Cron Jobs, etc.) — así solo se ejecuta una vez sin
# importar cuántos workers/réplicas tengas corriendo. En ese caso, NO llames
# iniciar_scheduler() en main.py para evitar la duplicación.

import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from core.database import SessionLocal

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="America/Tegucigalpa")


async def _job_sugerencias():
    """Corre en un `db` propio, separado del de cualquier request en curso."""
    from routes.notificaciones import generar_sugerencias_preferencias

    db = SessionLocal()
    try:
        enviados = await generar_sugerencias_preferencias(db)
        logger.info(f"[SCHEDULER] Sugerencias generadas para {enviados} clientes")
    except Exception as e:
        logger.error(f"[SCHEDULER] Error generando sugerencias: {e}")
    finally:
        db.close()


def start_scheduler():
    if _scheduler.running:
        return
    # Todos los días a las 9:00 AM hora Honduras — un buen horario para que
    # el cliente lo vea al revisar el teléfono en la mañana, sin ser tan
    # temprano que se sienta invasivo.
    _scheduler.add_job(
        _job_sugerencias, "cron", hour=9, minute=0,
        id="sugerencias_diarias", replace_existing=True,
    )
    _scheduler.start()
    logger.info("[SCHEDULER] Iniciado — sugerencias diarias a las 9:00 AM (America/Tegucigalpa)")