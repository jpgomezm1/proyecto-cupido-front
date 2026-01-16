"""
Worker para procesar jobs de Redis Queue.
Ejecutar con: python worker.py
"""
import os
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

    # Crear worker con la conexión (API moderna de RQ)
    worker = Worker([queue], connection=conn)
    print(f"[WORKER] Escuchando cola 'captures'...")
    worker.work()
