"""
Precio sugerido y comparables con facetas (portal → ficha → catálogo de barrios).

Solo lectura contra la BD real; skip si no hay conexión. Oct-2026: con las columnas
del portal, un apartamento reciente de Wasi llegaba sin tipo ni zona y se comparaba
contra casas y oficinas de toda la ciudad.
"""
from tests.conftest import requires_db
from src.services import facetas
from src.services import property_service as ps
from src.services.db import get_db


def _apto_reciente_sin_tipo_crudo(cur):
    cur.execute("""
        SELECT p.id FROM propiedades p JOIN propiedades_ficha f ON f.propiedad_id = p.id
        WHERE p.activa AND COALESCE(p.tipo_propiedad, '') = '' AND f.tipo = 'apartamento'
          AND f.area_m2 > 0 AND p.precio > 0
        ORDER BY p.fecha_creacion DESC LIMIT 1
    """)
    r = cur.fetchone()
    return r["id"] if r else None


@requires_db
def test_get_property_completa_tipo_desde_la_ficha():
    with get_db() as db:
        pid = _apto_reciente_sin_tipo_crudo(db.cursor)
        if not pid:
            return
        p = ps.get_property(db.cursor, pid)
    assert p["tipo_propiedad"] == "Apartamento"
    assert p["area_construida"]


@requires_db
def test_comparables_son_del_mismo_tipo():
    with get_db() as db:
        pid = _apto_reciente_sin_tipo_crudo(db.cursor)
        if not pid:
            return
        comp = ps.find_comparables(db.cursor, pid, limit=10)
    tipos = {(c["tipo_propiedad"] or "").lower() for c in comp["comparables"]}
    assert tipos <= {"apartamento", "departamento"}, tipos


@requires_db
def test_estimacion_usa_mas_que_las_columnas_del_portal():
    with get_db() as db:
        est = ps.estimate_price(db.cursor, ciudad="Medellín", zona="Laureles", tipo_propiedad="apartamento",
                                area_construida=80, habitaciones=3)
        db.cursor.execute("""
            SELECT COUNT(*) n FROM propiedades p
            WHERE p.activa AND p.precio > 0 AND p.area_construida > 0 AND p.tipo_negocio = 'Venta'
              AND p.tipo_propiedad ILIKE '%%apartamento%%' AND p.zona ILIKE '%%laureles%%'
        """)
        solo_portal = db.cursor.fetchone()["n"]
    assert est["muestra_comparables"] >= solo_portal
    assert est.get("precio_estimado")


def test_tipo_con_espacio_casa_con_la_clave_de_la_ficha():
    conds, params = facetas.condiciones(tipo="casa campestre")
    assert params == ["%casa_campestre%"]  # «_» en LIKE vale por « » o por «_»
    assert facetas.legible_tipo("casa_campestre") == "Casa campestre"
    assert facetas.legible_tipo("Apartamento") == "Apartamento"
