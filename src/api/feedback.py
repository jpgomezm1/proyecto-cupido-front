#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API Blueprint para Sistema de Feedback
Permite a usuarios de chat enviar feedback y a admins gestionarlo
"""

from flask import Blueprint, request, jsonify
from flask_cors import CORS
import traceback

from src.db.database import DatabaseManager
from src.api.chat_auth import require_chat_auth
from src.api.auth import token_required

feedback_bp = Blueprint('feedback', __name__, url_prefix='/api/feedback')

CORS(feedback_bp, supports_credentials=True)

CATEGORIAS_VALIDAS = ['administrador', 'busqueda_propiedades', 'ai_search', 'general', 'otro']
ESTADOS_VALIDOS = ['nuevo', 'en_revision', 'resuelto', 'descartado']
PRIORIDADES_VALIDAS = ['baja', 'media', 'alta', 'urgente']
MAX_IMAGENES = 5


# ============================================================================
# ENDPOINTS PARA USUARIOS DE CHAT
# ============================================================================

@feedback_bp.route('', methods=['POST'])
@require_chat_auth
def create_feedback():
    """
    POST /api/feedback
    Envia feedback desde un usuario de chat

    Body JSON:
    {
        "categoria": "administrador",
        "contenido": "Texto del feedback...",
        "imagenes": [{"data": "base64...", "nombre": "foto.jpg", "tipo": "image/jpeg"}]
    }
    """
    db = None
    try:
        db = DatabaseManager()
        db.connect()
        user_id = request.chat_user['id']
        data = request.get_json()

        if not data:
            return jsonify({'success': False, 'error': 'No se enviaron datos'}), 400

        categoria = data.get('categoria', '').strip()
        contenido = data.get('contenido', '').strip()
        imagenes = data.get('imagenes', [])

        if not categoria or categoria not in CATEGORIAS_VALIDAS:
            return jsonify({
                'success': False,
                'error': f'Categoria invalida. Opciones: {", ".join(CATEGORIAS_VALIDAS)}'
            }), 400

        if not contenido:
            return jsonify({'success': False, 'error': 'El contenido es requerido'}), 400

        if len(imagenes) > MAX_IMAGENES:
            return jsonify({
                'success': False,
                'error': f'Maximo {MAX_IMAGENES} imagenes permitidas'
            }), 400

        # Validar estructura de imagenes
        import json
        for img in imagenes:
            if not isinstance(img, dict) or 'data' not in img:
                return jsonify({
                    'success': False,
                    'error': 'Formato de imagen invalido'
                }), 400

        db.cursor.execute("""
            INSERT INTO feedback (user_id, categoria, contenido, imagenes)
            VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id, categoria, estado, prioridad, fecha_creacion
        """, (user_id, categoria, contenido, json.dumps(imagenes)))

        result = db.cursor.fetchone()
        feedback_id = result['id']
        db.conn.commit()

        # Generate AI summary in background thread (non-blocking for user)
        import threading

        def _run_ai_analysis(fb_id, fb_contenido, fb_categoria, fb_imagenes):
            try:
                from src.core.feedback_analyzer import analyze_feedback
                ai_result = analyze_feedback(fb_contenido, fb_categoria, fb_imagenes)
                if ai_result:
                    from src.db.database import DatabaseManager as DB
                    resumen_legacy = ai_result.get('resumen_legacy', '')
                    ai_titulo = ai_result.get('titulo')
                    ai_tipo = ai_result.get('tipo')
                    ai_prioridad = ai_result.get('prioridad_sugerida')
                    ai_confianza = ai_result.get('confianza')

                    with DB() as bg_db:
                        bg_db.cursor.execute("""
                            UPDATE feedback
                            SET ai_resumen = %s, ai_titulo = %s, ai_tipo = %s,
                                ai_prioridad_sugerida = %s, ai_confianza = %s,
                                prioridad = COALESCE(%s, prioridad)
                            WHERE id = %s
                        """, (resumen_legacy, ai_titulo, ai_tipo,
                              ai_prioridad, ai_confianza,
                              ai_prioridad, fb_id))
                        bg_db.conn.commit()
                    print(f"[Feedback] AI triage saved for feedback #{fb_id}: "
                          f"tipo={ai_tipo}, prioridad={ai_prioridad}")
            except Exception as ai_err:
                print(f"[Feedback] AI analysis failed (non-critical): {ai_err}")

        threading.Thread(
            target=_run_ai_analysis,
            args=(feedback_id, contenido, categoria, imagenes),
            daemon=True
        ).start()

        return jsonify({
            'success': True,
            'data': {
                'id': feedback_id,
                'categoria': result['categoria'],
                'estado': result['estado'],
                'prioridad': result['prioridad'],
                'fecha_creacion': str(result['fecha_creacion'])
            },
            'message': 'Feedback enviado exitosamente'
        }), 201

    except Exception as e:
        if db and db.conn:
            db.conn.rollback()
        print(f"Error en create_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


@feedback_bp.route('/my', methods=['GET'])
@require_chat_auth
def get_my_feedback():
    """
    GET /api/feedback/my
    Obtiene el historial de feedback del usuario autenticado
    """
    db = None
    try:
        db = DatabaseManager()
        db.connect()
        user_id = request.chat_user['id']

        db.cursor.execute("""
            SELECT id, categoria, contenido, estado, prioridad,
                   notas_admin, fecha_creacion, fecha_actualizacion,
                   jsonb_array_length(COALESCE(imagenes, '[]'::jsonb)) as num_imagenes
            FROM feedback
            WHERE user_id = %s
            ORDER BY fecha_creacion DESC
            LIMIT 50
        """, (user_id,))

        results = db.cursor.fetchall()

        items = []
        for r in results:
            items.append({
                'id': r['id'],
                'categoria': r['categoria'],
                'contenido': r['contenido'][:200],
                'estado': r['estado'],
                'prioridad': r['prioridad'],
                'notas_admin': r['notas_admin'],
                'num_imagenes': r['num_imagenes'],
                'fecha_creacion': str(r['fecha_creacion']) if r['fecha_creacion'] else None,
                'fecha_actualizacion': str(r['fecha_actualizacion']) if r['fecha_actualizacion'] else None
            })

        return jsonify({
            'success': True,
            'data': items,
            'count': len(items)
        }), 200

    except Exception as e:
        print(f"Error en get_my_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if db:
            db.disconnect()


# ============================================================================
# ENDPOINTS PARA ADMIN
# ============================================================================

@feedback_bp.route('', methods=['GET'])
@token_required
def list_feedback():
    """
    GET /api/feedback
    Lista todo el feedback con filtros (admin)

    Query params:
        - estado: filtrar por estado
        - categoria: filtrar por categoria
        - prioridad: filtrar por prioridad
        - tipo: filtrar por ai_tipo
        - sort: prioridad_desc | fecha_desc (default)
        - limit: max resultados (default 50)
        - offset: paginacion
    """
    try:
        estado = request.args.get('estado')
        categoria = request.args.get('categoria')
        prioridad = request.args.get('prioridad')
        tipo = request.args.get('tipo')
        sort = request.args.get('sort', 'fecha_desc')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)

        with DatabaseManager() as db:
            query = """
                SELECT
                    f.id, f.user_id, f.categoria, f.contenido, f.estado,
                    f.prioridad, f.notas_admin, f.ai_resumen,
                    f.ai_titulo, f.ai_tipo, f.ai_prioridad_sugerida, f.ai_confianza,
                    f.fecha_creacion, f.fecha_actualizacion,
                    jsonb_array_length(COALESCE(f.imagenes, '[]'::jsonb)) as num_imagenes,
                    u.nombre as user_nombre,
                    u.email as user_email
                FROM feedback f
                JOIN chat_users u ON u.id = f.user_id
                WHERE 1=1
            """
            params = []

            if estado:
                query += " AND f.estado = %s"
                params.append(estado)

            if categoria:
                query += " AND f.categoria = %s"
                params.append(categoria)

            if prioridad:
                query += " AND f.prioridad = %s"
                params.append(prioridad)

            if tipo:
                query += " AND f.ai_tipo = %s"
                params.append(tipo)

            # Sort
            if sort == 'prioridad_desc':
                query += """ ORDER BY CASE f.prioridad
                    WHEN 'urgente' THEN 1
                    WHEN 'alta' THEN 2
                    WHEN 'media' THEN 3
                    WHEN 'baja' THEN 4
                    ELSE 5 END, f.fecha_creacion DESC"""
            else:
                query += " ORDER BY f.fecha_creacion DESC"

            query += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            db.cursor.execute(query, params)
            results = db.cursor.fetchall()

            # Total count with same filters
            count_query = "SELECT COUNT(*) as total FROM feedback f WHERE 1=1"
            count_params = []
            if estado:
                count_query += " AND f.estado = %s"
                count_params.append(estado)
            if categoria:
                count_query += " AND f.categoria = %s"
                count_params.append(categoria)
            if prioridad:
                count_query += " AND f.prioridad = %s"
                count_params.append(prioridad)
            if tipo:
                count_query += " AND f.ai_tipo = %s"
                count_params.append(tipo)

            db.cursor.execute(count_query, count_params)
            total = db.cursor.fetchone()['total']

            items = []
            for r in results:
                items.append({
                    'id': r['id'],
                    'user_id': r['user_id'],
                    'categoria': r['categoria'],
                    'contenido': r['contenido'][:200],
                    'estado': r['estado'],
                    'prioridad': r['prioridad'],
                    'notas_admin': r['notas_admin'],
                    'ai_resumen': r['ai_resumen'],
                    'ai_titulo': r['ai_titulo'],
                    'ai_tipo': r['ai_tipo'],
                    'ai_prioridad_sugerida': r['ai_prioridad_sugerida'],
                    'ai_confianza': r['ai_confianza'],
                    'num_imagenes': r['num_imagenes'],
                    'user_nombre': r['user_nombre'],
                    'user_email': r['user_email'],
                    'fecha_creacion': r['fecha_creacion'].isoformat() if r['fecha_creacion'] else None,
                    'fecha_actualizacion': r['fecha_actualizacion'].isoformat() if r['fecha_actualizacion'] else None
                })

            return jsonify({
                'success': True,
                'data': items,
                'total': total
            })

    except Exception as e:
        print(f"Error en list_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>', methods=['GET'])
@token_required
def get_feedback_detail(feedback_id):
    """
    GET /api/feedback/<id>
    Detalle de un feedback con imagenes completas (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    f.id, f.user_id, f.categoria, f.contenido, f.imagenes,
                    f.estado, f.prioridad, f.notas_admin, f.ai_resumen,
                    f.ai_titulo, f.ai_tipo, f.ai_prioridad_sugerida, f.ai_confianza,
                    f.fecha_creacion, f.fecha_actualizacion,
                    u.nombre as user_nombre,
                    u.email as user_email
                FROM feedback f
                JOIN chat_users u ON u.id = f.user_id
                WHERE f.id = %s
            """, (feedback_id,))

            r = db.cursor.fetchone()

            if not r:
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            return jsonify({
                'success': True,
                'data': {
                    'id': r['id'],
                    'user_id': r['user_id'],
                    'categoria': r['categoria'],
                    'contenido': r['contenido'],
                    'imagenes': r['imagenes'] or [],
                    'estado': r['estado'],
                    'prioridad': r['prioridad'],
                    'notas_admin': r['notas_admin'],
                    'ai_resumen': r['ai_resumen'],
                    'ai_titulo': r['ai_titulo'],
                    'ai_tipo': r['ai_tipo'],
                    'ai_prioridad_sugerida': r['ai_prioridad_sugerida'],
                    'ai_confianza': r['ai_confianza'],
                    'user_nombre': r['user_nombre'],
                    'user_email': r['user_email'],
                    'fecha_creacion': r['fecha_creacion'].isoformat() if r['fecha_creacion'] else None,
                    'fecha_actualizacion': r['fecha_actualizacion'].isoformat() if r['fecha_actualizacion'] else None
                }
            })

    except Exception as e:
        print(f"Error en get_feedback_detail: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>', methods=['DELETE'])
@token_required
def delete_feedback(feedback_id):
    """
    DELETE /api/feedback/<id>
    Elimina un feedback (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("DELETE FROM feedback WHERE id = %s RETURNING id", (feedback_id,))
            result = db.cursor.fetchone()

            if not result:
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            db.conn.commit()
            return jsonify({'success': True, 'message': 'Feedback eliminado'})

    except Exception as e:
        print(f"Error en delete_feedback: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>/status', methods=['PUT'])
@token_required
def update_feedback_status(feedback_id):
    """
    PUT /api/feedback/<id>/status
    Actualiza estado, prioridad y notas_admin (admin)

    Body JSON:
    {
        "estado": "en_revision",
        "prioridad": "alta",
        "notas_admin": "Revisando el tema..."
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No se enviaron datos'}), 400

        with DatabaseManager() as db:
            # Verify exists
            db.cursor.execute("SELECT id FROM feedback WHERE id = %s", (feedback_id,))
            if not db.cursor.fetchone():
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            updates = []
            params = []

            if 'estado' in data:
                if data['estado'] not in ESTADOS_VALIDOS:
                    return jsonify({
                        'success': False,
                        'error': f'Estado invalido. Opciones: {", ".join(ESTADOS_VALIDOS)}'
                    }), 400
                updates.append("estado = %s")
                params.append(data['estado'])

            if 'prioridad' in data:
                if data['prioridad'] not in PRIORIDADES_VALIDAS:
                    return jsonify({
                        'success': False,
                        'error': f'Prioridad invalida. Opciones: {", ".join(PRIORIDADES_VALIDAS)}'
                    }), 400
                updates.append("prioridad = %s")
                params.append(data['prioridad'])

            if 'notas_admin' in data:
                updates.append("notas_admin = %s")
                params.append(data['notas_admin'])

            if not updates:
                return jsonify({'success': False, 'error': 'No hay campos para actualizar'}), 400

            updates.append("fecha_actualizacion = CURRENT_TIMESTAMP")
            params.append(feedback_id)

            query = f"""
                UPDATE feedback SET {', '.join(updates)}
                WHERE id = %s
                RETURNING id, estado, prioridad, notas_admin, fecha_actualizacion
            """

            db.cursor.execute(query, params)
            result = db.cursor.fetchone()
            db.conn.commit()

            return jsonify({
                'success': True,
                'data': {
                    'id': result['id'],
                    'estado': result['estado'],
                    'prioridad': result['prioridad'],
                    'notas_admin': result['notas_admin'],
                    'fecha_actualizacion': result['fecha_actualizacion'].isoformat() if result['fecha_actualizacion'] else None
                }
            })

    except Exception as e:
        print(f"Error en update_feedback_status: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/<int:feedback_id>/generate-prompt', methods=['POST'])
@token_required
def generate_prompt(feedback_id):
    """
    POST /api/feedback/<id>/generate-prompt
    Genera un prompt accionable para Claude Code basado en el feedback (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT f.categoria, f.contenido, f.ai_resumen, f.imagenes,
                       u.nombre as user_nombre, u.email as user_email
                FROM feedback f
                JOIN chat_users u ON u.id = f.user_id
                WHERE f.id = %s
            """, (feedback_id,))

            r = db.cursor.fetchone()
            if not r:
                return jsonify({'success': False, 'error': 'Feedback no encontrado'}), 404

            import os
            import time
            from anthropic import Anthropic

            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                return jsonify({'success': False, 'error': 'ANTHROPIC_API_KEY no configurada'}), 500

            client = Anthropic(api_key=api_key)

            # Fetch project context
            from src.core.feedback_analyzer import _fetch_project_context
            project_context = _fetch_project_context()

            # Category to module mapping for extra precision
            categoria_module_hints = {
                'administrador': 'This relates to the admin panel (mvp-tu360). Key pages: Dashboard.tsx, Properties.tsx, Deals.tsx, AppSidebar.tsx. API calls go through src/integrations/api/client.ts.',
                'busqueda_propiedades': 'This relates to property search/browsing. Frontend: Properties.tsx, FilterSidebar.tsx, PropertyCard.tsx, PropertyDetail.tsx. Backend: src/api/properties.py, src/db/database.py.',
                'ai_search': 'This relates to the AI-powered search chat (Fynder Search). Frontend: SharedChat.tsx, useConversations.ts. Backend: src/api/conversations.py, src/core/search_agent.py, src/core/search_context.py, src/core/search_config.py.',
                'general': 'General platform issue. Could involve any module.',
                'otro': 'Uncategorized issue. Analyze the content to determine the right module.',
            }

            module_hint = categoria_module_hints.get(r['categoria'], '')

            system_prompt = """You are a senior software engineer and expert prompt engineer. Your task is to generate a comprehensive, actionable prompt that a developer will paste DIRECTLY into Claude Code (Anthropic's AI coding CLI) to resolve a bug or implement a feature request reported by a user.

The prompt you generate will be the ONLY input Claude Code receives. It must be self-contained and precise enough that Claude Code can:
1. Understand the full context of the problem
2. Know exactly which files to read and modify
3. Implement the correct fix without ambiguity
4. Verify the fix works

OUTPUT FORMAT:
- Output ONLY a valid JSON object. No markdown fences, no extra text before or after.
- The JSON MUST follow this exact schema:

{
  "role": "You are working on Fynder, a Colombian real estate platform. The codebase is a monorepo with a Python/Flask backend (proyecto-cupido-front/) and a React/TypeScript frontend (mvp-tu360/).",
  "task": "One clear sentence describing exactly what needs to be fixed or implemented",
  "bug_report": {
    "reported_by": "User name",
    "category": "Feedback category",
    "original_feedback": "The exact user feedback text",
    "ai_analysis": "The AI-generated analysis of the feedback"
  },
  "investigation": {
    "primary_files": ["Exact file paths to read FIRST - these are the most likely locations of the bug"],
    "secondary_files": ["Additional files that may need changes or provide context"],
    "likely_root_cause": "Your best assessment of what is causing the issue based on the architecture"
  },
  "implementation_plan": [
    "Step 1: Read [specific file] and locate [specific function/component]",
    "Step 2: Identify the issue in [specific area]",
    "Step 3: Modify [specific thing] to fix [specific problem]",
    "Step 4: Update [related file] if needed for consistency"
  ],
  "constraints": [
    "Do not break existing functionality",
    "Follow the existing code patterns and conventions in the codebase",
    "Backend API responses must follow format: {success: bool, data: ..., error: ...}",
    "Frontend uses shadcn/ui components, Tailwind CSS, and TanStack Query",
    "Any additional constraint specific to this fix"
  ],
  "acceptance_criteria": [
    "Criterion 1: What must be true when the fix is complete",
    "Criterion 2: Another measurable criterion"
  ],
  "testing_steps": [
    "Step 1: How to manually verify the fix",
    "Step 2: Additional verification"
  ]
}

QUALITY GUIDELINES:
- file paths must be RELATIVE to the project root (e.g., 'mvp-tu360/src/pages/Properties.tsx' or 'proyecto-cupido-front/src/api/properties.py')
- implementation_plan must be SPECIFIC: mention function names, component names, CSS classes, API endpoints
- If the issue involves frontend UI, mention the exact Tailwind classes or component props to change
- If the issue involves backend API, mention the exact endpoint, SQL query, or function
- likely_root_cause should be a technical hypothesis, not just a restatement of the bug
- acceptance_criteria must be measurable and verifiable
- Always include at least 3-5 implementation steps
- Always include at least 2 acceptance criteria"""

            if project_context:
                system_prompt += f"\n\n---\nPROJECT ARCHITECTURE REFERENCE:\n\n{project_context}"

            # Build rich user content
            user_content = f"""Generate a Claude Code prompt for this user feedback.

FEEDBACK METADATA:
- Category: {r['categoria']}
- Reported by: {r['user_nombre']} ({r['user_email']})
- Module hint: {module_hint}
- Has attached images: {'Yes (' + str(len(r['imagenes'] or [])) + ')' if r.get('imagenes') else 'No'}

USER'S ORIGINAL FEEDBACK:
\"\"\"
{r['contenido']}
\"\"\"
"""

            if r['ai_resumen']:
                user_content += f"""
AI ANALYSIS OF THIS FEEDBACK:
\"\"\"
{r['ai_resumen']}
\"\"\"
"""

            user_content += """
Now generate the comprehensive Claude Code prompt as a JSON object. Be as specific as possible about files, functions, and implementation details. The developer should be able to paste this into Claude Code and get the fix done in one shot."""

            start_time = time.time()

            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=3000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}]
            )

            prompt_text = response.content[0].text.strip()

            # Track usage
            try:
                from src.core.ai_usage_tracker import get_ai_tracker
                get_ai_tracker().track_anthropic_response(
                    model='claude-sonnet-4-20250514',
                    usage_type='feedback_prompt_generation',
                    function_name='feedback.generate_prompt',
                    response=response,
                    start_time=start_time,
                    context={'feedback_id': feedback_id, 'categoria': r['categoria']}
                )
            except Exception:
                pass

            # Parse JSON - handle Claude wrapping in markdown
            import json
            try:
                prompt_json = json.loads(prompt_text)
            except json.JSONDecodeError:
                if '```' in prompt_text:
                    json_str = prompt_text.split('```')[1]
                    if json_str.startswith('json'):
                        json_str = json_str[4:]
                    prompt_json = json.loads(json_str.strip())
                else:
                    prompt_json = {"raw": prompt_text}

            return jsonify({
                'success': True,
                'data': {
                    'prompt': prompt_json
                }
            })

    except Exception as e:
        print(f"Error en generate_prompt: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500


@feedback_bp.route('/stats', methods=['GET'])
@token_required
def get_feedback_stats():
    """
    GET /api/feedback/stats
    Estadisticas de feedback (admin)
    """
    try:
        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE estado = 'nuevo') as nuevos,
                    COUNT(*) FILTER (WHERE estado = 'en_revision') as en_revision,
                    COUNT(*) FILTER (WHERE estado = 'resuelto') as resueltos,
                    COUNT(*) FILTER (WHERE estado = 'descartado') as descartados
                FROM feedback
            """)
            stats = db.cursor.fetchone()

            db.cursor.execute("""
                SELECT categoria, COUNT(*) as total
                FROM feedback
                GROUP BY categoria
                ORDER BY total DESC
            """)
            por_categoria = {r['categoria']: r['total'] for r in db.cursor.fetchall()}

            # Priority distribution (active items only)
            db.cursor.execute("""
                SELECT prioridad, COUNT(*) as total
                FROM feedback
                WHERE estado NOT IN ('resuelto', 'descartado')
                GROUP BY prioridad
            """)
            por_prioridad = {r['prioridad']: r['total'] for r in db.cursor.fetchall()}

            # Type distribution (items with AI classification)
            db.cursor.execute("""
                SELECT ai_tipo, COUNT(*) as total
                FROM feedback
                WHERE ai_tipo IS NOT NULL
                GROUP BY ai_tipo
                ORDER BY total DESC
            """)
            por_tipo = {r['ai_tipo']: r['total'] for r in db.cursor.fetchall()}

            return jsonify({
                'success': True,
                'data': {
                    'total': stats['total'],
                    'nuevos': stats['nuevos'],
                    'en_revision': stats['en_revision'],
                    'resueltos': stats['resueltos'],
                    'descartados': stats['descartados'],
                    'por_categoria': por_categoria,
                    'por_prioridad': por_prioridad,
                    'por_tipo': por_tipo
                }
            })

    except Exception as e:
        print(f"Error en get_feedback_stats: {e}")
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500
