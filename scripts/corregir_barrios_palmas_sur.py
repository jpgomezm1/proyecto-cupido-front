"""
Corrige dos alias del catálogo de barrios que inflaban comunas en el Índice Fynder (27-oct-2026):

  1. «Las Palmas», «Palmas», «Av. Las Palmas», «El Poblado Las Palmas»… apuntaban al barrio oficial
     Las Palmas (comuna 9, Buenos Aires). En el mercado es el corredor de la Av. Las Palmas en
     El Poblado: pasan a «Vía Las Palmas» (comuna 14). «Las Palmas parte baja» sí es el oficial y
     se queda; «alquiler alto de las palmas» va a Alto de las Palmas (Envigado), como sus parecidos.
  2. «Sur» era un barrio de Guayabal (comuna 15), pero es «la zona sur» en general: el alias deja
     de decidir el barrio (barrio_id NULL → se usa el título o las coordenadas) y el barrio pasa a
     tipo 'sector' (no se asigna por cercanía).

Después reasigna los inmuebles y pedidos que estaban en esos barrios y muestra cómo quedan las
comunas en el índice de octubre. Sin --aplicar hace todo en una transacción y la deshace.

    venv/Scripts/python scripts/corregir_barrios_palmas_sur.py            # simulación
    venv/Scripts/python scripts/corregir_barrios_palmas_sur.py --aplicar  # escribe
"""
import io
import os
import sys
from datetime import date

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.services import barrios_service as bs, indice_service as ix  # noqa: E402
from src.services.db import fetch_all, fetch_one, get_db  # noqa: E402

LAS_PALMAS_OFICIAL = 9       # comuna 9 - Buenos Aires
VIA_LAS_PALMAS = 693         # comuna 14 - El Poblado
ALTO_LAS_PALMAS_ENV = 6      # Envigado
SUR_GUAYABAL = 111           # comuna 15 - Guayabal
COMUNAS = ("9 - Buenos Aires", "14 - El Poblado", "15 - Guayabal")


def _comunas(cur):
    filas = {f["zona"]: f for f in ix._calcular_filas(cur, date(2026, 10, 1))}
    for c in COMUNAS:
        f = filas.get(c)
        if f:
            print(f"   {c:20} en venta {f['activos']:5}  aptos {f['aptos']:5}  m² {f['m2_mediana'] or 0:>12,}  pedidos {f['pedidos']}")
    top = sorted((f for f in filas.values() if f["nivel"] != "total" and f["m2_mediana"] and f["aptos"] >= ix.MIN_APTOS),
                 key=lambda f: -f["m2_mediana"])[:5]
    print("   m² más alto (con 30+ apartamentos): " + "; ".join(f"{f['zona']} {f['m2_mediana'] / 1e6:.1f} M" for f in top))


def main(aplicar: bool) -> None:
    with get_db() as db:
        cur = db.cursor
        # Que los ids sean los que creemos (si el catálogo cambió, no tocar nada).
        for bid, nombre in ((LAS_PALMAS_OFICIAL, "Las Palmas"), (VIA_LAS_PALMAS, "Vía Las Palmas"),
                            (ALTO_LAS_PALMAS_ENV, "Alto de las Palmas"), (SUR_GUAYABAL, "Sur")):
            b = fetch_one(cur, "SELECT nombre FROM barrios WHERE id = %s", (bid,))
            assert b and b["nombre"] == nombre, f"El barrio {bid} no es {nombre}: {b}"

        print("Antes (índice de octubre):")
        _comunas(cur)
        props = [f["propiedad_id"] for f in fetch_all(cur, "SELECT propiedad_id FROM propiedad_barrio WHERE barrio_id = ANY(%s)",
                                                       ([LAS_PALMAS_OFICIAL, SUR_GUAYABAL],))]
        pedidos = [f["id"] for f in fetch_all(cur, "SELECT id FROM pedidos WHERE barrio_ids && %s::int[]",
                                              ([LAS_PALMAS_OFICIAL, SUR_GUAYABAL],))]
        print(f"\nInmuebles a reasignar: {len(props)} · pedidos: {len(pedidos)}")

        cur.execute("""
            UPDATE barrio_alias SET barrio_id = %s
            WHERE barrio_id = %s AND alias_clave = 'alquiler alto de las palmas'
        """, (ALTO_LAS_PALMAS_ENV, LAS_PALMAS_OFICIAL))
        cur.execute("""
            UPDATE barrio_alias SET barrio_id = %s
            WHERE barrio_id = %s AND alias_clave <> 'las palmas parte baja'
              AND municipio_clave IN ('medellin', 'el poblado', '')
        """, (VIA_LAS_PALMAS, LAS_PALMAS_OFICIAL))
        print(f"Alias de Las Palmas → Vía Las Palmas: {cur.rowcount}")
        cur.execute("UPDATE barrio_alias SET barrio_id = NULL WHERE barrio_id = %s", (SUR_GUAYABAL,))
        print(f"Alias de «Sur» (Guayabal) que dejan de decidir: {cur.rowcount}")
        cur.execute("UPDATE barrios SET tipo = 'sector' WHERE id = %s", (SUR_GUAYABAL,))

        cat = bs.Catalogo(cur)
        if props:
            filas = fetch_all(cur, bs._SQL_INMUEBLES + " WHERE p.id = ANY(%s)", (props,))
            print("Inmuebles reasignados por fuente:", bs._guardar(cur, filas, cat))
            nuevos = fetch_all(cur, """
                SELECT COALESCE(b.nombre, '(sin barrio)') AS barrio, COUNT(*) AS n
                FROM propiedad_barrio pb LEFT JOIN barrios b ON b.id = pb.barrio_id
                WHERE pb.propiedad_id = ANY(%s) GROUP BY 1 ORDER BY 2 DESC LIMIT 8
            """, (props,))
            print("Ahora quedan en:", ", ".join(f"{f['barrio']} {f['n']}" for f in nuevos))
        if pedidos:
            from psycopg2.extras import execute_values
            filas = fetch_all(cur, "SELECT id, criterios FROM pedidos WHERE id = ANY(%s)", (pedidos,))
            valores = [(f["id"], bs.barrios_de_pedido(f["criterios"] if isinstance(f["criterios"], dict) else {}, cat))
                       for f in filas]
            execute_values(cur, """
                UPDATE pedidos AS p SET barrio_ids = v.ids, barrio_at = NOW()
                FROM (VALUES %s) AS v(id, ids) WHERE p.id = v.id
            """, valores, template="(%s::int, %s::int[])")

        print("\nDespués (índice de octubre):")
        _comunas(cur)

        if aplicar:
            db.conn.commit()
            print("\n✅ Aplicado.")
        else:
            db.conn.rollback()
            print("\n(Simulación: no se escribió nada. Corre con --aplicar para guardar.)")


if __name__ == "__main__":
    main("--aplicar" in sys.argv)
