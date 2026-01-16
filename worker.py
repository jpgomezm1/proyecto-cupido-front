"""
Worker para procesar jobs de Redis Queue.
Ejecutar con: python worker.py
"""
import os
import redis
from rq import Worker, Queue, Connection

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')

# SSL fix para Heroku Redis (usa rediss:// con SSL)
if redis_url.startswith('rediss://'):
    conn = redis.from_url(redis_url, ssl_cert_reqs=None)
else:
    conn = redis.from_url(redis_url)

if __name__ == '__main__':
    print(f"[WORKER] Iniciando worker...")
    print(f"[WORKER] Redis URL: {redis_url[:30]}...")
    with Connection(conn):
        worker = Worker(['captures'])
        print(f"[WORKER] Escuchando cola 'captures'...")
        worker.work()
