#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Procesamiento de Propiedades para Búsqueda Vectorial
Genera embeddings y analiza imágenes de todas las propiedades

Uso:
    python scripts/process_properties_vectors.py --all          # Procesar todas
    python scripts/process_properties_vectors.py --new          # Solo nuevas (sin embedding)
    python scripts/process_properties_vectors.py --id 123       # Procesar una específica
    python scripts/process_properties_vectors.py --migrate      # Solo migración DB
    python scripts/process_properties_vectors.py --stats        # Ver estadísticas
"""

import os
import sys
import io

# Configurar UTF-8 para Windows
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import argparse
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

# Agregar path del proyecto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from src.db.database import DatabaseManager
from src.core.embeddings import get_embeddings_manager
from src.core.image_analyzer import get_image_analyzer


class PropertyVectorProcessor:
    """Procesa propiedades para búsqueda vectorial"""

    def __init__(self, analyze_images: bool = True, max_images_per_property: int = 5):
        self.embeddings = get_embeddings_manager()
        self.image_analyzer = get_image_analyzer() if analyze_images else None
        self.analyze_images = analyze_images
        self.max_images = max_images_per_property
        self.stats = {
            'processed': 0,
            'embeddings_created': 0,
            'images_analyzed': 0,
            'errors': 0,
            'skipped': 0
        }

    def run_migration(self) -> bool:
        """Ejecuta la migración de pgvector"""
        print("\n" + "=" * 60)
        print("🔧 EJECUTANDO MIGRACIÓN DE PGVECTOR")
        print("=" * 60 + "\n")

        try:
            with DatabaseManager() as db:
                # 1. Habilitar extensión pgvector
                print("   Habilitando pgvector...")
                try:
                    db.cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    db.conn.commit()
                    print("   ✅ Extensión vector habilitada")
                except Exception as e:
                    print(f"   ⚠️  {e}")
                    db.conn.rollback()

                # 2. Crear tabla de embeddings
                print("   Creando tabla property_embeddings...")
                try:
                    db.cursor.execute("""
                        CREATE TABLE IF NOT EXISTS property_embeddings (
                            id SERIAL PRIMARY KEY,
                            propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
                            embedding vector(1536),
                            texto_embedding TEXT,
                            modelo_embedding VARCHAR(50) DEFAULT 'text-embedding-3-small',
                            fecha_generacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            version INTEGER DEFAULT 1,
                            UNIQUE(propiedad_id)
                        )
                    """)
                    db.conn.commit()
                    print("   ✅ Tabla property_embeddings creada")
                except Exception as e:
                    if 'already exists' in str(e).lower():
                        print("   ℹ️  Tabla property_embeddings ya existe")
                    else:
                        print(f"   ⚠️  {e}")
                    db.conn.rollback()

                # 3. Crear tabla de análisis de imágenes
                print("   Creando tabla property_image_analysis...")
                try:
                    db.cursor.execute("""
                        CREATE TABLE IF NOT EXISTS property_image_analysis (
                            id SERIAL PRIMARY KEY,
                            propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
                            imagen_url TEXT NOT NULL,
                            descripcion_visual TEXT,
                            estilo_detectado VARCHAR(100),
                            ambiente VARCHAR(100),
                            calidad_imagen DECIMAL(3,1),
                            caracteristicas_visibles JSONB,
                            puntos_destacados JSONB,
                            tipo_espacio VARCHAR(50),
                            es_imagen_principal BOOLEAN DEFAULT FALSE,
                            fecha_analisis TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            modelo_analisis VARCHAR(50) DEFAULT 'claude-sonnet-4',
                            UNIQUE(propiedad_id, imagen_url)
                        )
                    """)
                    db.conn.commit()
                    print("   ✅ Tabla property_image_analysis creada")
                except Exception as e:
                    if 'already exists' in str(e).lower():
                        print("   ℹ️  Tabla property_image_analysis ya existe")
                    else:
                        print(f"   ⚠️  {e}")
                    db.conn.rollback()

                # 4. Crear tabla de resumen visual
                print("   Creando tabla property_visual_summary...")
                try:
                    db.cursor.execute("""
                        CREATE TABLE IF NOT EXISTS property_visual_summary (
                            id SERIAL PRIMARY KEY,
                            propiedad_id INTEGER NOT NULL REFERENCES propiedades(id) ON DELETE CASCADE,
                            descripcion_general TEXT,
                            estilo_predominante VARCHAR(100),
                            ambiente_general VARCHAR(100),
                            calidad_promedio DECIMAL(3,1),
                            todas_caracteristicas JSONB,
                            todos_puntos_destacados JSONB,
                            tags_visuales TEXT[],
                            embedding_visual vector(1536),
                            total_imagenes_analizadas INTEGER DEFAULT 0,
                            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            UNIQUE(propiedad_id)
                        )
                    """)
                    db.conn.commit()
                    print("   ✅ Tabla property_visual_summary creada")
                except Exception as e:
                    if 'already exists' in str(e).lower():
                        print("   ℹ️  Tabla property_visual_summary ya existe")
                    else:
                        print(f"   ⚠️  {e}")
                    db.conn.rollback()

                # 5. Crear índice vectorial
                print("   Creando índice vectorial...")
                try:
                    db.cursor.execute("""
                        CREATE INDEX IF NOT EXISTS idx_property_embeddings_vector
                        ON property_embeddings
                        USING ivfflat (embedding vector_cosine_ops)
                        WITH (lists = 100)
                    """)
                    db.conn.commit()
                    print("   ✅ Índice vectorial creado")
                except Exception as e:
                    if 'already exists' in str(e).lower():
                        print("   ℹ️  Índice ya existe")
                    else:
                        print(f"   ⚠️  {e}")
                    db.conn.rollback()

            print("\n✅ Migración completada")
            return True

        except Exception as e:
            print(f"❌ Error en migración: {e}")
            import traceback
            traceback.print_exc()
            return False

    def process_all_properties(self, force: bool = False) -> Dict[str, int]:
        """
        Procesa todas las propiedades activas

        Args:
            force: Si True, reprocesa aunque ya tengan embedding

        Returns:
            Estadísticas de procesamiento
        """
        print("\n" + "=" * 60)
        print("📊 PROCESANDO TODAS LAS PROPIEDADES")
        print("=" * 60 + "\n")

        with DatabaseManager() as db:
            if force:
                query = """
                    SELECT id, titulo, tipo_propiedad, ciudad, zona, precio,
                           habitaciones, banos, parqueaderos, area_construida,
                           estrato, amenidades_internas, amenidades_externas,
                           descripcion, caracteristicas_adicionales,
                           imagen_principal, imagenes_urls
                    FROM propiedades
                    WHERE activa = TRUE
                    ORDER BY id
                """
            else:
                query = """
                    SELECT p.id, p.titulo, p.tipo_propiedad, p.ciudad, p.zona, p.precio,
                           p.habitaciones, p.banos, p.parqueaderos, p.area_construida,
                           p.estrato, p.amenidades_internas, p.amenidades_externas,
                           p.descripcion, p.caracteristicas_adicionales,
                           p.imagen_principal, p.imagenes_urls
                    FROM propiedades p
                    LEFT JOIN property_embeddings pe ON pe.propiedad_id = p.id
                    WHERE p.activa = TRUE
                    AND pe.id IS NULL
                    ORDER BY p.id
                """

            db.cursor.execute(query)
            properties = db.cursor.fetchall()

            print(f"📋 Propiedades a procesar: {len(properties)}")

            if not properties:
                print("✅ Todas las propiedades ya tienen embedding")
                return self.stats

            for i, prop in enumerate(properties):
                print(f"\n[{i + 1}/{len(properties)}] Procesando ID {prop['id']}: {prop['titulo'][:50]}...")
                self._process_single_property(db, dict(prop))

        print("\n" + "=" * 60)
        print("📊 RESUMEN DE PROCESAMIENTO")
        print("=" * 60)
        print(f"   Procesadas: {self.stats['processed']}")
        print(f"   Embeddings creados: {self.stats['embeddings_created']}")
        print(f"   Imágenes analizadas: {self.stats['images_analyzed']}")
        print(f"   Errores: {self.stats['errors']}")
        print(f"   Omitidas: {self.stats['skipped']}")

        return self.stats

    def process_new_properties(self) -> Dict[str, int]:
        """Procesa solo propiedades sin embedding"""
        return self.process_all_properties(force=False)

    def process_single_property(self, property_id: int) -> bool:
        """Procesa una propiedad específica"""
        print(f"\n🔍 Procesando propiedad ID: {property_id}")

        with DatabaseManager() as db:
            db.cursor.execute("""
                SELECT id, titulo, tipo_propiedad, ciudad, zona, precio,
                       habitaciones, banos, parqueaderos, area_construida,
                       estrato, amenidades_internas, amenidades_externas,
                       descripcion, caracteristicas_adicionales,
                       imagen_principal, imagenes_urls
                FROM propiedades
                WHERE id = %s AND activa = TRUE
            """, (property_id,))

            prop = db.cursor.fetchone()
            if not prop:
                print(f"❌ Propiedad {property_id} no encontrada o inactiva")
                return False

            return self._process_single_property(db, dict(prop))

    def _process_single_property(self, db: DatabaseManager, prop: Dict) -> bool:
        """
        Procesa una propiedad individual

        Args:
            db: Conexión a la base de datos
            prop: Diccionario con datos de la propiedad

        Returns:
            True si se procesó correctamente
        """
        property_id = prop['id']
        self.stats['processed'] += 1

        try:
            # 1. Analizar imágenes (si está habilitado)
            visual_data = {}
            if self.analyze_images and self.image_analyzer:
                visual_data = self._analyze_property_images(db, prop)
                if visual_data.get('success'):
                    print(f"   ✅ Análisis visual completado")

            # 2. Construir texto para embedding
            # Combinar datos de propiedad con análisis visual
            combined_data = {**prop, **visual_data}
            text_for_embedding = self.embeddings.build_property_text(combined_data)

            # 3. Generar embedding
            print(f"   🔮 Generando embedding...")
            embedding = self.embeddings.generate_embedding(text_for_embedding)

            if not embedding:
                print(f"   ❌ No se pudo generar embedding")
                self.stats['errors'] += 1
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
            self.stats['embeddings_created'] += 1
            print(f"   ✅ Embedding guardado")

            return True

        except Exception as e:
            print(f"   ❌ Error procesando: {e}")
            self.stats['errors'] += 1
            db.conn.rollback()
            return False

    def _analyze_property_images(self, db: DatabaseManager, prop: Dict) -> Dict:
        """
        Analiza las imágenes de una propiedad

        Args:
            db: Conexión a la base de datos
            prop: Datos de la propiedad

        Returns:
            Resumen del análisis visual
        """
        property_id = prop['id']

        # Recopilar URLs de imágenes
        image_urls = []

        if prop.get('imagen_principal'):
            image_urls.append(prop['imagen_principal'])

        if prop.get('imagenes_urls'):
            urls_str = prop['imagenes_urls']
            if isinstance(urls_str, str):
                extra_urls = [u.strip() for u in urls_str.split('|') if u.strip()]
                image_urls.extend(extra_urls)

        # Eliminar duplicados manteniendo orden
        seen = set()
        unique_urls = []
        for url in image_urls:
            if url not in seen:
                seen.add(url)
                unique_urls.append(url)

        if not unique_urls:
            print(f"   ℹ️  Sin imágenes para analizar")
            return {}

        print(f"   📸 Analizando {min(len(unique_urls), self.max_images)} imágenes...")

        # Contexto de la propiedad
        context = {
            'tipo_propiedad': prop.get('tipo_propiedad'),
            'ciudad': prop.get('ciudad'),
            'zona': prop.get('zona'),
            'precio': prop.get('precio')
        }

        # Analizar imágenes
        analysis = self.image_analyzer.analyze_property_images(
            unique_urls,
            context,
            max_images=self.max_images
        )

        if not analysis.get('success'):
            return {}

        # Guardar análisis individual de cada imagen
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

                self.stats['images_analyzed'] += 1

            except Exception as e:
                print(f"   ⚠️  Error guardando análisis de imagen: {e}")

        # Guardar resumen visual
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
            db.conn.rollback()

        return {
            'descripcion_visual': analysis.get('descripcion_general'),
            'estilo_predominante': analysis.get('estilo_predominante'),
            'ambiente_general': analysis.get('ambiente_general'),
            'tags_visuales': analysis.get('tags_visuales', [])
        }

    def get_stats(self) -> Dict[str, Any]:
        """Obtiene estadísticas del sistema vectorial"""
        print("\n" + "=" * 60)
        print("📊 ESTADÍSTICAS DEL SISTEMA VECTORIAL")
        print("=" * 60 + "\n")

        try:
            with DatabaseManager() as db:
                # Estadísticas generales
                db.cursor.execute("""
                    SELECT
                        (SELECT COUNT(*) FROM propiedades WHERE activa = TRUE) as total_propiedades,
                        (SELECT COUNT(*) FROM property_embeddings) as con_embedding,
                        (SELECT COUNT(*) FROM property_visual_summary) as con_vision,
                        (SELECT COUNT(*) FROM property_image_analysis) as imagenes_analizadas
                """)

                stats = db.cursor.fetchone()

                total = stats['total_propiedades']
                con_embedding = stats['con_embedding']
                con_vision = stats['con_vision']
                imagenes = stats['imagenes_analizadas']

                cobertura = round(con_embedding / max(total, 1) * 100, 1)
                cobertura_vision = round(con_vision / max(total, 1) * 100, 1)

                print(f"📋 Total propiedades activas: {total}")
                print(f"🔮 Con embedding: {con_embedding} ({cobertura}%)")
                print(f"📸 Con análisis visual: {con_vision} ({cobertura_vision}%)")
                print(f"🖼️  Imágenes analizadas: {imagenes}")

                # Propiedades sin embedding
                db.cursor.execute("""
                    SELECT p.id, p.titulo
                    FROM propiedades p
                    LEFT JOIN property_embeddings pe ON pe.propiedad_id = p.id
                    WHERE p.activa = TRUE AND pe.id IS NULL
                    LIMIT 10
                """)

                sin_embedding = db.cursor.fetchall()
                if sin_embedding:
                    print(f"\n⚠️  Propiedades sin embedding (primeras 10):")
                    for prop in sin_embedding:
                        print(f"   - ID {prop['id']}: {prop['titulo'][:50]}")

                return {
                    'total_propiedades': total,
                    'con_embedding': con_embedding,
                    'con_vision': con_vision,
                    'imagenes_analizadas': imagenes,
                    'cobertura_embeddings': cobertura,
                    'cobertura_vision': cobertura_vision
                }

        except Exception as e:
            print(f"❌ Error obteniendo estadísticas: {e}")
            return {}


def main():
    parser = argparse.ArgumentParser(
        description='Procesa propiedades para búsqueda vectorial'
    )
    parser.add_argument('--all', action='store_true',
                        help='Procesar todas las propiedades')
    parser.add_argument('--new', action='store_true',
                        help='Procesar solo propiedades sin embedding')
    parser.add_argument('--id', type=int,
                        help='Procesar propiedad específica por ID')
    parser.add_argument('--migrate', action='store_true',
                        help='Solo ejecutar migración de base de datos')
    parser.add_argument('--stats', action='store_true',
                        help='Mostrar estadísticas')
    parser.add_argument('--no-images', action='store_true',
                        help='No analizar imágenes (solo embeddings)')
    parser.add_argument('--force', action='store_true',
                        help='Forzar reprocesamiento aunque ya exista embedding')
    parser.add_argument('--max-images', type=int, default=5,
                        help='Máximo de imágenes a analizar por propiedad')

    args = parser.parse_args()

    processor = PropertyVectorProcessor(
        analyze_images=not args.no_images,
        max_images_per_property=args.max_images
    )

    # Siempre ejecutar migración primero si es necesario
    if args.migrate or args.all or args.new or args.id:
        processor.run_migration()

    if args.migrate:
        return

    if args.stats:
        processor.get_stats()
        return

    if args.id:
        processor.process_single_property(args.id)
        return

    if args.all:
        processor.process_all_properties(force=args.force)
        return

    if args.new:
        processor.process_new_properties()
        return

    # Si no se especifica nada, mostrar ayuda
    parser.print_help()


if __name__ == '__main__':
    main()
