#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Procesador de Propiedades - Proyecto Cupido
Genera embeddings y analiza imágenes automáticamente al guardar propiedades
"""

import os
import json
import threading
from typing import Dict, Any, Optional, List
from src.db.database import DatabaseManager

# Importar módulos de vectorización (opcionales)
try:
    from src.core.embeddings import get_embeddings_manager
    EMBEDDINGS_AVAILABLE = True
except ImportError:
    EMBEDDINGS_AVAILABLE = False

try:
    from src.core.image_analyzer import get_image_analyzer
    IMAGE_ANALYZER_AVAILABLE = True
except ImportError:
    IMAGE_ANALYZER_AVAILABLE = False


class PropertyProcessor:
    """
    Procesa propiedades para búsqueda vectorial
    Se ejecuta automáticamente después de guardar una propiedad
    """

    def __init__(self, analyze_images: bool = True, async_processing: bool = True):
        """
        Args:
            analyze_images: Si analizar imágenes con Claude Vision
            async_processing: Si procesar en background (no bloquear)
        """
        self.analyze_images = analyze_images and IMAGE_ANALYZER_AVAILABLE
        self.async_processing = async_processing
        self.max_images = 5

        if EMBEDDINGS_AVAILABLE:
            self.embeddings = get_embeddings_manager()
        else:
            self.embeddings = None
            print("ℹ️  Embeddings no disponibles")

        if self.analyze_images:
            self.image_analyzer = get_image_analyzer()
        else:
            self.image_analyzer = None

    def process_property(self, property_id: int, property_data: Optional[Dict] = None) -> bool:
        """
        Procesa una propiedad: genera embedding y analiza imágenes

        Args:
            property_id: ID de la propiedad en la base de datos
            property_data: Datos de la propiedad (opcional, se obtienen de DB si no se proveen)

        Returns:
            True si se procesó correctamente
        """
        if not EMBEDDINGS_AVAILABLE:
            print("⚠️  Sistema de embeddings no disponible")
            return False

        if self.async_processing:
            # Procesar en background
            thread = threading.Thread(
                target=self._process_property_sync,
                args=(property_id, property_data)
            )
            thread.daemon = True
            thread.start()
            print(f"🔄 Procesamiento vectorial iniciado en background para propiedad {property_id}")
            return True
        else:
            return self._process_property_sync(property_id, property_data)

    def _process_property_sync(self, property_id: int, property_data: Optional[Dict] = None) -> bool:
        """Procesamiento síncrono de propiedad"""
        try:
            with DatabaseManager() as db:
                # Obtener datos si no se proveyeron
                if not property_data:
                    property_data = self._get_property_data(db, property_id)

                if not property_data:
                    print(f"❌ No se encontró propiedad {property_id}")
                    return False

                print(f"🔮 Procesando vectores para: {property_data.get('titulo', 'Sin título')[:50]}...")

                # 1. Analizar imágenes (si está habilitado)
                visual_data = {}
                if self.analyze_images and self.image_analyzer:
                    visual_data = self._analyze_images(db, property_id, property_data)

                # 2. Construir texto para embedding
                combined_data = {**property_data, **visual_data}
                text_for_embedding = self.embeddings.build_property_text(combined_data)

                # 3. Generar embedding
                embedding = self.embeddings.generate_embedding(text_for_embedding)

                if not embedding:
                    print(f"❌ No se pudo generar embedding para propiedad {property_id}")
                    return False

                # 4. Guardar embedding
                embedding_str = '[' + ','.join(map(str, embedding)) + ']'

                db.cursor.execute("""
                    INSERT INTO property_embeddings (propiedad_id, embedding, texto_embedding)
                    VALUES (%s, %s::vector, %s)
                    ON CONFLICT (propiedad_id)
                    DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        texto_embedding = EXCLUDED.texto_embedding,
                        fecha_generacion = CURRENT_TIMESTAMP,
                        version = property_embeddings.version + 1
                """, (property_id, embedding_str, text_for_embedding[:5000]))

                db.conn.commit()
                print(f"✅ Embedding generado para propiedad {property_id}")
                return True

        except Exception as e:
            print(f"❌ Error procesando propiedad {property_id}: {e}")
            return False

    def _get_property_data(self, db: DatabaseManager, property_id: int) -> Optional[Dict]:
        """Obtiene datos de la propiedad de la base de datos"""
        db.cursor.execute("""
            SELECT
                id, titulo, tipo_propiedad, ciudad, zona, precio,
                habitaciones, banos, parqueaderos, area_construida,
                estrato, amenidades_internas, amenidades_externas,
                descripcion, caracteristicas_adicionales,
                imagen_principal, imagenes_urls
            FROM propiedades
            WHERE id = %s AND activa = TRUE
        """, (property_id,))

        result = db.cursor.fetchone()
        return dict(result) if result else None

    def _analyze_images(self, db: DatabaseManager, property_id: int, property_data: Dict) -> Dict:
        """Analiza imágenes de la propiedad"""
        # Recopilar URLs
        image_urls = []

        if property_data.get('imagen_principal'):
            image_urls.append(property_data['imagen_principal'])

        if property_data.get('imagenes_urls'):
            urls_str = property_data['imagenes_urls']
            if isinstance(urls_str, str):
                extra_urls = [u.strip() for u in urls_str.split('|') if u.strip()]
                image_urls.extend(extra_urls)

        # Eliminar duplicados
        image_urls = list(dict.fromkeys(image_urls))

        if not image_urls:
            return {}

        print(f"   📸 Analizando {min(len(image_urls), self.max_images)} imágenes...")

        # Contexto
        context = {
            'tipo_propiedad': property_data.get('tipo_propiedad'),
            'ciudad': property_data.get('ciudad'),
            'zona': property_data.get('zona'),
            'precio': property_data.get('precio')
        }

        # Analizar
        analysis = self.image_analyzer.analyze_property_images(
            image_urls,
            context,
            max_images=self.max_images
        )

        if not analysis.get('success'):
            return {}

        # Guardar análisis individual
        for img_analysis in analysis.get('analisis_individuales', []):
            try:
                db.cursor.execute("""
                    INSERT INTO property_image_analysis (
                        propiedad_id, imagen_url, descripcion_visual,
                        estilo_detectado, ambiente, calidad_imagen,
                        caracteristicas_visibles, puntos_destacados,
                        tipo_espacio, es_imagen_principal
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (propiedad_id, imagen_url) DO UPDATE SET
                        descripcion_visual = EXCLUDED.descripcion_visual,
                        estilo_detectado = EXCLUDED.estilo_detectado,
                        ambiente = EXCLUDED.ambiente,
                        calidad_imagen = EXCLUDED.calidad_imagen,
                        caracteristicas_visibles = EXCLUDED.caracteristicas_visibles,
                        puntos_destacados = EXCLUDED.puntos_destacados,
                        tipo_espacio = EXCLUDED.tipo_espacio,
                        fecha_analisis = CURRENT_TIMESTAMP
                """, (
                    property_id,
                    img_analysis.get('imagen_url'),
                    img_analysis.get('descripcion_breve'),
                    img_analysis.get('estilo_detectado'),
                    img_analysis.get('ambiente'),
                    img_analysis.get('calidad_imagen'),
                    json.dumps(img_analysis.get('caracteristicas_visibles', [])),
                    json.dumps(img_analysis.get('puntos_destacados', [])),
                    img_analysis.get('tipo_espacio'),
                    img_analysis.get('es_imagen_principal', False)
                ))
            except Exception as e:
                print(f"   ⚠️  Error guardando análisis: {e}")

        # Guardar resumen
        try:
            db.cursor.execute("""
                INSERT INTO property_visual_summary (
                    propiedad_id, descripcion_general, estilo_predominante,
                    ambiente_general, calidad_promedio,
                    todas_caracteristicas, todos_puntos_destacados,
                    tags_visuales, total_imagenes_analizadas
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (propiedad_id) DO UPDATE SET
                    descripcion_general = EXCLUDED.descripcion_general,
                    estilo_predominante = EXCLUDED.estilo_predominante,
                    ambiente_general = EXCLUDED.ambiente_general,
                    calidad_promedio = EXCLUDED.calidad_promedio,
                    todas_caracteristicas = EXCLUDED.todas_caracteristicas,
                    todos_puntos_destacados = EXCLUDED.todos_puntos_destacados,
                    tags_visuales = EXCLUDED.tags_visuales,
                    total_imagenes_analizadas = EXCLUDED.total_imagenes_analizadas,
                    fecha_actualizacion = CURRENT_TIMESTAMP
            """, (
                property_id,
                analysis.get('descripcion_general'),
                analysis.get('estilo_predominante'),
                analysis.get('ambiente_general'),
                analysis.get('calidad_promedio'),
                json.dumps(analysis.get('todas_caracteristicas', [])),
                json.dumps(analysis.get('todos_puntos_destacados', [])),
                analysis.get('tags_visuales', []),
                analysis.get('total_imagenes_analizadas', 0)
            ))
            db.conn.commit()
        except Exception as e:
            print(f"   ⚠️  Error guardando resumen visual: {e}")

        return {
            'descripcion_visual': analysis.get('descripcion_general'),
            'estilo_predominante': analysis.get('estilo_predominante'),
            'ambiente_general': analysis.get('ambiente_general'),
            'tags_visuales': analysis.get('tags_visuales', [])
        }


# Singleton
_processor = None


def get_property_processor(analyze_images: bool = True) -> PropertyProcessor:
    """Obtiene instancia singleton del procesador"""
    global _processor
    if _processor is None:
        _processor = PropertyProcessor(analyze_images=analyze_images)
    return _processor


def process_new_property(property_id: int, property_data: Optional[Dict] = None) -> bool:
    """
    Función helper para procesar una nueva propiedad
    Llamar después de guardar en la base de datos

    Args:
        property_id: ID de la propiedad guardada
        property_data: Datos de la propiedad (opcional)

    Returns:
        True si se inició el procesamiento
    """
    try:
        processor = get_property_processor()
        return processor.process_property(property_id, property_data)
    except Exception as e:
        print(f"⚠️  Error iniciando procesamiento vectorial: {e}")
        return False
