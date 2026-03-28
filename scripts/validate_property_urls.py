#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validador de URLs de propiedades.

Verifica que los links originales de las propiedades activas siguen funcionando.
Si un link devuelve 404 o no carga, marca la propiedad como inactiva.

Uso:
    python scripts/validate_property_urls.py              # Ejecutar validación completa
    python scripts/validate_property_urls.py --dry-run    # Solo verificar, no desactivar
    python scripts/validate_property_urls.py --limit 50   # Validar solo las primeras N
"""

import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
BATCH_SIZE = 100
DELAY_BETWEEN_REQUESTS = 1.5  # seconds
DELAY_BETWEEN_BATCHES = 5     # seconds
REQUEST_TIMEOUT = 20           # seconds

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Wasi redirects to this URL when property doesn't exist
WASI_HOME_URL = "https://wasi.co"
WASI_NOT_FOUND_PATTERNS = ["wasi.co/es", "wasi.co/en", "inmueble-no-encontrado"]

# Tu360 shows this text when property is removed
TU360_NOT_FOUND_PATTERNS = [
    "propiedad no encontrada",
    "esta propiedad ya no está disponible",
    "property not found",
    "no encontramos la propiedad",
]


class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'


def get_connection():
    if not DATABASE_URL:
        print(f"{Colors.RED}Error: DATABASE_URL no configurada{Colors.END}")
        sys.exit(1)
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def check_url(session, url, fuente):
    """
    Verifica si una URL sigue activa.
    Returns: (is_active: bool, reason: str, status_code: int|None)
    """
    if not url or not url.startswith("http"):
        return True, "sin_url", None

    try:
        response = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        status = response.status_code
        final_url = response.url

        # 404 explícito
        if status == 404:
            return False, "404", status

        # 410 Gone
        if status == 410:
            return False, "410_gone", status

        # Server error — no desactivar, puede ser temporal
        if status >= 500:
            return True, f"server_error_{status}", status

        # 403 Forbidden — no desactivar, puede ser rate limit
        if status == 403:
            return True, "forbidden_skip", status

        # 200 pero verificar contenido
        if status == 200:
            # Wasi: redirect a home page = propiedad no existe
            if fuente and "wasi" in fuente.lower():
                for pattern in WASI_NOT_FOUND_PATTERNS:
                    if pattern in final_url.lower():
                        return False, "wasi_redirect_home", status

            # Tu360/Pulppo: 200 pero con texto de "no encontrada"
            if fuente and ("tu360" in fuente.lower() or "pulppo" in fuente.lower()):
                content_lower = response.text[:5000].lower()
                for pattern in TU360_NOT_FOUND_PATTERNS:
                    if pattern in content_lower:
                        return False, "tu360_not_found_content", status

            return True, "ok", status

        # Otros status codes (200-399) — probablemente OK
        if 200 <= status < 400:
            return True, f"ok_{status}", status

        # Cualquier otro — no desactivar por seguridad
        return True, f"unknown_{status}", status

    except requests.exceptions.Timeout:
        return False, "timeout", None
    except requests.exceptions.ConnectionError:
        return False, "connection_error", None
    except requests.exceptions.TooManyRedirects:
        return False, "too_many_redirects", None
    except Exception as e:
        return True, f"error: {str(e)[:50]}", None


def run_validation(dry_run=False, limit=None):
    start_time = datetime.now()
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}  VALIDACION DE URLS DE PROPIEDADES{Colors.END}")
    print(f"{Colors.BOLD}  {start_time.strftime('%Y-%m-%d %H:%M:%S')}{Colors.END}")
    if dry_run:
        print(f"{Colors.YELLOW}  MODO DRY-RUN: No se desactivaran propiedades{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}\n")

    conn = get_connection()
    cursor = conn.cursor()

    # Fetch active properties with URLs
    query = """
        SELECT id, url, fuente, titulo
        FROM propiedades
        WHERE activa = TRUE AND url IS NOT NULL AND url != ''
        ORDER BY id
    """
    if limit:
        query += f" LIMIT {int(limit)}"

    cursor.execute(query)
    properties = cursor.fetchall()

    total = len(properties)
    print(f"  Propiedades activas con URL: {Colors.BOLD}{total}{Colors.END}\n")

    if total == 0:
        print(f"{Colors.GREEN}No hay propiedades para validar{Colors.END}")
        conn.close()
        return

    # Setup HTTP session
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # Counters
    ok_count = 0
    deactivated_count = 0
    skipped_count = 0
    error_count = 0
    deactivated_list = []

    for idx, prop in enumerate(properties, 1):
        prop_id = prop["id"]
        url = prop["url"]
        fuente = prop["fuente"] or "unknown"
        titulo = (prop["titulo"] or "Sin titulo")[:50]

        is_active, reason, status_code = check_url(session, url, fuente)

        if is_active:
            if reason == "ok" or reason.startswith("ok_"):
                ok_count += 1
                status_str = f"{Colors.GREEN}✓ OK{Colors.END}"
            else:
                skipped_count += 1
                status_str = f"{Colors.YELLOW}⊘ SKIP ({reason}){Colors.END}"
        else:
            deactivated_count += 1
            deactivated_list.append({
                "id": prop_id,
                "titulo": titulo,
                "fuente": fuente,
                "reason": reason,
                "url": url,
            })

            if not dry_run:
                cursor.execute(
                    "UPDATE propiedades SET activa = FALSE, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id = %s",
                    (prop_id,)
                )
                conn.commit()

            status_str = f"{Colors.RED}✗ {reason.upper()}{Colors.END} — {'DESACTIVADA' if not dry_run else 'SERIA DESACTIVADA'}"

        # Progress log
        print(f"  [{idx:>{len(str(total))}}/{total}] {status_str} {Colors.DIM}{titulo} ({fuente}){Colors.END}")

        # Rate limiting
        if idx % BATCH_SIZE == 0 and idx < total:
            print(f"\n  {Colors.BLUE}Pausa entre lotes ({DELAY_BETWEEN_BATCHES}s)...{Colors.END}\n")
            time.sleep(DELAY_BETWEEN_BATCHES)
        else:
            time.sleep(DELAY_BETWEEN_REQUESTS)

    conn.close()
    elapsed = (datetime.now() - start_time).total_seconds()

    # Summary
    print(f"\n{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"{Colors.BOLD}  RESUMEN{Colors.END}")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}")
    print(f"  Total verificadas:   {total}")
    print(f"  {Colors.GREEN}Activas (OK):        {ok_count}{Colors.END}")
    print(f"  {Colors.YELLOW}Skipped (temp):      {skipped_count}{Colors.END}")
    print(f"  {Colors.RED}Desactivadas:        {deactivated_count}{Colors.END}")
    print(f"  Tiempo total:        {elapsed/60:.1f} minutos")
    print(f"{Colors.BOLD}{'=' * 70}{Colors.END}")

    if deactivated_list:
        print(f"\n{Colors.RED}{Colors.BOLD}  Propiedades desactivadas:{Colors.END}\n")
        for d in deactivated_list[:30]:
            print(f"    #{d['id']} — {d['titulo']} ({d['fuente']}) — {d['reason']}")
            print(f"    {Colors.DIM}{d['url']}{Colors.END}")
        if len(deactivated_list) > 30:
            print(f"\n    ... y {len(deactivated_list) - 30} mas")

    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Validador de URLs de propiedades")
    parser.add_argument("--dry-run", action="store_true", help="Solo verificar, no desactivar")
    parser.add_argument("--limit", type=int, help="Limitar cantidad de propiedades a verificar")
    args = parser.parse_args()

    run_validation(dry_run=args.dry_run, limit=args.limit)
