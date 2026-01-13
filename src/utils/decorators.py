#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Decoradores reutilizables para la API

Uso:
    from src.utils.decorators import handle_api_error, with_db_connection

    @api_bp.route('/endpoint')
    @handle_api_error
    def my_endpoint():
        ...
"""

import traceback
from functools import wraps
from flask import jsonify, g
from src.db.database import DatabaseManager


def handle_api_error(f):
    """
    Decorador para manejo uniforme de errores en endpoints.

    Captura cualquier excepción, la loguea y retorna una respuesta
    JSON estandarizada con código 500.

    Uso:
        @handle_api_error
        def my_endpoint():
            # Si hay error, retorna {"success": False, "error": "..."}
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            print(f"❌ Error en {f.__name__}: {e}")
            traceback.print_exc()
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500
    return decorated


def with_db_connection(f):
    """
    Decorador que provee una conexión a la base de datos.

    La conexión está disponible como primer argumento de la función
    o como g.db dentro del contexto de Flask.

    Uso:
        @with_db_connection
        def my_function(db):
            db.cursor.execute("SELECT ...")
            ...

    O dentro de un endpoint Flask:
        @api_bp.route('/endpoint')
        @handle_api_error
        @with_db_connection
        def my_endpoint(db):
            db.cursor.execute("SELECT ...")
            ...
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        db = None
        try:
            db = DatabaseManager()
            db.connect()
            g.db = db  # Disponible en contexto Flask
            return f(db, *args, **kwargs)
        finally:
            if db:
                db.disconnect()
    return decorated


def log_execution_time(logger=None):
    """
    Decorador para medir y loguear tiempo de ejecución.

    Args:
        logger: Logger opcional para registrar tiempos

    Uso:
        @log_execution_time()
        def slow_function():
            ...
    """
    import time

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            start = time.time()
            result = f(*args, **kwargs)
            elapsed = (time.time() - start) * 1000

            message = f"⏱️  {f.__name__} ejecutado en {elapsed:.2f}ms"
            if logger:
                logger.info(message)
            else:
                print(message)

            return result
        return decorated
    return decorator
