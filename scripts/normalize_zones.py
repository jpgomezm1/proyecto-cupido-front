#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script para normalizar zonas existentes en la base de datos

Este script:
1. Lee todas las zonas únicas en la tabla propiedades
2. Aplica la función normalizar_zona() a cada una
3. Muestra los cambios propuestos
4. Opcionalmente aplica los cambios a la DB

Uso:
    python scripts/normalize_zones.py --dry-run    # Solo mostrar cambios
    python scripts/normalize_zones.py --apply      # Aplicar cambios
"""

import sys
import os
import argparse

# Agregar el directorio padre al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.search_config import normalizar_zona, ZONA_CANONICA
from src.db.database import DatabaseManager


def get_unique_zones():
    """Obtiene todas las zonas únicas de la base de datos"""
    with DatabaseManager() as db:
        db.cursor.execute("""
            SELECT zona, COUNT(*) as count
            FROM propiedades
            WHERE zona IS NOT NULL AND zona != ''
            GROUP BY zona
            ORDER BY count DESC
        """)
        rows = db.cursor.fetchall()
        # Convertir a lista de tuplas (zona, count)
        result = []
        for row in rows:
            if isinstance(row, dict):
                result.append((row['zona'], row['count']))
            else:
                result.append((row[0], row[1]))
        return result


def calculate_normalizations(zones):
    """Calcula qué normalizaciones se aplicarían"""
    normalizations = []
    unchanged = []

    for zona, count in zones:
        zona_normalizada = normalizar_zona(zona)
        if zona != zona_normalizada:
            normalizations.append({
                'original': zona,
                'normalizada': zona_normalizada,
                'count': count
            })
        else:
            unchanged.append({
                'zona': zona,
                'count': count
            })

    return normalizations, unchanged


def apply_normalizations(normalizations, dry_run=True):
    """Aplica las normalizaciones a la base de datos"""
    if dry_run:
        print("\n⚠️  MODO DRY-RUN: No se aplicarán cambios")
        print("    Usa --apply para aplicar los cambios\n")
        return

    with DatabaseManager() as db:
        total_updated = 0

        for norm in normalizations:
            try:
                db.cursor.execute(
                    "UPDATE propiedades SET zona = %s WHERE zona = %s",
                    (norm['normalizada'], norm['original'])
                )
                rows_affected = db.cursor.rowcount
                total_updated += rows_affected
                print(f"  ✅ '{norm['original']}' → '{norm['normalizada']}' ({rows_affected} props)")

            except Exception as e:
                print(f"  ❌ Error normalizando '{norm['original']}': {e}")
                db.connection.rollback()
                return

        db.connection.commit()
        print(f"\n✅ Normalización completada: {total_updated} propiedades actualizadas")


def main():
    parser = argparse.ArgumentParser(
        description='Normaliza nombres de zonas en la base de datos'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Aplica los cambios (por defecto solo muestra)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        default=True,
        help='Solo muestra los cambios sin aplicarlos (default)'
    )

    args = parser.parse_args()
    dry_run = not args.apply

    print("=" * 60)
    print("  NORMALIZACIÓN DE ZONAS EN BASE DE DATOS")
    print("=" * 60)
    print()

    # Obtener zonas únicas
    print("📊 Obteniendo zonas únicas de la base de datos...")
    zones = get_unique_zones()
    print(f"   Encontradas: {len(zones)} zonas únicas")
    print()

    # Calcular normalizaciones
    normalizations, unchanged = calculate_normalizations(zones)

    # Mostrar zonas que cambiarían
    print(f"🔄 Zonas a normalizar: {len(normalizations)}")
    print("-" * 60)

    for norm in normalizations:
        print(f"  '{norm['original']}' → '{norm['normalizada']}' ({norm['count']} props)")

    print()

    # Mostrar zonas que no cambian
    print(f"✓ Zonas ya normalizadas: {len(unchanged)}")
    if unchanged:
        top_unchanged = unchanged[:10]
        for item in top_unchanged:
            print(f"  '{item['zona']}' ({item['count']} props)")
        if len(unchanged) > 10:
            print(f"  ... y {len(unchanged) - 10} más")

    print()

    # Resumen
    total_props_affected = sum(n['count'] for n in normalizations)
    print(f"📈 Resumen:")
    print(f"   - Zonas a normalizar: {len(normalizations)}")
    print(f"   - Propiedades afectadas: {total_props_affected}")
    print(f"   - Zonas sin cambios: {len(unchanged)}")
    print()

    # Aplicar cambios
    if normalizations:
        apply_normalizations(normalizations, dry_run=dry_run)
    else:
        print("✅ No hay zonas que normalizar. La base de datos ya está normalizada.")


if __name__ == "__main__":
    main()
