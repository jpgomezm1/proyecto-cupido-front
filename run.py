#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Punto de entrada para el servidor Flask de Proyecto Cupido.
Ejecutar con: python run.py
"""

from src.main import app

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5050, debug=True)
