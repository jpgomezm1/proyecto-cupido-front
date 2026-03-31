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

        # Cache de grupos activos: {grupo_id: tipo} (se actualiza cada X minutos)
        self._grupos_activos_cache = {}
        self._cache_timestamp = None
        self._cache_ttl = 60  # segundos

        # URL base del frontend (para links en WhatsApp)
        self.frontend_url = 'https://fyndercol.netlify.app'

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
                    "SELECT grupo_id, COALESCE(tipo, 'oferta') as tipo FROM grupos_whatsapp WHERE activo = true"
                )
                rows = db.cursor.fetchall()
                self._grupos_activos_cache = {row['grupo_id']: row['tipo'] for row in rows}
                self._cache_timestamp = datetime.now()
                print(f"[OK] Grupos activos cargados: {len(self._grupos_activos_cache)}")
        except Exception as e:
            print(f"[WARN] No se pudieron cargar grupos desde DB: {e}")
            # Fallback: usar variable de entorno si existe
            env_grupo = os.getenv('GRUPO_CUPIDO_ID', '')
            if env_grupo:
                self._grupos_activos_cache = {env_grupo: 'oferta'}
                print(f"[OK] Usando grupo de .env como fallback: {env_grupo}")

    def _get_grupos_activos(self) -> dict:
        """Obtiene los grupos activos {grupo_id: tipo}, actualizando cache si es necesario."""
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

    def _get_tipo_grupo(self, grupo_id: str) -> str:
        """Retorna 'oferta' o 'demanda' para un grupo activo."""
        grupos = self._get_grupos_activos()
        return grupos.get(grupo_id, 'oferta')

    # Keywords que excluyen auto-respuesta
    _EXCLUIR_AUTO = ['bodega', 'lote', 'terreno', 'finca', 'local comercial', 'oficina']
    _PRESUPUESTO_MIN_AUTO = 450_000_000

    def _is_auto_responder_enabled(self) -> bool:
        """Consulta la DB para saber si el auto-responder esta habilitado."""
        try:
            from src.db.database import DatabaseManager
            with DatabaseManager() as db:
                db.cursor.execute("SELECT value FROM system_config WHERE key = 'auto_responder_enabled'")
                row = db.cursor.fetchone()
                return row['value'] == 'true' if row else False
        except Exception:
            return False

    def _handle_demanda_message(self, message_data: dict, message_body: str,
                                 message_type: str, grupo_id: str) -> dict:
        """Procesa un mensaje de un grupo de demanda — captura pedidos."""
        try:
            if message_type != 'chat':
                return {'status': 'ignored', 'reason': 'demanda_unsupported_type'}

            if not message_body or len(message_body.strip()) < 10:
                return {'status': 'ignored', 'reason': 'demanda_message_too_short'}

            # Extraer info del agente
            author = message_data.get('author', '')
            agente_telefono = None
            if author and '@c.us' in author:
                agente_telefono = author.replace('@c.us', '')
                if not agente_telefono.startswith('+'):
                    agente_telefono = '+' + agente_telefono

            agente_nombre = message_data.get('pushname', None)
            texto_pedido = message_body.strip()

            print(f"\n📋 Mensaje de grupo demanda")
            print(f"   👤 Agente: {agente_nombre or 'N/A'} ({agente_telefono or 'N/A'})")
            print(f"   📝 Texto: {texto_pedido[:100]}...")

            # Deduplicacion: mismo texto + mismo agente en las ultimas 24h = duplicado
            from src.db.database import DatabaseManager
            with DatabaseManager() as db:
                db.cursor.execute("""
                    SELECT id FROM pedidos
                    WHERE agente_telefono = %s
                      AND texto_pedido = %s
                      AND fecha_captura >= NOW() - INTERVAL '24 hours'
                    LIMIT 1
                """, (agente_telefono, texto_pedido))
                duplicado = db.cursor.fetchone()
                if duplicado:
                    print(f"   ⏭️ Duplicado detectado (pedido #{duplicado['id']}), ignorado")
                    return {'status': 'ignored', 'reason': 'duplicate', 'original_id': duplicado['id']}

            # Clasificar con AI (solo SI/NO + presupuesto, sin reformatear)
            es_pedido, presupuesto = self._clasificar_y_formatear_pedido(texto_pedido)

            if not es_pedido:
                print(f"   ⏭️ No es un pedido inmobiliario, ignorado")
                return {'status': 'ignored', 'reason': 'not_a_property_request'}

            if not presupuesto:
                print(f"   ⏭️ Sin presupuesto en el pedido, ignorado")
                return {'status': 'ignored', 'reason': 'no_budget'}

            # Guardar en base de datos (texto original, sin reformateo AI)
            from src.db.database import DatabaseManager
            with DatabaseManager() as db:
                db.cursor.execute("""
                    INSERT INTO pedidos (grupo_id, agente_telefono, agente_nombre, texto_pedido, mensaje_completo, presupuesto_estimado)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (grupo_id, agente_telefono, agente_nombre, texto_pedido, message_body, presupuesto))
                pedido_id = db.cursor.fetchone()['id']

                db.cursor.execute("""
                    UPDATE grupos_whatsapp
                    SET total_pedidos = total_pedidos + 1,
                        ultimo_pedido = CURRENT_TIMESTAMP
                    WHERE grupo_id = %s
                """, (grupo_id,))
                db.conn.commit()

            print(f"   ✅ Pedido guardado con ID: {pedido_id}")

            # === AUTO-RESPUESTA: solo si cumple criterios y esta habilitado ===
            auto_enabled = self._is_auto_responder_enabled()
            if (auto_enabled and presupuesto and presupuesto >= self._PRESUPUESTO_MIN_AUTO
                    and agente_telefono and '@g.us' not in agente_telefono):
                texto_lower = texto_pedido.lower()
                es_excluido = any(kw in texto_lower for kw in self._EXCLUIR_AUTO)
                if not es_excluido:
                    print(f"   🤖 Auto-respuesta iniciada (presupuesto=${presupuesto:,.0f})")
                    self._auto_responder_pedido(pedido_id, texto_pedido, agente_telefono)
                else:
                    print(f"   ⏭️ Auto-respuesta omitida: tipo excluido")
            elif presupuesto and presupuesto < self._PRESUPUESTO_MIN_AUTO:
                print(f"   ⏭️ Auto-respuesta omitida: presupuesto ${presupuesto:,.0f} < $800M")

            return {
                'status': 'pedido_capturado',
                'pedido_id': pedido_id,
                'grupo_id': grupo_id
            }

        except Exception as e:
            print(f"[ERROR] Error procesando pedido de demanda: {e}")
            import traceback
            traceback.print_exc()
            return {'status': 'error', 'error': str(e)}

    def _auto_responder_pedido(self, pedido_id: int, texto_pedido: str, agente_telefono: str):
        """
        Auto-busca propiedades, genera shareable link, y envia WhatsApp
        al NUMERO PERSONAL del agente desde la segunda linea UltraMSG.
        JAMAS envia a un grupo.
        """
        try:
            import requests as req
            import uuid

            # SAFEGUARD: NUNCA enviar a un grupo
            if '@g.us' in agente_telefono or not agente_telefono:
                print(f"[AUTO-RESP] BLOQUEADO: {agente_telefono} es grupo o vacio. NO se envia.")
                return

            # 1. Verificar credenciales de la segunda linea
            instance_id = os.getenv('ULTRAMSG_RESPONDER_INSTANCE_ID')
            token = os.getenv('ULTRAMSG_RESPONDER_TOKEN')
            if not instance_id or not token:
                print(f"[AUTO-RESP] Credenciales ULTRAMSG_RESPONDER no configuradas, omitiendo")
                return

            # 2. Buscar propiedades con AI
            from src.core.search_agent import PropertySearchAgent
            agent = PropertySearchAgent()
            search_response = agent.search(texto_pedido, limit=20, sender='auto')

            results = search_response.get('results', [])
            good_results = [r for r in results if r.get('match_score', 0) >= 40][:5]

            from src.db.database import DatabaseManager

            # 3. Si no hay match con score suficiente
            if not good_results:
                print(f"[AUTO-RESP] Pedido {pedido_id}: {len(results)} resultados pero ninguno con score >= 40. NO_MATCH.")
                with DatabaseManager() as db:
                    db.cursor.execute(
                        "UPDATE pedidos SET estado = 'no_match', share_count = 0, canal = 'auto' WHERE id = %s",
                        (pedido_id,)
                    )
                    db.conn.commit()
                return

            property_ids = [r['id'] for r in good_results]

            # 4. Crear shared selection directamente en DB
            share_id = str(uuid.uuid4())[:12]
            with DatabaseManager() as db:
                db.cursor.execute("""
                    INSERT INTO shared_property_selections (share_id, property_ids, created_at, expires_at, view_count)
                    VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '30 days', 0)
                """, (share_id, property_ids))
                db.conn.commit()

            # 5. Construir mensajes (2 mensajes separados)
            link = f"https://fyndercol.netlify.app/compartir/propiedades/{share_id}"
            count = len(property_ids)
            message_text = (
                f"Hola, soy *Hernan Rios*, agente inmobiliario. "
                f"Aca te comparto *{count} propiedades* que encontre segun tu pedido.\n\n"
                f"Quedo super pendiente de cual de las {count} te interesa!\n\n"
                f"Tu pedido fue: _{texto_pedido}_"
            )

            # 6. Enviar 2 WhatsApps al NUMERO PERSONAL (SEGUNDA LINEA, no la de captacion)
            api_url = f"https://api.ultramsg.com/{instance_id}/messages/chat"

            print(f"[AUTO-RESP] Enviando a {agente_telefono} (PERSONAL, no grupo)")

            # Mensaje 1: texto
            resp = req.post(api_url, data={'token': token, 'to': agente_telefono, 'body': message_text}, timeout=30)

            # Mensaje 2: link solo (clickeable)
            import time
            time.sleep(1)
            resp2 = req.post(api_url, data={'token': token, 'to': agente_telefono, 'body': link}, timeout=30)

            # Usar el status del primer mensaje como referencia
            resp = resp if resp.status_code == 200 else resp2

            if resp.status_code == 200:
                # 7. Actualizar pedido en DB
                with DatabaseManager() as db:
                    db.cursor.execute("""
                        UPDATE pedidos
                        SET share_id = %s, share_count = %s, estado = 'procesado', canal = 'auto'
                        WHERE id = %s
                    """, (share_id, count, pedido_id))
                    db.conn.commit()
                print(f"[AUTO-RESP] ✅ Pedido {pedido_id} respondido: {count} props → {agente_telefono}")
            else:
                print(f"[AUTO-RESP] ❌ Error UltraMSG: {resp.status_code} {resp.text[:200]}")

        except Exception as e:
            print(f"[AUTO-RESP] ❌ Error: {e}")
            import traceback
            traceback.print_exc()

    def _clasificar_y_formatear_pedido(self, texto_pedido: str) -> tuple:
        """
        Usa Claude para clasificar si un mensaje es un pedido inmobiliario real
        y extraer el presupuesto. No reformatea el texto.

        Returns:
            tuple: (es_pedido: bool, presupuesto: int or None)
        """
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY', ''))

            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=100,
                messages=[{
                    "role": "user",
                    "content": f"""Analiza este mensaje de un grupo de WhatsApp inmobiliario.

