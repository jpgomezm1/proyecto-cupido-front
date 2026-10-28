"""
Crea inmuebles de prueba para una cuenta de prueba (chat_users.origen = 'prueba_ui'), copiando los datos
y las fotos de avisos reales de Wasi. Quedan con es_prueba = TRUE (migración 065): su dueño los ve en
Mis inmuebles, compradores, ficha y compartir, pero no les aparecen a los demás agentes.

Perfiles (uno por inmueble), pensados para el journey de Findy:
  1. Apto en Laureles, 80–110 m², 3 hab, $550–700 M
  2. Apto en El Poblado, 2 hab, $650–950 M
  3. Casa en Envigado, $900–1.600 M

Sin --aplicar solo muestra qué avisos copiaría. Necesita la migración 065 aplicada.

    venv/Scripts/python scripts/crear_inmuebles_prueba.py prueba@getfynder.com
    venv/Scripts/python scripts/crear_inmuebles_prueba.py prueba@getfynder.com --aplicar
"""
import io
import os
import sys

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services.db import fetch_all, fetch_one, get_db  # noqa: E402
from src.services.listing_service import crear_listing  # noqa: E402
from src.services.redact import redact_phones  # noqa: E402

PERFILES = [
    ("Apto en Laureles", "p.tipo_propiedad ILIKE 'apartamento%%' AND p.zona ILIKE '%%laureles%%' "
                         "AND p.area_construida BETWEEN 80 AND 110 AND p.habitaciones = 3 "
                         "AND p.precio BETWEEN 550000000 AND 700000000"),
    ("Apto en El Poblado", "p.tipo_propiedad ILIKE 'apartamento%%' AND p.zona ILIKE '%%poblado%%' "
                           "AND p.habitaciones = 2 AND p.precio BETWEEN 650000000 AND 950000000"),
    ("Casa en Envigado", "p.tipo_propiedad ILIKE 'casa%%' AND p.ciudad ILIKE 'envigado' "
                         "AND p.precio BETWEEN 900000000 AND 1600000000"),
]

CAMPOS = ("precio", "area_construida", "ciudad", "zona", "tipo_propiedad", "habitaciones", "banos",
          "parqueaderos", "estrato", "piso", "ano_construccion", "administracion",
          "amenidades_internas", "amenidades_externas", "latitud", "longitud")


def _fuente(cur, condicion: str):
    return fetch_one(cur, f"""
        SELECT p.* FROM propiedades p
        WHERE p.activa AND p.fuente ILIKE 'wasi' AND NOT p.es_prueba
          AND p.imagenes_urls IS NOT NULL AND COALESCE(p.total_imagenes, 0) >= 5
          AND COALESCE(p.descripcion_ai, p.descripcion) IS NOT NULL
          AND {condicion}
        ORDER BY p.fecha_ultima_validacion DESC NULLS LAST LIMIT 1
    """)


def main(email: str, aplicar: bool) -> None:
    with get_db() as db:
        cur = db.cursor
        u = fetch_one(cur, "SELECT id, nombre, telefono, origen FROM chat_users WHERE email = %s", (email,))
        if not u:
            sys.exit(f"No existe la cuenta {email}.")
        if u["origen"] != "prueba_ui":
            sys.exit(f"{email} no es una cuenta de prueba (origen = {u['origen']!r}): no se le crean inmuebles de prueba.")
        if not u["telefono"]:
            sys.exit("La cuenta no tiene teléfono: los inmuebles se asocian al dueño por teléfono.")
        ya = fetch_one(cur, """SELECT COUNT(*) n FROM propiedades WHERE es_prueba AND activa
                               AND RIGHT(agente_captador_telefono, 10) = RIGHT(%s, 10)""", (u["telefono"],))["n"]
        print(f"Cuenta: {u['nombre']} (id {u['id']}) · inmuebles de prueba activos: {ya}\n")

        elegidos = []
        for etiqueta, condicion in PERFILES:
            p = _fuente(cur, condicion)
            if not p:
                print(f"  {etiqueta}: no encontré un aviso de Wasi que sirva")
                continue
            print(f"  {etiqueta}: copia de #{p['id']} · {p['precio_texto'] or p['precio']} · "
                  f"{p['area_construida']} m² · {p['habitaciones'] or '?'} hab · {p['total_imagenes']} fotos · "
                  f"{p['zona'] or p['ciudad']}")
            elegidos.append((etiqueta, p))

        if not aplicar:
            print(f"\nSe crearían {len(elegidos)}. Corre con --aplicar para hacerlo.")
            return

    creados = []
    for etiqueta, p in elegidos:
        data = {k: p.get(k) for k in CAMPOS}
        data["area_construida"] = float(p["area_construida"]) if p.get("area_construida") else None
        data["tipo_negocio"] = "Venta"
        data["titulo"] = f"[Prueba] {p.get('titulo') or etiqueta}"[:200]
        data["descripcion"] = redact_phones(p.get("descripcion_ai") or p.get("descripcion") or "", cut_signatures=True)
        # Sin fotos queda como borrador (inactivo): así no hay ni un instante en que lo vean otros agentes.
        res = crear_listing(u["telefono"], data, agente_nombre=u["nombre"], agente_user_id=u["id"], canal="script_prueba")
        imgs = [x for x in (p.get("imagenes_urls") or "").split("|") if x]
        with get_db() as db:
            db.cursor.execute("""
                UPDATE propiedades SET es_prueba = TRUE, imagenes_urls = %s, total_imagenes = %s,
                       imagen_principal = %s, activa = TRUE
                WHERE id = %s
            """, ("|".join(imgs), len(imgs), imgs[0] if imgs else None, res["id"]))
            db.conn.commit()
        creados.append(res["id"])
        print(f"  ✅ #{res['id']} {data['titulo'][:60]} · {res['precio_legible']}")

    print(f"\nCreados: {creados}. Para retirarlos: scripts/retirar_inmuebles_prueba.py {' '.join(map(str, creados))} --aplicar")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    main(args[0], "--aplicar" in sys.argv)
