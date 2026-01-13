#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Helpers para respuestas API estandarizadas

Uso:
    from src.utils.responses import success_response, error_response

    return success_response(data={'user': user_data})
    return error_response('Usuario no encontrado', 404)
"""

from flask import jsonify
from typing import Any, Dict, Optional


def success_response(data: Any = None, **kwargs) -> tuple:
    """
    Genera una respuesta exitosa estandarizada.

    Args:
        data: Datos a incluir en la respuesta
        **kwargs: Campos adicionales (total, page, etc.)

    Returns:
        Tuple de (Response JSON, status_code)

    Ejemplo:
        return success_response({'id': 1, 'name': 'Test'})
        # {"success": true, "data": {"id": 1, "name": "Test"}}

        return success_response(users, total=100, page=1)
        # {"success": true, "data": [...], "total": 100, "page": 1}
    """
    response = {'success': True}

    if data is not None:
        response['data'] = data

    response.update(kwargs)

    return jsonify(response), 200


def error_response(message: str, status_code: int = 400, **kwargs) -> tuple:
    """
    Genera una respuesta de error estandarizada.

    Args:
        message: Mensaje de error
        status_code: Código HTTP (default 400)
        **kwargs: Campos adicionales

    Returns:
        Tuple de (Response JSON, status_code)

    Ejemplo:
        return error_response('Campo requerido', 400)
        # {"success": false, "error": "Campo requerido"}

        return error_response('No encontrado', 404, field='user_id')
        # {"success": false, "error": "No encontrado", "field": "user_id"}
    """
    response = {
        'success': False,
        'error': message
    }

    response.update(kwargs)

    return jsonify(response), status_code


def paginated_response(
    data: list,
    total: int,
    page: int = 1,
    limit: int = 20,
    **kwargs
) -> tuple:
    """
    Genera una respuesta paginada estandarizada.

    Args:
        data: Lista de items
        total: Total de items (sin paginar)
        page: Página actual
        limit: Items por página
        **kwargs: Campos adicionales

    Returns:
        Tuple de (Response JSON, status_code)

    Ejemplo:
        return paginated_response(
            data=properties,
            total=150,
            page=2,
            limit=20
        )
        # {
        #   "success": true,
        #   "data": [...],
        #   "pagination": {
        #     "total": 150,
        #     "page": 2,
        #     "limit": 20,
        #     "pages": 8,
        #     "has_next": true,
        #     "has_prev": true
        #   }
        # }
    """
    import math

    total_pages = math.ceil(total / limit) if limit > 0 else 1

    response = {
        'success': True,
        'data': data,
        'pagination': {
            'total': total,
            'page': page,
            'limit': limit,
            'pages': total_pages,
            'has_next': page < total_pages,
            'has_prev': page > 1
        }
    }

    response.update(kwargs)

    return jsonify(response), 200


def validation_error(errors: Dict[str, str]) -> tuple:
    """
    Genera una respuesta de error de validación.

    Args:
        errors: Dict con campo -> mensaje de error

    Returns:
        Tuple de (Response JSON, status_code 422)

    Ejemplo:
        return validation_error({
            'email': 'Email inválido',
            'password': 'Mínimo 8 caracteres'
        })
    """
    return jsonify({
        'success': False,
        'error': 'Errores de validación',
        'validation_errors': errors
    }), 422
