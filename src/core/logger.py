#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sistema de Logging Centralizado - Proyecto Cupido
Proporciona logging estructurado para debugging y monitoreo del sistema
"""

import os
import sys
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps
import time
import traceback

# Directorio de logs
LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
os.makedirs(LOGS_DIR, exist_ok=True)


class CupidoFormatter(logging.Formatter):
    """Formatter personalizado con colores y formato estructurado"""

    # Colores ANSI
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Verde
        'WARNING': '\033[33m',    # Amarillo
        'ERROR': '\033[31m',      # Rojo
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'
    }

    # Emojis por nivel
    EMOJIS = {
        'DEBUG': '🔍',
        'INFO': '✅',
        'WARNING': '⚠️',
        'ERROR': '❌',
        'CRITICAL': '🚨'
    }

    def __init__(self, use_colors: bool = True, use_emojis: bool = True):
        super().__init__()
        self.use_colors = use_colors and sys.stdout.isatty()
        self.use_emojis = use_emojis

    def format(self, record):
        # Timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

        # Nivel con emoji y color
        level = record.levelname
        emoji = self.EMOJIS.get(level, '')

        if self.use_colors:
            color = self.COLORS.get(level, '')
            reset = self.COLORS['RESET']
            level_str = f"{color}{level:8}{reset}"
        else:
            level_str = f"{level:8}"

        # Módulo/componente
        module = record.name.replace('cupido.', '')

        # Mensaje
        message = record.getMessage()

        # Formato base
        if self.use_emojis:
            log_line = f"{emoji} [{timestamp}] {level_str} [{module}] {message}"
        else:
            log_line = f"[{timestamp}] {level_str} [{module}] {message}"

        # Agregar exception info si existe
        if record.exc_info:
            log_line += '\n' + ''.join(traceback.format_exception(*record.exc_info))

        return log_line


class JSONFormatter(logging.Formatter):
    """Formatter JSON para logs estructurados (archivos)"""

    def format(self, record):
        log_data = {
            'timestamp': datetime.fromtimestamp(record.created).isoformat(),
            'level': record.levelname,
            'module': record.name,
            'message': record.getMessage(),
            'function': record.funcName,
            'line': record.lineno
        }

        # Agregar datos extra si existen
        if hasattr(record, 'extra_data'):
            log_data['data'] = record.extra_data

        # Agregar exception info si existe
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__ if record.exc_info[0] else None,
                'message': str(record.exc_info[1]) if record.exc_info[1] else None,
                'traceback': traceback.format_exception(*record.exc_info)
            }

        return json.dumps(log_data, ensure_ascii=False, default=str)


def get_logger(name: str, level: str = None) -> logging.Logger:
    """
    Obtiene o crea un logger con configuración estándar de Cupido

    Args:
        name: Nombre del módulo (ej: 'search', 'scraper', 'whatsapp')
        level: Nivel de logging (DEBUG, INFO, WARNING, ERROR). Default: INFO

    Returns:
        Logger configurado
    """
    logger_name = f"cupido.{name}"
    logger = logging.getLogger(logger_name)

    # Si ya está configurado, retornar
    if logger.handlers:
        return logger

    # Configurar nivel
    level_str = level or os.getenv('LOG_LEVEL', 'INFO')
    logger.setLevel(getattr(logging, level_str.upper(), logging.INFO))

    # Handler de consola (con colores)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(CupidoFormatter(use_colors=True, use_emojis=True))
    logger.addHandler(console_handler)

    # Handler de archivo (JSON estructurado)
    log_file = os.path.join(LOGS_DIR, f'{name}.log')
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    # Handler de archivo general (todo el sistema)
    general_log = os.path.join(LOGS_DIR, 'cupido.log')
    general_handler = logging.FileHandler(general_log, encoding='utf-8')
    general_handler.setFormatter(JSONFormatter())
    logger.addHandler(general_handler)

    # No propagar al logger root
    logger.propagate = False

    return logger


def log_with_data(logger: logging.Logger, level: str, message: str, data: Dict[str, Any] = None):
    """
    Log con datos estructurados adicionales

    Args:
        logger: Logger a usar
        level: Nivel (debug, info, warning, error, critical)
        message: Mensaje principal
        data: Datos adicionales para incluir en el log
    """
    record_factory = logging.getLogRecordFactory()

    def custom_factory(*args, **kwargs):
        record = record_factory(*args, **kwargs)
        if data:
            record.extra_data = data
        return record

    logging.setLogRecordFactory(custom_factory)
    getattr(logger, level.lower())(message)
    logging.setLogRecordFactory(record_factory)


def log_execution_time(logger: logging.Logger = None, operation: str = None):
    """
    Decorador para medir y loggear tiempo de ejecución

    Args:
        logger: Logger a usar (opcional, se crea uno si no se proporciona)
        operation: Nombre de la operación (opcional, usa el nombre de la función)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger, operation

            if logger is None:
                logger = get_logger(func.__module__.split('.')[-1])

            op_name = operation or func.__name__
            start_time = time.time()

            logger.debug(f"Iniciando: {op_name}")

            try:
                result = func(*args, **kwargs)
                elapsed = (time.time() - start_time) * 1000  # ms

                log_with_data(logger, 'info',
                    f"Completado: {op_name} ({elapsed:.2f}ms)",
                    {'operation': op_name, 'elapsed_ms': elapsed, 'status': 'success'}
                )

                return result

            except Exception as e:
                elapsed = (time.time() - start_time) * 1000

                log_with_data(logger, 'error',
                    f"Error en: {op_name} ({elapsed:.2f}ms) - {str(e)}",
                    {'operation': op_name, 'elapsed_ms': elapsed, 'status': 'error', 'error': str(e)}
                )
                raise

        return wrapper
    return decorator


