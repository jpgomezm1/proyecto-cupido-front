#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bot de WhatsApp para búsqueda inteligente de propiedades
Integración con UltraMSG API
"""

import os
import requests
import json
import re
from typing import Dict, Any, List
from datetime import datetime
from dotenv import load_dotenv
import redis
from rq import Queue
import sentry_sdk
from src.core.search_agent import PropertySearchAgent
from src.core.cupido_manager import CupidoManager

load_dotenv()

# Habilitar/deshabilitar Redis Queue para procesamiento asincrono
USE_REDIS_QUEUE = os.getenv('USE_REDIS_QUEUE', 'false').lower() == 'true'


def get_redis_queue():
    """Obtiene la cola de Redis para capturas."""
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    # Heroku Redis usa certificados auto-firmados, requiere ssl_cert_reqs=None
    if redis_url.startswith('rediss://'):
        conn = redis.from_url(redis_url, ssl_cert_reqs=None)
    else:
        conn = redis.from_url(redis_url)
    return Queue('captures', connection=conn)


class WhatsAppBot:
    """Bot de WhatsApp usando UltraMSG API - Proyecto Cupido"""

    def __init__(self):
        self.instance_id = os.getenv('ULTRAMSG_INSTANCE_ID')
        self.token = os.getenv('ULTRAMSG_TOKEN')
        self.base_url = f"https://api.ultramsg.com/{self.instance_id}"

        if not self.instance_id or not self.token:
            raise ValueError("❌ Faltan credenciales de UltraMSG en .env")

        # Inicializar agente de búsqueda
        self.search_agent = PropertySearchAgent()

        # Inicializar Cupido Manager
        self.cupido = CupidoManager()

        # Guardar sesiones de búsqueda (número -> propiedades)
        # En producción esto debería ser Redis o una BD
        self.user_sessions = {}

        # Cache de grupos activos (se actualiza cada X minutos)
        self._grupos_activos_cache = set()
        self._cache_timestamp = None
        self._cache_ttl = 60  # segundos

        # URL base del frontend (para links en WhatsApp)
        self.frontend_url = os.getenv('FRONTEND_BASE_URL', 'http://localhost:3000')

        # Cargar grupos activos desde DB
        self._refresh_grupos_activos()

        print(f"[OK] WhatsApp Bot inicializado (Proyecto Cupido)")
        print(f"   Instance ID: {self.instance_id}")
        print(f"   Base URL: {self.base_url}")
        print(f"   Frontend URL: {self.frontend_url}")
        print(f"   Grupos activos: {len(self._grupos_activos_cache)}")

    def _refresh_grupos_activos(self):
        """Recarga los grupos activos desde la base de datos."""
        from src.db.database import DatabaseManager
        try:
            with DatabaseManager() as db:
                db.cursor.execute(
                    "SELECT grupo_id FROM grupos_whatsapp WHERE activo = true"
                )
                rows = db.cursor.fetchall()
                self._grupos_activos_cache = {row['grupo_id'] for row in rows}
                self._cache_timestamp = datetime.now()
                print(f"[OK] Grupos activos cargados: {len(self._grupos_activos_cache)}")
        except Exception as e:
            print(f"[WARN] No se pudieron cargar grupos desde DB: {e}")
            # Fallback: usar variable de entorno si existe
            env_grupo = os.getenv('GRUPO_CUPIDO_ID', '')
            if env_grupo:
                self._grupos_activos_cache = {env_grupo}
                print(f"[OK] Usando grupo de .env como fallback: {env_grupo}")

    def _get_grupos_activos(self) -> set:
        """Obtiene los grupos activos, actualizando cache si es necesario."""
        now = datetime.now()
        if (self._cache_timestamp is None or
            (now - self._cache_timestamp).total_seconds() > self._cache_ttl):
            self._refresh_grupos_activos()
        return self._grupos_activos_cache

    def _is_grupo_activo(self, grupo_id: str) -> bool:
        """Verifica si un grupo está activo."""
        grupos = self._get_grupos_activos()
        return grupo_id in grupos

    def _update_grupo_stats(self, grupo_id: str):
        """Actualiza estadísticas del grupo después de una captación."""
        from src.db.database import DatabaseManager
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
            print(f"[WARN] No se pudo actualizar stats del grupo: {e}")

    def send_message(self, to: str, body: str) -> Dict[str, Any]:
        """
        Enviar mensaje de WhatsApp a un número

        Args:
            to: Número de teléfono con formato internacional (ej: +573001234567)
            body: Texto del mensaje (máx 4096 caracteres)

        Returns:
            Respuesta de la API
        """
        url = f"{self.base_url}/messages/chat"

        payload = {
            'token': self.token,
            'to': to,
            'body': body
        }

        try:
            response = requests.post(url, data=payload)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"❌ Error enviando mensaje: {e}")
            return {'error': str(e)}

    def format_property_result(self, prop: Dict[str, Any], index: int) -> str:
        """
        Formatear una propiedad para WhatsApp de forma profesional
        """
        titulo = prop.get('titulo', 'Sin título')
        precio = prop.get('precio_texto', 'Precio no disponible')
        zona = prop.get('zona', 'Zona no disponible')
        habitaciones = prop.get('habitaciones', '?')
        banos = prop.get('banos', '?')
        area = prop.get('area_construida', '?')
        estrato = prop.get('estrato', '')
        administracion = prop.get('administracion', '')
        parqueaderos = prop.get('parqueaderos', '')
        url = prop.get('url', '')

        # Amenidades
        amenidades_int = prop.get('amenidades_internas', '')
        amenidades_ext = prop.get('amenidades_externas', '')

        # Construir mensaje limpio y profesional
        msg = f"\n🏠 *OPCIÓN {index}*\n"
        msg += f"━━━━━━━━━━━━━━━━━━\n\n"

        # Título limpio
        msg += f"*{titulo}*\n\n"

        # Precio destacado
        msg += f"💰 *{precio}*\n\n"

        # Características principales
        msg += f"📋 *Características:*\n"
        msg += f"• {habitaciones} habitaciones | {banos} baños\n"
        msg += f"• Área: {area} m²\n"

        if parqueaderos:
            msg += f"• Parqueaderos: {parqueaderos}\n"

        if estrato:
            msg += f"• Estrato {estrato}\n"

        if administracion:
            try:
                admin_formatted = f"${int(administracion):,}".replace(',', '.')
                msg += f"• Administración: {admin_formatted}\n"
            except:
                pass

        # Amenidades (más compacto)
        amenidades = []
        if amenidades_int:
            amenidades.extend(amenidades_int.split(' | ')[:4])
        if amenidades_ext and len(amenidades) < 6:
            amenidades.extend(amenidades_ext.split(' | ')[:6-len(amenidades)])

        if amenidades:
            msg += f"\n✨ *Incluye:*\n"
            # Dividir en líneas de 2 amenidades
            for i in range(0, len(amenidades), 2):
                if i+1 < len(amenidades):
                    msg += f"• {amenidades[i]} • {amenidades[i+1]}\n"
                else:
                    msg += f"• {amenidades[i]}\n"

        # URL shareable (solo el link de compartir, no la fuente original)
        slug = prop.get('slug')
        if slug:
            # URL del frontend para compartir
            shareable_link = f"{self.frontend_url}/compartir/{slug}"
            msg += f"\n🔗 *Ver detalles:*\n{shareable_link}\n"
        else:
            # Fallback: usar ID si no hay slug
            propiedad_id = prop.get('id')
            if propiedad_id:
                msg += f"\n🔗 *Ver detalles:*\n{self.frontend_url}/compartir/{propiedad_id}\n"

        return msg

    def process_search_query(self, query: str, sender: str) -> str:
        """
        Procesar consulta de búsqueda y generar respuesta

        Args:
            query: Consulta en lenguaje natural
            sender: Número de teléfono del remitente

        Returns:
            Mensaje de respuesta formateado
        """
        print(f"\n📱 Procesando consulta de {sender}")
        print(f"📝 Query: {query[:100]}...")

        # Realizar búsqueda
        try:
            result = self.search_agent.search(query, limit=5)

            if not result.get('success'):
                return f"❌ Lo siento, hubo un error procesando tu búsqueda:\n{result.get('error', 'Error desconocido')}"

            criteria = result.get('criteria', {})
            properties = result.get('results', [])
            total_found = result.get('total_found', 0)

            # Construir respuesta más limpia
            response = "✅ *Búsqueda completada*\n\n"

            # Mostrar criterios de forma compacta
            response += "🔍 *Tu búsqueda:*\n"

            if criteria.get('ubicaciones'):
                response += f"📍 {', '.join(criteria['ubicaciones'])}\n"
            if criteria.get('tipo_propiedad'):
                tipo = criteria['tipo_propiedad']
                habs = ""
                if criteria.get('habitaciones_min'):
                    habs = f" • {criteria['habitaciones_min']}"
                    if criteria.get('habitaciones_max') and criteria['habitaciones_max'] != criteria['habitaciones_min']:
                        habs += f"-{criteria['habitaciones_max']}"
                    habs += " hab"
                response += f"🏠 {tipo}{habs}\n"
            if criteria.get('precio_max'):
                precio_max = f"${criteria['precio_max']:,}".replace(',', '.')
                response += f"💰 Hasta {precio_max}\n"

            if not properties:
                response += "\n😔 No encontramos propiedades con estos criterios.\n\n"
                response += "💡 *Intenta:*\n"
                response += "• Ampliar presupuesto\n"
                response += "• Buscar en zonas cercanas\n"
                response += "• Reducir requisitos\n"
                return response

            response += f"\n📊 *{total_found} propiedades encontradas*\n"
            response += f"Te muestro las mejores {len(properties)} opciones:\n"

            # Enviar cada propiedad como mensaje separado (para no exceder límite)
            return response

        except Exception as e:
            print(f"❌ Error en búsqueda: {e}")
            import traceback
            traceback.print_exc()
            return f"❌ Lo siento, ocurrió un error inesperado:\n{str(e)}"

    def send_search_results(self, to: str, query: str) -> bool:
        """
        Realizar búsqueda y enviar resultados al usuario

        Args:
            to: Número de WhatsApp del destinatario
            query: Consulta de búsqueda

        Returns:
            True si se enviaron correctamente, False en caso contrario
        """
        try:
            # Realizar búsqueda
            result = self.search_agent.search(query, limit=5)

            if not result.get('success'):
                error_msg = f"❌ Error en búsqueda:\n{result.get('error', 'Error desconocido')}"
                self.send_message(to, error_msg)
                return False

            # Enviar mensaje inicial con criterios
            initial_response = self.process_search_query(query, to)
            self.send_message(to, initial_response)

            # Enviar cada propiedad en mensaje separado
            properties = result.get('results', [])

            if properties:
                # Guardar propiedades en la sesión del usuario
                self.user_sessions[to] = {
                    'properties': properties,
                    'query': query,
                    'timestamp': datetime.now().isoformat()
                }

                for i, prop in enumerate(properties, 1):
                    prop_msg = self.format_property_result(prop, i)
                    self.send_message(to, prop_msg)

                # Mensaje final con opciones de selección
                final_msg = f"\n━━━━━━━━━━━━━━━━━━\n\n"
                final_msg += f"✅ ¡Listo! Te envié {len(properties)} opciones.\n\n"
                final_msg += f"📝 *¿Cuáles te interesan para ofrecerle a tu cliente?*\n\n"
                final_msg += f"Responde con el número o números de las opciones que te gustan:\n\n"

                # Listar opciones de forma clara
                for i in range(1, len(properties) + 1):
                    final_msg += f"• *{i}* - Para la opción {i}\n"

                final_msg += f"• *Ninguna* - Si no te convence ninguna\n"
                final_msg += f"• *Todas* - Si te interesan todas\n\n"
                final_msg += f"_Ejemplos: \"1\", \"1 y 3\", \"todas\", \"ninguna\"_"

                self.send_message(to, final_msg)

            return True

        except Exception as e:
            print(f"❌ Error enviando resultados: {e}")
            import traceback
            traceback.print_exc()

            error_msg = f"❌ Lo siento, ocurrió un error:\n{str(e)}"
            self.send_message(to, error_msg)
            return False

    def send_search_results_cupido(self, to: str, propiedades: List[Dict], solicitud_id: int) -> bool:
        """
        Enviar resultados de búsqueda con integración Proyecto Cupido
        Incluye información de contacto según el origen de la propiedad

        Args:
            to: Número de WhatsApp del destinatario
            propiedades: Lista de propiedades encontradas
            solicitud_id: ID de la solicitud de mercado en la DB

        Returns:
            True si se enviaron correctamente
        """
        try:
            # Mensaje inicial
            initial_msg = f"🔍 *Resultados de tu búsqueda*\n\n"
            initial_msg += f"✅ Encontré {len(propiedades)} propiedades que coinciden con lo que buscas:\n"

            self.send_message(to, initial_msg)

            # Guardar propiedades en la sesión
            self.user_sessions[to] = {
                'properties': propiedades,
                'solicitud_id': solicitud_id,
                'timestamp': datetime.now().isoformat()
            }

            # Enviar cada propiedad
            for i, prop in enumerate(propiedades, 1):
                prop_msg = self.format_property_result(prop, i)
                self.send_message(to, prop_msg)

            # Mensaje final con opciones
            final_msg = f"\n━━━━━━━━━━━━━━━━━━\n\n"
            final_msg += f"✅ ¡Listo! Te envié {len(propiedades)} opciones.\n\n"
            final_msg += f"📝 *¿Cuáles te interesan?*\n\n"
            final_msg += f"Responde con los números de las que quieras contactar:\n\n"

            for i in range(1, len(propiedades) + 1):
                final_msg += f"• *{i}* - Para la opción {i}\n"

            final_msg += f"• *Ninguna* - Si no te convence ninguna\n"
            final_msg += f"• *Todas* - Si te interesan todas\n\n"
            final_msg += f"_Ejemplos: \"1\", \"1 y 3\", \"todas\", \"ninguna\"_"

            self.send_message(to, final_msg)

            return True

        except Exception as e:
            print(f"❌ Error enviando resultados Cupido: {e}")
            import traceback
            traceback.print_exc()
            return False

    def parse_selection(self, message: str, total_options: int) -> List[int]:
        """
        Parsear la selección del usuario

        Args:
            message: Mensaje del usuario
            total_options: Total de opciones disponibles

        Returns:
            Lista de números seleccionados, o lista vacía si es "ninguna"
        """
        message_lower = message.lower().strip()

        # Caso especial: ninguna
        if 'ninguna' in message_lower or 'ninguno' in message_lower:
            return []

        # Caso especial: todas
        if 'todas' in message_lower or 'todos' in message_lower or 'all' in message_lower:
            return list(range(1, total_options + 1))

        # Extraer números del mensaje
        numbers = re.findall(r'\d+', message)
        selected = []

        for num_str in numbers:
            try:
                num = int(num_str)
                if 1 <= num <= total_options:
                    if num not in selected:
                        selected.append(num)
            except:
                continue

        return sorted(selected)

    def handle_property_selection(self, sender: str, message: str) -> Dict[str, Any]:
        """
        Procesar selección de propiedades

        Args:
            sender: Número del usuario
            message: Mensaje con la selección

        Returns:
            Diccionario con el resultado
        """
        # Verificar si hay una sesión activa
        if sender not in self.user_sessions:
            return {
                'status': 'no_session',
                'message': None
            }

        session = self.user_sessions[sender]
        properties = session['properties']
        total_options = len(properties)

        # Parsear selección
        selected = self.parse_selection(message, total_options)

        if not selected and 'ninguna' not in message.lower():
            # No se entendió la selección
            return {
                'status': 'invalid_selection',
                'message': None
            }

        # Ninguna propiedad
        if not selected:
            response = "👌 Entendido, ninguna de estas propiedades te interesa.\n\n"
            response += "🔍 ¿Quieres hacer otra búsqueda con criterios diferentes?\n"
            response += "Escríbeme qué necesitas."

            self.send_message(sender, response)

            # Limpiar sesión
            del self.user_sessions[sender]

            return {
                'status': 'none_selected',
                'selected': [],
                'message': 'ninguna'
            }

        # Propiedades seleccionadas
        selected_properties = [properties[i-1] for i in selected]

        # Obtener IDs de propiedades seleccionadas
        propiedades_ids = [prop.get('id') for prop in selected_properties if prop.get('id')]

        # Mensaje de confirmación
        response = f"✅ *Perfecto!* Seleccionaste {len(selected)} propiedad"
        response += "es" if len(selected) > 1 else ""
        response += ":\n\n"

        for i, prop_idx in enumerate(selected, 1):
            prop = properties[prop_idx - 1]
            titulo = prop.get('titulo', 'Sin título')[:50]
            precio = prop.get('precio_texto', 'N/A')
            response += f"*{prop_idx}.* {titulo}\n"
            response += f"   💰 {precio}\n\n"

        self.send_message(sender, response)

        # ===================================================================
        # INTEGRACIÓN CUPIDO: Procesar selección y obtener información de contacto
        # ===================================================================

        solicitud_id = session.get('solicitud_id')

        # Procesar selección con Cupido Manager
        result = self.cupido.procesar_seleccion_propiedades(
            agente_telefono=sender,
            propiedades_seleccionadas=propiedades_ids,
            solicitud_id=solicitud_id
        )

        if result['success']:
            # Enviar información de contacto unificada (siempre Hernán Ríos)
            msg_contacto = f"📞 *Información de contacto*\n\n"

            for seleccion in result['selecciones']:
                propiedad = seleccion['propiedad']
                contacto = seleccion['contacto']
                nombre = seleccion['contacto_nombre']

                titulo = propiedad.get('titulo', 'Sin título')[:40]

                msg_contacto += f"🏠 *{titulo}*\n"
                msg_contacto += f"📱 Contactar a: *{nombre}*\n"
                msg_contacto += f"   Teléfono: {contacto}\n"
                msg_contacto += f"   _(Asesor inmobiliario)_\n\n"

            msg_contacto += f"💡 _Coordina con Hernán para agendar tu visita y resolver todas tus dudas._"

            self.send_message(sender, msg_contacto)

        # Limpiar sesión
        del self.user_sessions[sender]

        return {
            'status': 'selected',
            'selected': selected,
            'properties': selected_properties
        }

    def handle_incoming_message(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Manejar mensaje entrante desde webhook

        MODO ACTUAL: Solo captación silenciosa desde el grupo configurado.
        - Ignora TODOS los mensajes privados
        - Solo procesa mensajes del grupo GRUPO_CUPIDO_ID
        - Solo capta propiedades (links Wasi/Tu360) de forma silenciosa
        - NO responde nada al grupo

        Args:
            webhook_data: Datos del webhook de UltraMSG

        Returns:
            Respuesta procesada
        """
        try:
            # UltraMSG envía los datos dentro de 'data'
            if 'data' in webhook_data:
                message_data = webhook_data['data']
            else:
                message_data = webhook_data

            # Extraer información del webhook
            sender = message_data.get('from', '')
            to = message_data.get('to', '')
            message_body = message_data.get('body', '')
            message_type = message_data.get('type', 'chat')
            event_type = webhook_data.get('event_type', '')

            # Ignorar eventos que no son mensajes nuevos
            if event_type not in ['message_received', '']:
                return {'status': 'ignored', 'reason': 'not_message_received'}

            # Ignorar mensajes propios (fromMe)
            if message_data.get('fromMe') or message_data.get('self'):
                return {'status': 'ignored', 'reason': 'own_message'}

            # Detectar si es mensaje de grupo
            is_group_message = '@g.us' in sender or '@g.us' in to
            grupo_id = sender if '@g.us' in sender else (to if '@g.us' in to else None)

            # Verificar si tiene URL
            url_pattern = r'https?://[^\s]+'
            has_url = bool(re.search(url_pattern, message_body))

            # === FASE 1: Logging estructurado ===
            print(f"[WEBHOOK] from={sender[:20] if sender else 'N/A'} grupo={grupo_id[:25] if grupo_id else 'private'} has_url={has_url} type={message_type}")

            # === FASE 4: Sentry tags ===
            sentry_sdk.set_tag("message_source", "group" if is_group_message else "private")
            sentry_sdk.set_tag("grupo_id", grupo_id[:25] if grupo_id else "none")
            sentry_sdk.set_tag("has_url", str(has_url))

            # =====================================================================
            # FILTRO CRÍTICO: Solo procesar mensajes del grupo configurado
            # =====================================================================

            # IGNORAR todos los mensajes que NO son de grupos
            if not is_group_message:
                # Mensaje privado - IGNORAR completamente
                return {'status': 'ignored', 'reason': 'private_message_not_allowed'}

            # Es mensaje de grupo - verificar que sea un grupo activo en la DB
            if not self._is_grupo_activo(grupo_id):
                return {'status': 'ignored', 'reason': 'group_not_active'}

            print(f"   ✅ Mensaje de grupo activo: {grupo_id[:30]}...")

            # =====================================================================
            # PROCESAMIENTO: Solo mensajes del grupo Cupido llegan aquí
            # =====================================================================

            # Ignorar mensajes que no son de texto
            if message_type != 'chat':
                return {'status': 'ignored', 'reason': 'unsupported_type'}

            # Ignorar mensajes vacíos
            if not message_body or len(message_body.strip()) < 1:
                return {'status': 'ignored', 'reason': 'empty_message'}

            # =====================================================================
            # FILTRO RÁPIDO: Solo procesar mensajes que contengan URL
            # (Ahorra tokens de AI - no se procesa nada sin URL)
            # =====================================================================

            url_pattern = r'https?://[^\s]+'
            if not re.search(url_pattern, message_body):
                # No hay URL en el mensaje - ignorar silenciosamente
                return {'status': 'ignored', 'reason': 'no_url_in_message'}

            # =====================================================================
            # El mensaje tiene URL - proceder con captación
            # =====================================================================

            print(f"\n📩 Mensaje del grupo Cupido (contiene URL)")
            print(f"📝 Contenido: {message_body[:100]}...")

            # Extraer teléfono del participante
            author = message_data.get('author', '')
            if author and '@c.us' in author:
                sender = author.replace('@c.us', '')
                if not sender.startswith('+'):
                    sender = '+' + sender
                print(f"   👤 Participante: {sender}")
            else:
                return {'status': 'ignored', 'reason': 'no_participant_info'}

            # Extraer nombre del agente
            nombre_agente = message_data.get('pushname', None)
            if nombre_agente:
                print(f"   👤 Nombre: {nombre_agente}")

            # =====================================================================
            # CAPTACIÓN SILENCIOSA: Detectar tipo de link (Wasi, Tu360, Lobbie)
            # =====================================================================

            deteccion = self.cupido.detectar_tipo_mensaje(message_body, sender, True)
            print(f"🔍 Tipo detectado: {deteccion['tipo']}")

            # =====================================================================
            # REDIS QUEUE: Si esta habilitado, encolar para procesamiento async
            # =====================================================================
            if USE_REDIS_QUEUE and deteccion['tipo'] in ['captacion_wasi', 'captacion_tu360', 'captacion_lobbie']:
                from src.jobs.capture_jobs import process_capture_job

                # === FASE 4: Sentry tags para captacion ===
                capture_type = deteccion['tipo'].replace('captacion_', '')
                sentry_sdk.set_tag("capture_type", capture_type)
                sentry_sdk.set_user({"phone": sender})

                queue = get_redis_queue()
                job = queue.enqueue(
                    process_capture_job,
                    {
                        'tipo': deteccion['tipo'],
                        'url': deteccion['data']['url'],
                        'agente_telefono': sender,
                        'mensaje_completo': message_body,
                        'grupo_id': grupo_id,
                        'nombre_agente': nombre_agente
                    },
                    job_timeout=120
                )

                # === FASE 1: Logging estructurado ===
                print(f"[WEBHOOK] ENQUEUED job_id={job.id} tipo={capture_type} agente={sender[:15]} grupo={grupo_id[:25]}")

                return {
                    'status': 'queued',
                    'job_id': job.id,
                    'tipo': deteccion['tipo']
                }

            # =====================================================================
            # PROCESAMIENTO SINCRONO (fallback si Redis no esta habilitado)
            # =====================================================================

            # CASO 1: Link de Wasi
            if deteccion['tipo'] == 'captacion_wasi':
                url = deteccion['data']['url']
                print(f"📥 Captando propiedad de Wasi: {url}")

                result = self.cupido.procesar_captacion_wasi(
                    url_wasi=url,
                    agente_telefono=sender,
                    mensaje_completo=message_body,
                    grupo_id=grupo_id,
                    nombre_agente=nombre_agente
                )

                if result['success']:
                    print(f"   ✅ Wasi captada (ID: {result['propiedad_id']})")
                    self._update_grupo_stats(grupo_id)
                    return {'status': 'captacion_exitosa', 'propiedad_id': result['propiedad_id'], 'fuente': 'Wasi'}
                else:
                    print(f"   ❌ Error: {result.get('error', 'Desconocido')}")
                    return {'status': 'captacion_error', 'error': result.get('error'), 'fuente': 'Wasi'}

            # CASO 2: Link de Tu360
            elif deteccion['tipo'] == 'captacion_tu360':
                url = deteccion['data']['url']
                print(f"📥 Captando propiedad de Tu360: {url}")

                result = self.cupido.procesar_captacion_tu360(
                    url_tu360=url,
                    agente_telefono=sender,
                    mensaje_completo=message_body,
                    grupo_id=grupo_id,
                    nombre_agente=nombre_agente
                )

                if result['success']:
                    print(f"   ✅ Tu360 captada (ID: {result['propiedad_id']})")
                    self._update_grupo_stats(grupo_id)
                    return {'status': 'captacion_exitosa', 'propiedad_id': result['propiedad_id'], 'fuente': 'Tu360'}
                else:
                    print(f"   ❌ Error: {result.get('error', 'Desconocido')}")
                    return {'status': 'captacion_error', 'error': result.get('error'), 'fuente': 'Tu360'}

            # CASO 3: Link de LobiApp
            elif deteccion['tipo'] == 'captacion_lobbie':
                url = deteccion['data']['url']
                print(f"📥 Captando propiedad de LobiApp: {url}")

                result = self.cupido.procesar_captacion_lobbie(
                    url_lobbie=url,
                    agente_telefono=sender,
                    origen='Grupo',
                    grupo_id=grupo_id,
                    mensaje_completo=message_body
                )

                if result['success']:
                    print(f"   ✅ LobiApp captada (ID: {result['propiedad_id']})")
                    self._update_grupo_stats(grupo_id)
                    return {'status': 'captacion_exitosa', 'propiedad_id': result['propiedad_id'], 'fuente': 'Lobbie'}
                else:
                    print(f"   ❌ Error: {result.get('error', 'Desconocido')}")
                    return {'status': 'captacion_error', 'error': result.get('error'), 'fuente': 'Lobbie'}

            # CASO 4: Tiene URL pero no es de ninguna fuente conocida
            else:
                print(f"   ⏭️  URL no reconocida (no es Wasi/Tu360/Lobbie)")
                return {'status': 'ignored', 'reason': 'unknown_url_source'}

        except Exception as e:
            print(f"❌ Error manejando mensaje entrante: {e}")
            import traceback
            traceback.print_exc()
            # NO enviar mensajes de error - modo silencioso
            return {
                'status': 'error',
                'error': str(e)
            }


if __name__ == "__main__":
    # Test rápido de envío
    print("🧪 Test de WhatsApp Bot")

    try:
        bot = WhatsAppBot()

        # Número de prueba (cambiar por tu número)
        test_number = input("📱 Ingresa número de WhatsApp para test (formato +57300...): ")

        if test_number:
            # Mensaje de bienvenida
            print("\n📤 Enviando mensaje de prueba...")
            result = bot.send_message(
                test_number,
                "🤖 *Test Bot TU360*\n\n¡Hola! Este es un mensaje de prueba del bot de búsqueda de propiedades. ¿Está funcionando? ✅"
            )
            print(f"✅ Resultado: {result}")
        else:
            print("⚠️  No se ingresó número de prueba")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
