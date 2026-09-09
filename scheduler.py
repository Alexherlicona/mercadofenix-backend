# backend/scheduler.py
# Limpieza automática de pedidos entregados/cancelados con más de 7 días.
# Se integra con APScheduler y arranca junto al servidor FastAPI.
#
# Instalar dependencia si no la tienes:
#   pip install apscheduler

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime, timedelta
from core.database import SessionLocal
from models.pedido import Pedido
import logging

logger = logging.getLogger("scheduler")


def limpiar_pedidos_antiguos():
    """
    Archiva pedidos entregados o cancelados con más de 7 días.
    Se ejecuta una vez al día automáticamente.
    """
    db = SessionLocal()
    try:
        limite = datetime.utcnow() - timedelta(days=7)

        # Pedidos entregados con fecha_entrega_real > 7 días
        entregados = db.query(Pedido).filter(
            Pedido.activo == True,
            Pedido.estado == "entregado",
            Pedido.fecha_entrega_real <= limite
        ).all()

        # Pedidos cancelados sin fecha_entrega_real → usar fecha_pedido
        cancelados = db.query(Pedido).filter(
            Pedido.activo == True,
            Pedido.estado == "cancelado",
            Pedido.fecha_entrega_real == None,
            Pedido.fecha_pedido <= limite
        ).all()

        total = len(entregados) + len(cancelados)
        for p in entregados + cancelados:
            p.activo = False

        db.commit()

        if total > 0:
            logger.info(f"[Scheduler] {total} pedidos archivados automáticamente")
        else:
            logger.info("[Scheduler] Sin pedidos para archivar")

    except Exception as e:
        logger.error(f"[Scheduler] Error en limpieza: {e}")
        db.rollback()
    finally:
        db.close()


def iniciar_scheduler():
    """Llama esto desde main.py al arrancar la app."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        limpiar_pedidos_antiguos,
        trigger=IntervalTrigger(hours=24),   # Corre una vez al día
        id="limpiar_pedidos",
        replace_existing=True,
        next_run_time=datetime.utcnow()       # Corre también al arrancar el servidor
    )
    scheduler.start()
    logger.info("[Scheduler] Iniciado — limpieza de pedidos cada 24h")
    return scheduler