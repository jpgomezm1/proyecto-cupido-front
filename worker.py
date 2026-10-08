"""
Worker para procesar jobs de Redis Queue.
Ejecutar con: python worker.py
"""
import os
from datetime import datetime
import redis
from rq import Worker, Queue
import sentry_sdk
from sentry_sdk.integrations.rq import RqIntegration

# Inicializar Sentry para el worker
sentry_dsn = os.getenv('SENTRY_DSN')
if sentry_dsn:
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[RqIntegration()],
        traces_sample_rate=0.1,
        environment=os.getenv('FLASK_ENV', 'production'),
    )
    print("[WORKER] Sentry inicializado")

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

# SSL fix para Heroku Redis (usa rediss:// con SSL)
if redis_url.startswith('rediss://'):
    conn = redis.from_url(redis_url, ssl_cert_reqs=None)
else:
    conn = redis.from_url(redis_url)

if __name__ == '__main__':
    print(f"[WORKER] Iniciando worker...")
    print(f"[WORKER] Redis URL: {redis_url[:30]}...")

    # Crear la cola con la conexión
    queue = Queue('captures', connection=conn)

    # Revalidación continua del inventario (acuerdo de frescura ≤ 8 días).
    # Corre en un hilo del proceso padre; los jobs de RQ van en procesos hijos.
    if os.getenv('REVALIDACION_ENABLED', 'true').lower() == 'true':
        from apscheduler.schedulers.background import BackgroundScheduler
        from src.services.disponibilidad_service import revalidar_lote

        def _revalidar():
            try:
                print(f"[REVALIDACION] {revalidar_lote()}")
            except Exception as e:  # noqa: BLE001 — nunca tumbar el worker
                print(f"[REVALIDACION] Error: {e}")

        scheduler = BackgroundScheduler()
        scheduler.add_job(_revalidar, 'interval',
                          minutes=int(os.getenv('REVALIDACION_INTERVALO_MIN', '30')),
                          id='revalidacion', next_run_time=datetime.now(),
                          max_instances=1, coalesce=True)
        scheduler.start()
        print("[WORKER] Revalidación de inventario programada")

    # Criterios de los pedidos nuevos con IA (búsqueda inversa inmueble -> compradores).
    if os.getenv('PEDIDOS_IA_ENABLED', 'true').lower() == 'true':
        from apscheduler.schedulers.background import BackgroundScheduler
        from src.services.pedidos_ia import estructurar_pendientes

        def _pedidos():
            try:
                print(f"[PEDIDOS-IA] {estructurar_pendientes(limit=100, concurrencia=4)}")
            except Exception as e:  # noqa: BLE001 — nunca tumbar el worker
                print(f"[PEDIDOS-IA] Error: {e}")

        sched_pedidos = BackgroundScheduler()
        sched_pedidos.add_job(_pedidos, 'interval', minutes=15, id='pedidos_ia',
                              next_run_time=datetime.now(), max_instances=1, coalesce=True)
        sched_pedidos.start()
        print("[WORKER] Estructuración de pedidos programada (cada 15 min)")

    # Fichas del buscador v3 para inmuebles nuevos o editados: reglas primero
    # (gratis) e IA solo si falta lo esencial. FICHAS_IA=false las deja solo con reglas.
    if os.getenv('FICHAS_ENABLED', 'true').lower() == 'true':
        from apscheduler.schedulers.background import BackgroundScheduler
        from src.services.ficha_service import enriquecer

        def _fichas():
            try:
                con_ia = os.getenv('FICHAS_IA', 'true').lower() == 'true'
                print(f"[FICHAS] {enriquecer(limite=60, hilos=3, con_ia=con_ia)}")
            except Exception as e:  # noqa: BLE001 — nunca tumbar el worker
                print(f"[FICHAS] Error: {e}")

        sched_fichas = BackgroundScheduler()
        sched_fichas.add_job(_fichas, 'interval', minutes=30, id='fichas',
                             next_run_time=datetime.now(), max_instances=1, coalesce=True)
        sched_fichas.start()
        print("[WORKER] Fichas del buscador programadas (cada 30 min)")

    # Alertas de cruce: inmuebles nuevos y cambios de precio contra los clientes de
    # cada agente (sin IA: SQL y el puntaje del buscador), y su resumen por correo.
    if os.getenv('ALERTAS_ENABLED', 'true').lower() == 'true':
        from apscheduler.schedulers.background import BackgroundScheduler
        from src.services import alertas_service

        def _alertas():
            try:
                print(f"[ALERTAS] {alertas_service.generar()}")
                print(f"[ALERTAS] correo {alertas_service.enviar_resumenes()}")
            except Exception as e:  # noqa: BLE001 — nunca tumbar el worker
                print(f"[ALERTAS] Error: {e}")

        sched_alertas = BackgroundScheduler()
        sched_alertas.add_job(_alertas, 'interval', minutes=30, id='alertas',
                              next_run_time=datetime.now(), max_instances=1, coalesce=True)
        sched_alertas.start()
        print("[WORKER] Alertas de cruce programadas (cada 30 min)")

    # Correos de recordatorio del plan (por vencer / vencido), idempotentes.
    if os.getenv('CORREOS_RECORDATORIO_ENABLED', 'true').lower() == 'true':
        from apscheduler.schedulers.background import BackgroundScheduler
        from src.services.correo_service import recordatorios_plan

        def _recordatorios():
            try:
                print(f"[CORREOS] Recordatorios de plan: {recordatorios_plan()}")
            except Exception as e:  # noqa: BLE001 — nunca tumbar el worker
                print(f"[CORREOS] Error: {e}")

        sched_correos = BackgroundScheduler()
        sched_correos.add_job(_recordatorios, 'interval', hours=6, id='correos_plan',
                              next_run_time=datetime.now(), max_instances=1, coalesce=True)
        sched_correos.start()
        print("[WORKER] Recordatorios de plan programados (cada 6 h)")

    # Crear worker con la conexión (API moderna de RQ)
    worker = Worker([queue], connection=conn)
    print(f"[WORKER] Escuchando cola 'captures'...")
    worker.work()