class SearchLogger:
    """Logger especializado para el sistema de búsqueda"""

    def __init__(self):
        self.logger = get_logger('search')
        self.current_search_id = None
        self._funnel = {}

    def info(self, msg): self.logger.info(msg)
    def warning(self, msg): self.logger.warning(msg)
    def error(self, msg): self.logger.error(msg)
    def debug(self, msg): self.logger.debug(msg)

    def start_search(self, query: str, sender: str = None) -> str:
        """Inicia el tracking de una búsqueda"""
        self.current_search_id = f"search_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        self._funnel = {
            'search_id': self.current_search_id,
            'query': query[:200],
            'stages': []
        }

        log_with_data(self.logger, 'info',
            f"[{self.current_search_id}] Nueva búsqueda iniciada",
            {
                'search_id': self.current_search_id,
                'query': query[:200],
                'sender': sender,
                'stage': 'start'
            }
        )
        return self.current_search_id

    def log_criteria_extraction(self, criteria: Dict[str, Any], elapsed_ms: float):
        """Loggea la extracción de criterios con Claude"""
        log_with_data(self.logger, 'info',
            f"[{self.current_search_id}] Criterios extraídos con Claude ({elapsed_ms:.0f}ms)",
            {
                'search_id': self.current_search_id,
                'criteria': criteria,
                'elapsed_ms': elapsed_ms,
                'stage': 'criteria_extraction'
            }
        )

    def log_sql_query(self, sql: str, params: Dict, elapsed_ms: float):
        """Loggea la consulta SQL ejecutada"""
        log_with_data(self.logger, 'debug',
            f"[{self.current_search_id}] Query SQL ejecutado ({elapsed_ms:.0f}ms)",
            {
                'search_id': self.current_search_id,
                'sql': sql[:500],
                'params': params,
                'elapsed_ms': elapsed_ms,
                'stage': 'sql_execution'
            }
        )

    def log_results(self, total_found: int, returned: int, elapsed_ms: float):
        """Loggea los resultados de la búsqueda"""
        log_with_data(self.logger, 'info',
            f"[{self.current_search_id}] Búsqueda completada: {total_found} encontradas, {returned} retornadas ({elapsed_ms:.0f}ms)",
            {
                'search_id': self.current_search_id,
                'total_found': total_found,
                'returned': returned,
                'elapsed_ms': elapsed_ms,
                'stage': 'results'
            }
        )

    def log_ranking(self, top_scores: list, elapsed_ms: float):
        """Loggea el proceso de ranking"""
        log_with_data(self.logger, 'debug',
            f"[{self.current_search_id}] Ranking completado ({elapsed_ms:.0f}ms)",
            {
                'search_id': self.current_search_id,
                'top_scores': top_scores[:5],
                'elapsed_ms': elapsed_ms,
                'stage': 'ranking'
            }
        )

    def log_error(self, error: str, stage: str):
        """Loggea un error en la búsqueda"""
        log_with_data(self.logger, 'error',
            f"[{self.current_search_id}] Error en {stage}: {error}",
            {
                'search_id': self.current_search_id,
                'error': error,
                'stage': stage
            }
        )

    # =========================================================================
    # DIAGNOSTIC FUNNEL LOGGING
    # =========================================================================

    def log_db_baseline(self, total_activas: int, total_con_precio: int, precio_min: float, precio_max: float):
        """Loggea el estado base de la DB antes de filtrar"""
        self._funnel['db_baseline'] = {
            'total_activas': total_activas,
            'total_con_precio': total_con_precio,
            'precio_min': precio_min,
            'precio_max': precio_max,
        }
        self.logger.info(
            f"[{self.current_search_id}] [FUNNEL] DB baseline: "
            f"{total_activas} activas, {total_con_precio} con precio, "
            f"rango ${precio_min/1_000_000:.0f}M - ${precio_max/1_000_000:.0f}M"
        )

    def log_criteria_summary(self, criteria: Dict[str, Any]):
        """Loggea resumen de criterios que se aplicaran como filtros SQL"""
        filters_applied = []
        if criteria.get('precio_max') or criteria.get('precio_min_implicito'):
            precio_min = criteria.get('precio_min') or criteria.get('precio_min_implicito', 0)
            precio_max = criteria.get('precio_max_ajustado') or criteria.get('precio_max', 0)
            filters_applied.append(f"precio: ${precio_min/1_000_000:.0f}M - ${precio_max/1_000_000:.0f}M")
        if criteria.get('tipo_propiedad'):
            filters_applied.append(f"tipo: {criteria['tipo_propiedad']}")
        if criteria.get('ubicaciones'):
            filters_applied.append(f"ubicaciones: {criteria['ubicaciones']}")
        if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
            hab_min = criteria.get('habitaciones_min_filtro') or criteria.get('habitaciones_min', '?')
            hab_max = criteria.get('habitaciones_max_filtro') or criteria.get('habitaciones_max', '?')
            filters_applied.append(f"habitaciones: {hab_min}-{hab_max}")
        if criteria.get('banos_min') or criteria.get('banos_max'):
            filters_applied.append(f"banos: {criteria.get('banos_min', '?')}-{criteria.get('banos_max', '?')}")
        if criteria.get('area_min') or criteria.get('area_max'):
            area_min = criteria.get('area_min_ajustado') or criteria.get('area_min', '?')
            area_max = criteria.get('area_max_ajustado') or criteria.get('area_max', '?')
            filters_applied.append(f"area: {area_min}-{area_max}m2")

        self._funnel['filters'] = filters_applied
        self.logger.info(
            f"[{self.current_search_id}] [FUNNEL] Filtros a aplicar: {' | '.join(filters_applied)}"
        )

    def log_sql_diagnostic(self, level_name: str, sql: str, params: Dict, result_count: int, elapsed_ms: float):
        """Loggea el SQL completo con params y resultado para diagnostico"""
        stage = {'level': level_name, 'results': result_count, 'elapsed_ms': round(elapsed_ms, 1)}
        self._funnel.setdefault('stages', []).append(stage)

        # Reemplazar params en SQL para mostrar query legible
        readable_sql = sql
        for key, val in params.items():
            placeholder = f'%({key})s'
            display_val = f"'{val}'" if isinstance(val, str) else str(val)
            readable_sql = readable_sql.replace(placeholder, display_val)

        # Log nivel INFO para que siempre aparezca
        self.logger.info(
            f"[{self.current_search_id}] [SQL] {level_name}: {result_count} resultados ({elapsed_ms:.0f}ms)"
        )
        # Log nivel DEBUG con SQL completo
        log_with_data(self.logger, 'info',
            f"[{self.current_search_id}] [SQL-DETAIL] {level_name}",
            {
                'search_id': self.current_search_id,
                'level': level_name,
                'sql_readable': readable_sql.strip(),
                'params': {k: str(v) for k, v in params.items()},
                'result_count': result_count,
                'elapsed_ms': elapsed_ms,
                'stage': 'sql_diagnostic'
            }
        )

    @staticmethod
    def _fetch_scalar(cursor) -> Any:
        """Extrae un valor escalar de fetchone(), compatible con dict y tuple cursors"""
        row = cursor.fetchone()
        if row is None:
            return 0
        if isinstance(row, dict):
            return list(row.values())[0]
        return row[0]

    def log_filter_impact(self, db, criteria: Dict[str, Any]):
        """Ejecuta queries diagnosticas para ver el impacto de cada filtro individual"""
        try:
            impacts = []
            _s = self._fetch_scalar  # shorthand

            # 1. Total activas
            db.cursor.execute("SELECT COUNT(*) FROM propiedades WHERE activa = TRUE")
            total = _s(db.cursor)
            impacts.append(f"activa=TRUE: {total}")

            # 2. Con precio valido
            db.cursor.execute("SELECT COUNT(*) FROM propiedades WHERE activa = TRUE AND precio IS NOT NULL AND precio > 0")
            con_precio = _s(db.cursor)
            impacts.append(f"+ precio valido: {con_precio}")

            # 3. Filtro de precio
            if criteria.get('precio_max'):
                precio_min = criteria.get('precio_min') or criteria.get('precio_min_implicito', 0)
                precio_max = criteria.get('precio_max_ajustado') or criteria.get('precio_max')
                db.cursor.execute(
                    "SELECT COUNT(*) FROM propiedades WHERE activa = TRUE AND precio >= %s AND precio <= %s",
                    (precio_min, precio_max)
                )
                en_rango = _s(db.cursor)
                impacts.append(f"+ precio ${precio_min/1_000_000:.0f}M-${precio_max/1_000_000:.0f}M: {en_rango}")

                # Solo upper bound (sin precio_min_implicito)
                db.cursor.execute(
                    "SELECT COUNT(*) FROM propiedades WHERE activa = TRUE AND precio > 0 AND precio <= %s",
                    (precio_max,)
                )
                solo_max = _s(db.cursor)
                impacts.append(f"  (solo precio <= ${precio_max/1_000_000:.0f}M sin piso: {solo_max})")

            # 4. Filtro de tipo
            if criteria.get('tipo_propiedad'):
                tipo = criteria['tipo_propiedad']
                if isinstance(tipo, list):
                    tipo_sql = " OR ".join(["tipo_propiedad ILIKE %s"] * len(tipo))
                    tipo_params = [f"%{t}%" for t in tipo]
                else:
                    tipo_sql = "tipo_propiedad ILIKE %s"
                    tipo_params = [f"%{tipo}%"]
                db.cursor.execute(
                    f"SELECT COUNT(*) FROM propiedades WHERE activa = TRUE AND ({tipo_sql})",
                    tipo_params
                )
                por_tipo = _s(db.cursor)
                impacts.append(f"+ tipo '{tipo}': {por_tipo}")

            # 5. Filtro de ubicacion
            if criteria.get('ubicaciones'):
                ub_conditions = []
                ub_params = []
                for ub in criteria['ubicaciones']:
                    ub_conditions.append("zona ILIKE %s OR ciudad ILIKE %s")
                    ub_params.extend([f"%{ub}%", f"%{ub}%"])
                db.cursor.execute(
                    f"SELECT COUNT(*) FROM propiedades WHERE activa = TRUE AND ({' OR '.join(ub_conditions)})",
                    ub_params
                )
                por_zona = _s(db.cursor)
                impacts.append(f"+ ubicacion {criteria['ubicaciones']}: {por_zona}")

            # 6. Filtro de habitaciones
            if criteria.get('habitaciones_min') or criteria.get('habitaciones_max'):
                hab_min = criteria.get('habitaciones_min_filtro') or criteria.get('habitaciones_min')
                hab_max = criteria.get('habitaciones_max_filtro') or criteria.get('habitaciones_max')
                hab_conds = ["activa = TRUE"]
                hab_params = []
                if hab_min:
                    hab_conds.append("habitaciones >= %s")
                    hab_params.append(hab_min)
                if hab_max:
                    hab_conds.append("habitaciones <= %s")
                    hab_params.append(hab_max)
                db.cursor.execute(
                    f"SELECT COUNT(*) FROM propiedades WHERE {' AND '.join(hab_conds)}",
                    hab_params
                )
                por_hab = _s(db.cursor)
                impacts.append(f"+ habitaciones {hab_min}-{hab_max}: {por_hab}")

            impact_text = " --> ".join(impacts)
            self.logger.warning(
                f"[{self.current_search_id}] [FILTER-IMPACT] {impact_text}"
            )
            log_with_data(self.logger, 'warning',
                f"[{self.current_search_id}] [FILTER-IMPACT-DETAIL]",
                {
                    'search_id': self.current_search_id,
                    'impacts': impacts,
                    'stage': 'filter_impact'
                }
            )

        except Exception as e:
            self.logger.error(f"[{self.current_search_id}] [FILTER-IMPACT] Error diagnosticando: {e}")

    def log_quality_gate(self, gate_name: str, score: float, threshold: float, passed: bool, detail: str = ''):
        """Loggea una decision de quality gate"""
        status = "PASSED" if passed else "BLOCKED"
        self.logger.warning(
            f"[{self.current_search_id}] [QUALITY-GATE] {gate_name}: {status} "
            f"(score={score:.1f}, threshold={threshold}) {detail}"
        )
        self._funnel.setdefault('quality_gates', []).append({
            'gate': gate_name,
            'score': score,
            'threshold': threshold,
            'passed': passed,
            'detail': detail
        })

    def log_ranking_detail(self, results: list, top_n: int = 5):
        """Loggea el detalle de scoring de los top N resultados"""
        for i, r in enumerate(results[:top_n]):
            score = r.get('match_score', 0)
            details = r.get('match_details', {})
            zona = r.get('zona', '?')
            precio = r.get('precio', 0)
            precio_display = f"${precio/1_000_000:.0f}M" if isinstance(precio, (int, float)) and precio > 0 else str(precio)
            hab = r.get('habitaciones', '?')
            tipo = r.get('tipo_propiedad', '?')

            self.logger.info(
                f"[{self.current_search_id}] [RANK] #{i+1} score={score:.1f} | "
                f"{tipo} | {zona} | {precio_display} | {hab}hab | "
                f"detalles={details}"
            )

    def log_search_funnel_summary(self, criteria: Dict, sql_count: int, post_rank_count: int,
                                   final_count: int, search_type: str, elapsed_ms: float):
        """Loggea un resumen completo del funnel de busqueda"""
        # Build the funnel visualization
        lines = [
            f"",
            f"{'='*70}",
            f"  SEARCH FUNNEL - {self.current_search_id}",
            f"{'='*70}",
            f"  Query: {self._funnel.get('query', '?')}",
            f"  Tipo busqueda: {search_type}",
            f"{'─'*70}",
        ]

        # DB baseline
        baseline = self._funnel.get('db_baseline', {})
        if baseline:
            lines.append(f"  DB Total activas:    {baseline.get('total_activas', '?')}")
            lines.append(f"  DB Con precio:       {baseline.get('total_con_precio', '?')}")

        # Filters
        lines.append(f"{'─'*70}")
        lines.append(f"  FILTROS APLICADOS:")
        for f in self._funnel.get('filters', []):
            lines.append(f"    - {f}")

        # SQL stages
        lines.append(f"{'─'*70}")
        lines.append(f"  RESULTADOS POR NIVEL:")
        for stage in self._funnel.get('stages', []):
            marker = ">>>" if stage['results'] > 0 else "   "
            lines.append(f"  {marker} {stage['level']}: {stage['results']} resultados ({stage['elapsed_ms']}ms)")

        # Quality gates
        lines.append(f"{'─'*70}")
        lines.append(f"  QUALITY GATES:")
        for gate in self._funnel.get('quality_gates', []):
            icon = "PASS" if gate['passed'] else "FAIL"
            lines.append(f"    [{icon}] {gate['gate']}: score={gate['score']:.1f} (min={gate['threshold']}) {gate.get('detail', '')}")

        # Final funnel
        lines.append(f"{'─'*70}")
        lines.append(f"  FUNNEL:")
        lines.append(f"    SQL results:       {sql_count}")
        lines.append(f"    Post-ranking:      {post_rank_count}")
        lines.append(f"    Final returned:    {final_count}")
        lines.append(f"    Tiempo total:      {elapsed_ms:.0f}ms")
        lines.append(f"{'='*70}")

        funnel_text = "\n".join(lines)
        self.logger.warning(f"\n{funnel_text}")

        # Also save to structured log
        log_with_data(self.logger, 'info',
            f"[{self.current_search_id}] [FUNNEL-SUMMARY]",
            {
                'search_id': self.current_search_id,
                'funnel': self._funnel,
                'sql_count': sql_count,
                'post_rank_count': post_rank_count,
                'final_count': final_count,
                'search_type': search_type,
                'elapsed_ms': elapsed_ms,
                'stage': 'funnel_summary'
            }
        )


