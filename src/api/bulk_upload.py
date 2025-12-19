#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API de Carga Masiva de Propiedades
Permite subir archivos Excel con múltiples propiedades y procesarlas con SSE para progreso en tiempo real
"""

from flask import Blueprint, jsonify, request, Response, send_file
import uuid
import json
import time
import os
import io
from threading import Thread
from queue import Queue, Empty
from datetime import datetime

bulk_bp = Blueprint('bulk', __name__, url_prefix='/api/bulk')

# Almacén en memoria para jobs activos
# En producción, migrar a Redis
active_jobs = {}


class BulkUploadJob:
    """Representa un job de carga masiva de propiedades"""

    def __init__(self, job_id: str, properties: list, is_propia: bool):
        self.job_id = job_id
        self.properties = properties
        self.is_propia = is_propia
        self.total = len(properties)
        self.processed = 0
        self.results = []
        self.status = 'pending'  # pending, processing, completed, error
        self.event_queue = Queue()
        self.created_at = datetime.now()

    def add_event(self, event_type: str, data: dict):
        """Agrega un evento a la cola SSE"""
        self.event_queue.put({
            'type': event_type,
            'data': data,
            'timestamp': datetime.now().isoformat()
        })

    def to_dict(self):
        """Convierte el job a diccionario"""
        return {
            'job_id': self.job_id,
            'total': self.total,
            'processed': self.processed,
            'status': self.status,
            'is_propia': self.is_propia,
            'created_at': self.created_at.isoformat(),
            'results_summary': {
                'success': len([r for r in self.results if r.get('status') == 'success']),
                'error': len([r for r in self.results if r.get('status') == 'error'])
            }
        }


def process_bulk_job(job: BulkUploadJob):
    """
    Procesa las propiedades en background, emitiendo eventos SSE
    """
    from src.scrapers.wasi import WasiScraper
    from src.scrapers.tu360 import Tu360Scraper
    from src.db.database import DatabaseManager

    job.status = 'processing'

    # Inicializar scrapers (sin AI enrichment para mayor velocidad)
    # Delay de 2 segundos para Wasi para evitar rate limiting
    wasi_scraper = WasiScraper(delay=2, verbose=True, enable_ai_enrichment=False)
    tu360_scraper = Tu360Scraper(verbose=False)

    print(f"\n{'='*60}")
    print(f"🚀 INICIANDO CARGA MASIVA - Job: {job.job_id}")
    print(f"📊 Total propiedades: {job.total}")
    print(f"📁 Tipo: {'Propias' if job.is_propia else 'Externas'}")
    print(f"{'='*60}\n")

    for idx, prop in enumerate(job.properties):
        url = prop.get('url', '').strip()

        if not url:
            job.add_event('progress', {
                'index': idx,
                'url': url,
                'status': 'error',
                'error': 'URL vacía'
            })
            job.results.append({
                'url': url,
                'status': 'error',
                'error': 'URL vacía'
            })
            job.processed += 1
            continue

        # Emitir evento de inicio de procesamiento
        job.add_event('processing', {
            'index': idx,
            'url': url,
            'status': 'processing'
        })

        print(f"📍 [{idx+1}/{job.total}] Procesando: {url[:60]}...")

        try:
            # Detectar fuente y scrapear (con reintento)
            data = None
            max_retries = 2

            if 'wasi.co' in url.lower():
                # Wasi tiene 404 intermitentes por su CDN, necesitamos más reintentos
                max_wasi_retries = 4
                for attempt in range(max_wasi_retries):
                    data = wasi_scraper.extract_property_data(url)
                    if data:
                        break
                    if attempt < max_wasi_retries - 1:
                        wait_time = 2 + (attempt * 2)  # 2, 4, 6 segundos (backoff)
                        print(f"   ⏳ Reintentando en {wait_time} segundos... (intento {attempt + 2}/{max_wasi_retries})")
                        time.sleep(wait_time)

                if not data:
                    raise ValueError('No se pudo extraer información de la URL después de varios intentos')
                if job.is_propia:
                    data['fuente'] = 'Propia'
                else:
                    data['fuente'] = 'Wasi_Captado'
            elif 'tu360inmobiliario' in url.lower() or 'pulppo' in url.lower():
                data = tu360_scraper.extract_property_data(url)
                if not data:
                    raise ValueError('No se pudo extraer información de la URL (puede que ya no exista)')
                if not job.is_propia:
                    data['fuente'] = 'Tu360_Captado'
            else:
                raise ValueError(f'URL no soportada. Solo se aceptan URLs de Wasi.co o Tu360Inmobiliario')

            # Para propiedades externas, agregar/sobrescribir datos del agente
            if not job.is_propia:
                nombre_agente = prop.get('nombre_agente', '').strip()
                telefono_agente = prop.get('telefono_agente', '').strip()

                if nombre_agente:
                    data['asesor'] = nombre_agente
                if telefono_agente:
                    # Normalizar teléfono colombiano
                    telefono_agente = telefono_agente.replace(' ', '').replace('-', '')
                    if not telefono_agente.startswith('+'):
                        if telefono_agente.startswith('57'):
                            telefono_agente = '+' + telefono_agente
                        else:
                            telefono_agente = '+57' + telefono_agente
                    data['telefono'] = telefono_agente

            # Guardar en base de datos
            with DatabaseManager() as db:
                property_id = db.insert_property(data)

            titulo = data.get('titulo', data.get('title', 'Sin título'))

            # Verificar si se guardó correctamente
            if property_id is None:
                raise ValueError(f'La propiedad ya existe en la base de datos (código: {data.get("codigo_propiedad", "desconocido")})')

            print(f"   ✅ Guardada: {titulo[:40]}... (ID: {property_id})")

            # Emitir evento de éxito
            job.add_event('progress', {
                'index': idx,
                'url': url,
                'status': 'success',
                'title': titulo,
                'property_id': property_id
            })

            job.results.append({
                'url': url,
                'status': 'success',
                'property_id': property_id,
                'title': titulo
            })

        except Exception as e:
            error_msg = str(e)
            print(f"   ❌ Error: {error_msg[:50]}...")

            # Emitir evento de error
            job.add_event('progress', {
                'index': idx,
                'url': url,
                'status': 'error',
                'error': error_msg
            })

            job.results.append({
                'url': url,
                'status': 'error',
                'error': error_msg
            })

        job.processed += 1

        # Delay entre propiedades para evitar rate limiting (2 segundos)
        if idx < len(job.properties) - 1:
            time.sleep(2)

    # Calcular resumen
    success_count = len([r for r in job.results if r['status'] == 'success'])
    error_count = len([r for r in job.results if r['status'] == 'error'])

    print(f"\n{'='*60}")
    print(f"✅ CARGA MASIVA COMPLETADA - Job: {job.job_id}")
    print(f"📊 Exitosas: {success_count} | Errores: {error_count}")
    print(f"{'='*60}\n")

    # Emitir evento de completado
    job.add_event('complete', {
        'total': job.total,
        'success': success_count,
        'errors': error_count,
        'results': job.results
    })

    job.status = 'completed'


@bulk_bp.route('/upload', methods=['POST'])
def upload_bulk():
    """
    POST /api/bulk/upload

    Recibe archivo Excel y tipo de carga.
    Inicia procesamiento en background.

    Form data:
    - file: archivo Excel (.xlsx)
    - tipo: 'propia' | 'externa'

    Returns:
        JSON: {success, job_id, total_properties}
    """
    try:
        # Validar archivo
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No se recibió ningún archivo'
            }), 400

        file = request.files['file']
        tipo = request.form.get('tipo', 'propia')

        if not file.filename:
            return jsonify({
                'success': False,
                'error': 'El archivo no tiene nombre'
            }), 400

        if not file.filename.endswith('.xlsx'):
            return jsonify({
                'success': False,
                'error': 'El archivo debe ser formato Excel (.xlsx)'
            }), 400

        # Leer Excel con pandas
        import pandas as pd

        try:
            df = pd.read_excel(file, engine='openpyxl')
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'Error al leer el archivo Excel: {str(e)}'
            }), 400

        # Normalizar nombres de columnas (lowercase, strip)
        df.columns = [col.lower().strip() for col in df.columns]

        # Validar columnas según tipo
        if tipo == 'propia':
            required_columns = ['url']
        else:  # externa
            required_columns = ['url', 'nombre_agente', 'telefono_agente']

        missing = [col for col in required_columns if col not in df.columns]
        if missing:
            return jsonify({
                'success': False,
                'error': f'Columnas faltantes en el archivo: {", ".join(missing)}. Descarga el template correcto.'
            }), 400

        # Filtrar filas vacías
        df = df.dropna(subset=['url'])

        if len(df) == 0:
            return jsonify({
                'success': False,
                'error': 'El archivo no contiene URLs válidas'
            }), 400

        # Límite de propiedades
        MAX_PROPERTIES = 100
        if len(df) > MAX_PROPERTIES:
            return jsonify({
                'success': False,
                'error': f'El archivo excede el límite de {MAX_PROPERTIES} propiedades. Divide el archivo en partes más pequeñas.'
            }), 400

        # Convertir a lista de propiedades
        properties = []
        for _, row in df.iterrows():
            # Limpiar URL: quitar espacios, caracteres invisibles, y asegurar encoding correcto
            raw_url = str(row['url']).strip()
            # Quitar caracteres invisibles y de control
            clean_url = ''.join(c for c in raw_url if c.isprintable() or c in '\n\r\t')
            clean_url = clean_url.strip()

            prop = {'url': clean_url}
            if tipo == 'externa':
                prop['nombre_agente'] = str(row.get('nombre_agente', '')).strip() if pd.notna(row.get('nombre_agente')) else ''
                prop['telefono_agente'] = str(row.get('telefono_agente', '')).strip() if pd.notna(row.get('telefono_agente')) else ''
            properties.append(prop)

        # Crear job
        job_id = str(uuid.uuid4())[:8]
        job = BulkUploadJob(job_id, properties, tipo == 'propia')
        active_jobs[job_id] = job

        print(f"\n📤 Nuevo job de carga masiva creado: {job_id}")
        print(f"   Tipo: {'Propias' if job.is_propia else 'Externas'}")
        print(f"   Propiedades: {len(properties)}")

        # Iniciar procesamiento en background
        thread = Thread(target=process_bulk_job, args=(job,), daemon=True)
        thread.start()

        return jsonify({
            'success': True,
            'job_id': job_id,
            'total_properties': len(properties),
            'tipo': tipo
        }), 200

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': f'Error interno: {str(e)}'
        }), 500


@bulk_bp.route('/progress/<job_id>', methods=['GET'])
def get_progress(job_id: str):
    """
    GET /api/bulk/progress/:job_id

    Server-Sent Events stream para progreso en tiempo real.
    """
    if job_id not in active_jobs:
        return jsonify({
            'success': False,
            'error': 'Job no encontrado'
        }), 404

    job = active_jobs[job_id]

    def generate():
        """Generador de eventos SSE"""
        while True:
            try:
                # Esperar evento con timeout
                event = job.event_queue.get(timeout=30)

                # Formatear como SSE
                yield f"event: {event['type']}\n"
                yield f"data: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

                # Si es evento de completado, terminar stream
                if event['type'] == 'complete':
                    break

            except Empty:
                # Timeout - enviar heartbeat para mantener conexión
                yield f"event: heartbeat\ndata: {{}}\n\n"

                # Si el job ya terminó, enviar complete
                if job.status == 'completed':
                    success_count = len([r for r in job.results if r['status'] == 'success'])
                    error_count = len([r for r in job.results if r['status'] == 'error'])
                    yield f"event: complete\n"
                    yield f"data: {json.dumps({'total': job.total, 'success': success_count, 'errors': error_count, 'results': job.results}, ensure_ascii=False)}\n\n"
                    break

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
            'Access-Control-Allow-Origin': '*'
        }
    )


@bulk_bp.route('/status/<job_id>', methods=['GET'])
def get_status(job_id: str):
    """
    GET /api/bulk/status/:job_id

    Obtiene el estado actual del job (sin SSE, para polling fallback)
    """
    if job_id not in active_jobs:
        return jsonify({
            'success': False,
            'error': 'Job no encontrado'
        }), 404

    job = active_jobs[job_id]

    return jsonify({
        'success': True,
        'data': job.to_dict()
    }), 200


@bulk_bp.route('/templates/propias', methods=['GET'])
def download_template_propias():
    """
    GET /api/bulk/templates/propias

    Descarga template Excel para propiedades propias
    """
    import pandas as pd

    # Crear DataFrame con datos de ejemplo
    df = pd.DataFrame({
        'url': [
            'https://info.wasi.co/ejemplo-casa-venta/123456',
            'https://asesor.tu360inmobiliario-pulppo.com/property/ejemplo123',
            '(Agrega más URLs aquí...)'
        ]
    })

    # Guardar a BytesIO
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Propiedades')

        # Agregar hoja de instrucciones
        instrucciones = pd.DataFrame({
            'Instrucciones': [
                '1. Llena la columna "url" con los links de tus propiedades',
                '2. Solo se aceptan URLs de Wasi.co o Tu360Inmobiliario',
                '3. Máximo 100 propiedades por carga',
                '4. Las propiedades se marcarán como "Propias"',
                '',
                'Ejemplos de URLs válidas:',
                '- https://info.wasi.co/casa-venta-medellin/9560011',
                '- https://asesor.tu360inmobiliario-pulppo.com/property/abc123'
            ]
        })
        instrucciones.to_excel(writer, index=False, sheet_name='Instrucciones')

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='template_propiedades_propias.xlsx'
    )


@bulk_bp.route('/templates/externas', methods=['GET'])
def download_template_externas():
    """
    GET /api/bulk/templates/externas

    Descarga template Excel para propiedades de terceros
    """
    import pandas as pd

    # Crear DataFrame con datos de ejemplo
    df = pd.DataFrame({
        'url': [
            'https://info.wasi.co/apartamento-venta/789012',
            'https://info.wasi.co/casa-arriendo/345678',
            '(Agrega más URLs aquí...)'
        ],
        'nombre_agente': [
            'Juan Pérez',
            'María López',
            ''
        ],
        'telefono_agente': [
            '+573001234567',
            '3159876543',
            ''
        ]
    })

    # Guardar a BytesIO
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Propiedades')

        # Agregar hoja de instrucciones
        instrucciones = pd.DataFrame({
            'Instrucciones': [
                '1. Llena la columna "url" con los links de las propiedades',
                '2. Llena "nombre_agente" con el nombre del dueño de la propiedad',
                '3. Llena "telefono_agente" con el teléfono de contacto',
                '4. El teléfono puede incluir o no el +57',
                '5. Máximo 100 propiedades por carga',
                '',
                'Estas propiedades se marcarán como captadas de terceros.',
                'Los datos del agente aparecerán como contacto de la propiedad.'
            ]
        })
        instrucciones.to_excel(writer, index=False, sheet_name='Instrucciones')

    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='template_propiedades_externas.xlsx'
    )


@bulk_bp.route('/jobs', methods=['GET'])
def list_jobs():
    """
    GET /api/bulk/jobs

    Lista todos los jobs activos (para debugging)
    """
    jobs_list = []
    for job_id, job in active_jobs.items():
        jobs_list.append(job.to_dict())

    return jsonify({
        'success': True,
        'data': jobs_list,
        'total': len(jobs_list)
    }), 200


@bulk_bp.route('/jobs/<job_id>', methods=['DELETE'])
def delete_job(job_id: str):
    """
    DELETE /api/bulk/jobs/:job_id

    Elimina un job completado
    """
    if job_id not in active_jobs:
        return jsonify({
            'success': False,
            'error': 'Job no encontrado'
        }), 404

    job = active_jobs[job_id]

    if job.status == 'processing':
        return jsonify({
            'success': False,
            'error': 'No se puede eliminar un job en procesamiento'
        }), 400

    del active_jobs[job_id]

    return jsonify({
        'success': True,
        'message': f'Job {job_id} eliminado'
    }), 200
