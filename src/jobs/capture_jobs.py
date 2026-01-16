"""
Jobs de captura para procesamiento en background con Redis Queue.
Estos jobs se ejecutan en el worker dyno de forma asincrona.

Incluye:
- Logging estructurado para Papertrail
- Sentry tags y custom events
- New Relic custom metrics
"""
import os
import time
import sentry_sdk
import newrelic.agent
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
    start_time = time.time()
    job_id = os.getenv('RQ_JOB_ID', 'unknown')

    # Extraer datos del job
    tipo = job_data.get('tipo', 'unknown')
    url = job_data.get('url', '')
    agente = job_data.get('agente_telefono', '')
    mensaje = job_data.get('mensaje_completo', '')
    grupo_id = job_data.get('grupo_id', '')
    nombre = job_data.get('nombre_agente')
    source = tipo.replace('captacion_', '') if tipo else 'unknown'

    # === FASE 1: Logging estructurado ===
    print(f"[WORKER] START job_id={job_id} tipo={source} agente={agente[:15] if agente else 'N/A'} grupo={grupo_id[:25] if grupo_id else 'N/A'}")

    # === FASE 4: Sentry tags ===
    sentry_sdk.set_tag("worker", "capture")
    sentry_sdk.set_tag("source", source)
    sentry_sdk.set_tag("grupo_id", grupo_id[:25] if grupo_id else "direct")
    if agente:
        sentry_sdk.set_user({"phone": agente})

    # === FASE 2: Sentry context ===
    sentry_sdk.set_context("job_data", {
        "job_id": job_id,
        "tipo": tipo,
        "url": url[:100] if url else None,
        "agente": agente,
        "grupo_id": grupo_id,
        "nombre_agente": nombre
    })

    # === FASE 3: New Relic - marcar inicio ===
    newrelic.agent.record_custom_metric('Custom/Capture/Started', 1)

    manager = CupidoManager()
    result = None

    try:
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
            print(f"[WORKER] ERROR job_id={job_id} error=tipo_no_reconocido tipo={tipo}")
            newrelic.agent.record_custom_metric('Custom/Capture/InvalidType', 1)
            return {'success': False, 'error': 'Tipo no reconocido'}

        # Calcular tiempo de ejecucion
        elapsed_ms = (time.time() - start_time) * 1000

        # Actualizar stats del grupo si fue exitoso
        if result and result.get('success'):
            propiedad_id = result.get('propiedad_id')

            # === FASE 1: Log estructurado de exito ===
            print(f"[WORKER] SUCCESS job_id={job_id} propiedad_id={propiedad_id} tipo={source} tiempo={elapsed_ms:.0f}ms")

            # === FASE 2: Sentry event de exito ===
            sentry_sdk.set_context("propiedad", {
                "id": propiedad_id,
                "fuente": source
            })

            # === FASE 3: New Relic metrics de exito ===
            newrelic.agent.record_custom_metric('Custom/Capture/Success', 1)
            newrelic.agent.record_custom_metric('Custom/Capture/Duration', elapsed_ms)
            newrelic.agent.record_custom_metric(f'Custom/Capture/{source.capitalize()}/Count', 1)
            newrelic.agent.record_custom_metric(f'Custom/Capture/{source.capitalize()}/Duration', elapsed_ms)

            # Actualizar stats del grupo
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
                print(f"[WORKER] WARN job_id={job_id} error=stats_update msg={str(e)[:50]}")
        else:
            error_msg = result.get('error', 'Desconocido') if result else 'Sin resultado'

            # === FASE 1: Log estructurado de error ===
            print(f"[WORKER] FAIL job_id={job_id} tipo={source} error={error_msg[:80]} tiempo={elapsed_ms:.0f}ms")

            # === FASE 3: New Relic metrics de fallo ===
            newrelic.agent.record_custom_metric('Custom/Capture/Failure', 1)
            newrelic.agent.record_custom_metric(f'Custom/Capture/{source.capitalize()}/Failure', 1)

        return result

    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000

        # === FASE 1: Log estructurado de excepcion ===
        print(f"[WORKER] EXCEPTION job_id={job_id} tipo={source} error={str(e)[:100]} tiempo={elapsed_ms:.0f}ms")

        # === FASE 3: New Relic metrics de excepcion ===
        newrelic.agent.record_custom_metric('Custom/Capture/Exception', 1)

        # Sentry captura automaticamente la excepcion, pero agregamos contexto
        sentry_sdk.capture_exception(e)

        return {'success': False, 'error': str(e)}
