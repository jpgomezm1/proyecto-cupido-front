#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utilidades de manejo de errores seguros para la API.
Los errores detallados se loguean internamente, al cliente se envía mensaje genérico.
"""

import logging
import traceback

logger = logging.getLogger(__name__)


def safe_error_response(error: Exception, context: str = "") -> dict:
    """
    Log completo del error internamente, retorna mensaje genérico al cliente.

    Esto previene filtración de información sensible (stack traces, queries SQL,
    rutas de archivos, etc.) al cliente.

    Args:
        error: La excepción capturada
        context: Contexto adicional (nombre del endpoint, operación, etc.)

    Returns:
        Dict con success=False y mensaje genérico de error

    Ejemplo:
        try:
            # operación riesgosa
        except Exception as e:
            return jsonify(safe_error_response(e, "create_property")), 500
    """
    # Log completo para debugging interno (va a logs/Sentry/New Relic)
    full_context = f"[{context}]" if context else ""
    logger.error(f"{full_context} Error: {str(error)}")
    logger.debug(f"{full_context} Traceback:\n{traceback.format_exc()}")

    # Mensaje genérico para el cliente - sin detalles internos
    return {
        "success": False,
        "error": "Ha ocurrido un error. Por favor intenta de nuevo."
    }


def safe_error_response_with_code(error: Exception, context: str = "", code: str = "INTERNAL_ERROR") -> dict:
    """
    Similar a safe_error_response pero incluye un código de error para el frontend.

    Args:
        error: La excepción capturada
        context: Contexto adicional
        code: Código de error para el frontend (ej: "DB_ERROR", "VALIDATION_ERROR")

    Returns:
        Dict con success=False, mensaje genérico y código de error
    """
    full_context = f"[{context}]" if context else ""
    logger.error(f"{full_context} Error ({code}): {str(error)}")
    logger.debug(f"{full_context} Traceback:\n{traceback.format_exc()}")

    return {
        "success": False,
        "error": "Ha ocurrido un error. Por favor intenta de nuevo.",
        "code": code
    }
