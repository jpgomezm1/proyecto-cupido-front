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

    def start_search(self, query: str, sender: str = None) -> str:
        """Inicia el tracking de una búsqueda"""
        self.current_search_id = f"search_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"

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
