"""
Crea/actualiza el usuario demo de la constructora 'Conaltura (DEMO)' para probar
el portal B2B (E3). Idempotente. Credenciales por env o default de desarrollo.

Uso:
    python scripts/seed_constructora_demo.py
    DEMO_CONSTRUCTORA_PASSWORD=xxx python scripts/seed_constructora_demo.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("DEMO_CONSTRUCTORA_EMAIL", "demo@conaltura-demo.com")
PASSWORD = os.getenv("DEMO_CONSTRUCTORA_PASSWORD", "conaltura2026")


def main():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    cur.execute("SELECT id FROM constructoras WHERE nombre = 'Conaltura (DEMO)' ORDER BY id LIMIT 1")
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO constructoras (nombre, activa) VALUES ('Conaltura (DEMO)', TRUE) RETURNING id")
        row = cur.fetchone()
    constructora_id = row[0]

    cur.execute("""
        INSERT INTO constructora_users (constructora_id, email, password_hash, nombre, activo)
        VALUES (%s, %s, crypt(%s, gen_salt('bf')), %s, TRUE)
        ON CONFLICT (email) DO UPDATE
            SET password_hash = crypt(%s, gen_salt('bf')), activo = TRUE
    """, (constructora_id, EMAIL, PASSWORD, "Demo Conaltura", PASSWORD))
    conn.commit()
    conn.close()

    print(f"OK: constructora demo id={constructora_id}")
    print(f"    usuario: {EMAIL}")
    print(f"    clave:   {PASSWORD}")


if __name__ == "__main__":
    main()