Responde SOLO 2 lineas, nada mas:

Linea 1: SI o NO
- SI si es un pedido RELEVANTE para intermediacion inmobiliaria de VENTA de apartamentos, casas, penthouses o casas campestres
- NO si es:
  * No es un pedido (saludo, comentario, oferta de venta, spam, admin del grupo, confirmacion)
  * Es busqueda de BODEGA, LOCAL COMERCIAL, OFICINA, LOTE (no manejamos estos tipos)
  * Es busqueda de ARRIENDO (solo manejamos venta)
  * Es un pedido de plataforma Tu360 (dice "cliente tu360", "tu360 inmobiliario")
  * La comision no deja espacio para intermediario (dice "1.5% y 1.5%" o similar, sin espacio para el 0.5% del intermediario)
  * No menciona ningun criterio de busqueda (zona, precio, tipo, habitaciones)

Linea 2: Presupuesto maximo en NUMERO ENTERO (solo si es SI)
- "1.400 millones" = 1400000000
- "$800M" o "800 millones" = 800000000
- "presupuesto $1.200 a $1.300 millones" = 1300000000 (el maximo)
- Si no menciona precio = 0
- Porcentajes de comision (0.25%, 1.25%, puntas) NO son precios, ignorarlos

Mensaje:
{texto_pedido}"""
                }]
            )

            resultado = response.content[0].text.strip()
            lineas = resultado.split('\n')
            primera_linea = lineas[0].strip().upper()

            if primera_linea == 'SI':
                presupuesto = None
                if len(lineas) >= 2:
                    try:
                        presupuesto = int(lineas[1].strip().replace('.', '').replace(',', ''))
                        if presupuesto == 0:
                            presupuesto = None
                    except (ValueError, IndexError):
                        presupuesto = None
                return (True, presupuesto)
            else:
                return (False, None)

        except Exception as e:
            print(f"[WARN] No se pudo clasificar pedido con AI: {e}")
            # En caso de error, dejar pasar para no perder pedidos reales
            return (True, None)

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

        # URL shareable con nombre legible
        from src.scrapers.utils import PropertyNormalizer
        slug = prop.get('slug') or str(prop.get('id', ''))
        titulo = prop.get('titulo', '') or prop.get('title', '')
        title_slug = PropertyNormalizer.slugify_titulo(titulo)
        shareable_path = f"{slug}-{title_slug}" if title_slug else slug
        if slug:
            shareable_link = f"{self.frontend_url}/compartir/{shareable_path}"
            msg += f"\n🔗 *Ver detalles:*\n{shareable_link}\n"

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
            # BIFURCACIÓN POR TIPO DE GRUPO: oferta vs demanda
            # =====================================================================
            tipo_grupo = self._get_tipo_grupo(grupo_id)

            if tipo_grupo == 'demanda':
                # Grupo de demanda — capturar como pedido (no requiere URL)
                return self._handle_demanda_message(message_data, message_body, message_type, grupo_id)

            # =====================================================================
            # PROCESAMIENTO OFERTA: Solo grupos de oferta llegan aquí (flujo original)
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