class ScraperLogger:
    """Logger especializado para el sistema de scraping"""

    def __init__(self):
        self.logger = get_logger('scraper')
        self.current_scrape_id = None

    def start_scrape(self, url: str, source: str = 'Wasi') -> str:
        """Inicia el tracking de un scrape"""
        self.current_scrape_id = f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

        log_with_data(self.logger, 'info',
            f"[{self.current_scrape_id}] Iniciando scrape de {source}",
            {
                'scrape_id': self.current_scrape_id,
                'url': url,
                'source': source,
                'stage': 'start'
            }
        )
        return self.current_scrape_id

    def log_page_download(self, url: str, status_code: int, elapsed_ms: float):
        """Loggea la descarga de la página"""
        log_with_data(self.logger, 'debug',
            f"[{self.current_scrape_id}] Página descargada ({status_code}) - {elapsed_ms:.0f}ms",
            {
                'scrape_id': self.current_scrape_id,
                'url': url,
                'status_code': status_code,
                'elapsed_ms': elapsed_ms,
                'stage': 'download'
            }
        )

    def log_data_extraction(self, field: str, value: Any, success: bool = True):
        """Loggea la extracción de un campo específico"""
        level = 'debug' if success else 'warning'
        status = 'extraído' if success else 'no encontrado'

        log_with_data(self.logger, level,
            f"[{self.current_scrape_id}] Campo '{field}' {status}",
            {
                'scrape_id': self.current_scrape_id,
                'field': field,
                'value': str(value)[:100] if value else None,
                'success': success,
                'stage': 'extraction'
            }
        )

    def log_images_extracted(self, total: int, hd_count: int):
        """Loggea las imágenes extraídas"""
        log_with_data(self.logger, 'info',
            f"[{self.current_scrape_id}] {total} imágenes extraídas ({hd_count} HD)",
            {
                'scrape_id': self.current_scrape_id,
                'total_images': total,
                'hd_images': hd_count,
                'stage': 'images'
            }
        )

    def log_complete(self, property_code: str, elapsed_ms: float):
        """Loggea la finalización exitosa del scrape"""
        log_with_data(self.logger, 'info',
            f"[{self.current_scrape_id}] Scrape completado - Propiedad: {property_code} ({elapsed_ms:.0f}ms)",
            {
                'scrape_id': self.current_scrape_id,
                'property_code': property_code,
                'elapsed_ms': elapsed_ms,
                'stage': 'complete',
                'status': 'success'
            }
        )

    def log_error(self, error: str, stage: str):
        """Loggea un error en el scraping"""
        log_with_data(self.logger, 'error',
            f"[{self.current_scrape_id}] Error en {stage}: {error}",
            {
                'scrape_id': self.current_scrape_id,
                'error': error,
                'stage': stage,
                'status': 'error'
            }
        )


