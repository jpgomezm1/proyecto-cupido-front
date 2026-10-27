"""
Cuenta de prueba para recorrer la app como un agente nuevo (journey de UX).

Crea (o reusa y le cambia la clave) qa-journey@fynder.test: activa, sin celular verificado y sin
términos aceptados, como queda alguien que acaba de llegar. La clave NO se imprime: se guarda en
logs/qa_journey.txt (logs/ está en .gitignore). Correrlo otra vez genera una clave nueva.

    venv/Scripts/python scripts/crear_cuenta_qa.py
    venv/Scripts/python scripts/crear_cuenta_qa.py --desactivar   # al terminar el journey
"""
import io
import os
import secrets
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services.db import get_db, scalar  # noqa: E402

EMAIL = "qa-journey@fynder.test"
DESTINO = os.path.join(RAIZ, "logs", "qa_journey.txt")


def main() -> None:
    with get_db() as db:
        cur = db.cursor
        uid = scalar(cur, "SELECT id FROM chat_users WHERE lower(email) = %s", (EMAIL,))
        if "--desactivar" in sys.argv:
            if uid:
                cur.execute("UPDATE chat_users SET activo = FALSE WHERE id = %s", (uid,))
                db.conn.commit()
            print(f"Cuenta de prueba desactivada (id {uid}).")
            return
        clave = secrets.token_urlsafe(12)
        if uid:
            cur.execute("UPDATE chat_users SET password_hash = crypt(%s, gen_salt('bf')), activo = TRUE WHERE id = %s",
                        (clave, uid))
        else:
            uid = scalar(cur, """
                INSERT INTO chat_users (email, nombre, password_hash, activo, origen, telefono_verificado)
                VALUES (%s, 'Agente de Prueba', crypt(%s, gen_salt('bf')), TRUE, 'qa', FALSE) RETURNING id
            """, (EMAIL, clave))
        db.conn.commit()
    os.makedirs(os.path.dirname(DESTINO), exist_ok=True)
    with open(DESTINO, "w", encoding="utf-8") as f:
        f.write(f"https://getfynder.com/entrar\ncorreo: {EMAIL}\nclave: {clave}\n")
    print(f"Cuenta de prueba lista (id {uid}). El acceso quedó en {DESTINO}")


if __name__ == "__main__":
    main()
