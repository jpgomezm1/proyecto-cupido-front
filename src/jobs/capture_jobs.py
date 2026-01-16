"""
Jobs de captura para procesamiento en background con Redis Queue.
Estos jobs se ejecutan en el worker dyno de forma asincrona.
"""
import os
from src.core.cupido_manager import CupidoManager
from src.db.database import DatabaseManager


def process_capture_job(job_data: dict):
    """
    Procesa una captura de propiedad en background.

    Args:
        job_data: {
            'tipo': 'captacion_wasi' | 'captacion_tu360' | 'captacion_lobbie',
            'url': str,
            'agente_telefono': str,
            'mensaje_completo': str,
            'grupo_id': str,
            'nombre_agente': str | None
        }
    """
    print(f"[WORKER] Procesando job: {job_data.get('tipo')} - {job_data.get('url', '')[:50]}...")

    manager = CupidoManager()

    tipo = job_data.get('tipo')
    url = job_data.get('url')
    agente = job_data.get('agente_telefono')
    mensaje = job_data.get('mensaje_completo')
    grupo_id = job_data.get('grupo_id')
    nombre = job_data.get('nombre_agente')

    result = None

    # Procesar segun tipo
    if tipo == 'captacion_wasi':
        result = manager.procesar_captacion_wasi(
            url_wasi=url,
            agente_telefono=agente,
            mensaje_completo=mensaje,
            grupo_id=grupo_id,
            nombre_agente=nombre
        )
    elif tipo == 'captacion_tu360':
        result = manager.procesar_captacion_tu360(
            url_tu360=url,
            agente_telefono=agente,
            mensaje_completo=mensaje,
            grupo_id=grupo_id,
            nombre_agente=nombre
        )
    elif tipo == 'captacion_lobbie':
        result = manager.procesar_captacion_lobbie(
            url_lobbie=url,
            agente_telefono=agente,
            origen='Grupo',
            grupo_id=grupo_id,
            mensaje_completo=mensaje
        )
    else:
        print(f"[WORKER] Tipo no reconocido: {tipo}")
        return {'success': False, 'error': 'Tipo no reconocido'}

    # Actualizar stats del grupo si fue exitoso
    if result and result.get('success'):
        print(f"[WORKER] Captura exitosa - ID: {result.get('propiedad_id')}")
        try:
            with DatabaseManager() as db:
                db.cursor.execute("""
                    UPDATE grupos_whatsapp
                    SET total_capturas = total_capturas + 1,
                        ultima_captura = CURRENT_TIMESTAMP
                    WHERE grupo_id = %s
                """, (grupo_id,))
                db.conn.commit()
        except Exception as e:
            print(f"[WORKER] Error actualizando stats: {e}")
    else:
        print(f"[WORKER] Error: {result.get('error', 'Desconocido') if result else 'Sin resultado'}")

    return result