class WhatsAppLogger:
    """Logger especializado para el sistema de WhatsApp"""

    def __init__(self):
        self.logger = get_logger('whatsapp')

    def log_webhook_received(self, sender: str, message_type: str, is_group: bool):
        """Loggea un webhook recibido"""
        log_with_data(self.logger, 'info',
            f"Webhook recibido: {sender} ({message_type})",
            {
                'sender': sender,
                'message_type': message_type,
                'is_group': is_group,
                'stage': 'webhook_received'
            }
        )

    def log_message_detection(self, tipo: str, confianza: float, sender: str):
        """Loggea la detección del tipo de mensaje"""
        log_with_data(self.logger, 'info',
            f"Mensaje detectado: {tipo} (confianza: {confianza:.2f}) de {sender}",
            {
                'tipo': tipo,
                'confianza': confianza,
                'sender': sender,
                'stage': 'message_detection'
            }
        )

    def log_message_sent(self, to: str, success: bool, message_preview: str = None):
        """Loggea un mensaje enviado"""
        level = 'info' if success else 'error'
        status = 'enviado' if success else 'fallido'

        log_with_data(self.logger, level,
            f"Mensaje {status} a {to}",
            {
                'to': to,
                'success': success,
                'message_preview': message_preview[:50] if message_preview else None,
                'stage': 'message_sent'
            }
        )

    def log_session_created(self, sender: str, solicitud_id: int = None):
        """Loggea la creación de una sesión de usuario"""
        log_with_data(self.logger, 'debug',
            f"Sesión creada para {sender}",
            {
                'sender': sender,
                'solicitud_id': solicitud_id,
                'stage': 'session_created'
            }
        )

    def log_selection_processed(self, sender: str, selected: list, total_options: int):
        """Loggea el procesamiento de una selección"""
        log_with_data(self.logger, 'info',
            f"Selección procesada: {len(selected)}/{total_options} de {sender}",
            {
                'sender': sender,
                'selected': selected,
                'total_options': total_options,
                'stage': 'selection_processed'
            }
        )


# Instancias globales para uso directo
search_logger = SearchLogger()
scraper_logger = ScraperLogger()
whatsapp_logger = WhatsAppLogger()


# Funciones de conveniencia
def get_search_logger() -> SearchLogger:
    return search_logger

def get_scraper_logger() -> ScraperLogger:
    return scraper_logger

def get_whatsapp_logger() -> WhatsAppLogger:
    return whatsapp_logger
