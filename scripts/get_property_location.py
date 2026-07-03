#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Devuelve la ubicacion aproximada de una propiedad lista para enviar por WhatsApp.

Acepta el ID interno (propiedades.id) o el codigo_propiedad del portal.

Uso:
    python scripts/get_property_location.py 9924963
    python scripts/get_property_location.py 26133
"""

import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Forzar UTF-8 en stdout/stderr para que emojis y tildes salgan bien en Windows
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except AttributeError:
    pass

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    if not DATABASE_URL:
        print("Error: DATABASE_URL no configurada", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def fetch_property(identifier: str):
    """
    Busca propiedad por id (entero) o codigo_propiedad (texto del portal).
    Si el identificador es numerico, intenta ambos campos.
    """
    conn = get_connection()
    cur = conn.cursor()

    query = """
        SELECT id, codigo_propiedad, titulo, fuente, url, activa,
               pais, departamento, ciudad, zona, barrio_normalizado,
               direccion_completa, latitud, longitud, ubicacion_aproximada
        FROM propiedades
        WHERE codigo_propiedad = %s
           OR (CAST(id AS TEXT) = %s)
        LIMIT 1
    """
    cur.execute(query, (str(identifier), str(identifier)))
    row = cur.fetchone()
    conn.close()
    return row


def build_address_line(prop: dict) -> str:
    """Arma la linea de direccion mas especifica posible."""
    parts = []
    if prop.get("direccion_completa"):
        parts.append(prop["direccion_completa"])
    if prop.get("barrio_normalizado"):
        parts.append(prop["barrio_normalizado"])
    if prop.get("zona"):
        parts.append(prop["zona"])
    if prop.get("ciudad"):
        parts.append(prop["ciudad"])
    if prop.get("departamento"):
        parts.append(prop["departamento"])

    seen = set()
    deduped = []
    for p in parts:
        key = p.strip().lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(p.strip())
    return ", ".join(deduped) if deduped else "Ubicacion no disponible"


def build_maps_link(lat, lon):
    if lat is None or lon is None:
        return None
    return f"https://www.google.com/maps?q={lat},{lon}"


def build_whatsapp_message(prop: dict) -> str:
    titulo = prop.get("titulo") or "Propiedad"
    codigo = prop.get("codigo_propiedad") or prop.get("id")
    direccion = build_address_line(prop)
    maps_link = build_maps_link(prop.get("latitud"), prop.get("longitud"))
    aproximada = prop.get("ubicacion_aproximada")

    lines = []
    lines.append(f"📍 *{titulo}*")
    lines.append(f"Código: {codigo}")
    lines.append("")
    label = "Ubicación aproximada" if aproximada else "Ubicación"
    lines.append(f"{label}: {direccion}")

    if maps_link:
        lines.append("")
        lines.append("🗺️ Ver en Google Maps:")
        lines.append(maps_link)
    else:
        lines.append("")
        lines.append("⚠️ Esta propiedad no tiene coordenadas registradas.")

    if aproximada:
        lines.append("")
        lines.append("_Nota: la ubicación marca el sector, no el inmueble exacto._")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Ubicacion de propiedad para WhatsApp")
    parser.add_argument("identifier", help="ID interno o codigo_propiedad del portal")
    args = parser.parse_args()

    prop = fetch_property(args.identifier)
    if not prop:
        print(f"No se encontro propiedad con identificador '{args.identifier}'", file=sys.stderr)
        sys.exit(2)

    if not prop.get("activa"):
        print("[Aviso] La propiedad esta marcada como INACTIVA en BD.\n", file=sys.stderr)

    message = build_whatsapp_message(prop)
    print(message)


if __name__ == "__main__":
    main()
