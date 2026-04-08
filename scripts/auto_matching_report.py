"""
Script de auto-matching: cruza pedidos pendientes/no_match con inventario de propiedades.
Usa criterios MAS flexibles que el auto-responder (threshold 30 vs 40, sin filtro de presupuesto minimo).
Genera reporte de oportunidades perdidas.
"""
import os
import sys
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# Agregar el directorio raiz al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db.database import DatabaseManager
from src.core.search_agent import PropertySearchAgent

# --- Configuracion ---
SCORE_THRESHOLD_FLEXIBLE = 30       # vs 40 del auto-responder
SCORE_THRESHOLD_ORIGINAL = 40       # threshold actual
DIAS_ATRAS = 7                      # ultimos 7 dias
TOP_N = 5                           # max propiedades por pedido
ESTADOS_OBJETIVO = ('pendiente', 'no_match')


def fetch_pedidos_recientes(db, dias=DIAS_ATRAS):
    """Consulta pedidos en estado pendiente/no_match de los ultimos N dias."""
    db.cursor.execute("""
        SELECT id, grupo_id, agente_telefono, agente_nombre, texto_pedido,
               presupuesto_estimado, estado, fecha_captura
        FROM pedidos
        WHERE estado IN ('pendiente', 'no_match')
          AND fecha_captura >= NOW() - INTERVAL '%s days'
        ORDER BY fecha_captura DESC
    """, (dias,))
    return db.cursor.fetchall()


def run_matching(pedidos):
    """Ejecuta busqueda flexible para cada pedido y retorna resultados."""
    agent = PropertySearchAgent()
    resultados = []

    for i, pedido in enumerate(pedidos, 1):
        pedido_id = pedido['id']
        texto = pedido['texto_pedido']
        presupuesto = pedido['presupuesto_estimado']
        estado = pedido['estado']

        print(f"\n{'─' * 70}")
        print(f"[{i}/{len(pedidos)}] Pedido #{pedido_id} | Estado: {estado} | Presupuesto: {f'${presupuesto:,.0f}' if presupuesto else 'N/A'}")
        print(f"   Texto: {texto[:120]}...")

        try:
            search_response = agent.search(texto, limit=20, sender='auto_matching_report')
            all_results = search_response.get('results', [])

            # Filtrar con threshold flexible (30)
            flexible_matches = [r for r in all_results if r.get('match_score', 0) >= SCORE_THRESHOLD_FLEXIBLE][:TOP_N]

            # Filtrar con threshold original (40) para comparacion
            strict_matches = [r for r in all_results if r.get('match_score', 0) >= SCORE_THRESHOLD_ORIGINAL][:TOP_N]

            # Determinar razon de no-match
            razon_no_match = None
            if not flexible_matches:
                if not all_results:
                    razon_no_match = "Sin resultados de busqueda (criterios no parseables o inventario vacio para zona/tipo)"
                else:
                    max_score = max(r.get('match_score', 0) for r in all_results)
                    razon_no_match = f"Mejor score: {max_score:.0f} (por debajo del threshold flexible de {SCORE_THRESHOLD_FLEXIBLE})"

            # Clasificar la oportunidad
            es_oportunidad_perdida = len(flexible_matches) > 0 and len(strict_matches) == 0

            resultados.append({
                'pedido_id': pedido_id,
                'texto_pedido': texto,
                'presupuesto': presupuesto,
                'estado_original': estado,
                'agente_nombre': pedido['agente_nombre'],
                'agente_telefono': pedido['agente_telefono'],
                'fecha_captura': pedido['fecha_captura'],
                'total_resultados_busqueda': len(all_results),
                'matches_flexibles': [{
                    'id': r.get('id'),
                    'codigo': r.get('codigo_propiedad', ''),
                    'tipo': r.get('tipo_propiedad', ''),
                    'ciudad': r.get('ciudad', ''),
                    'zona': r.get('zona', ''),
                    'precio': r.get('precio', 0),
                    'habitaciones': r.get('habitaciones', 0),
                    'area': r.get('area_construida', 0),
                    'match_score': r.get('match_score', 0),
                } for r in flexible_matches],
                'matches_estrictos': len(strict_matches),
                'es_oportunidad_perdida': es_oportunidad_perdida,
                'razon_no_match': razon_no_match,
            })

            status_icon = "🟢" if flexible_matches else "🔴"
            opp_icon = " ⚡ OPORTUNIDAD PERDIDA" if es_oportunidad_perdida else ""
            print(f"   {status_icon} Matches flexibles: {len(flexible_matches)} | Estrictos: {len(strict_matches)}{opp_icon}")

        except Exception as e:
            print(f"   ❌ Error en busqueda: {e}")
            resultados.append({
                'pedido_id': pedido_id,
                'texto_pedido': texto,
                'presupuesto': presupuesto,
                'estado_original': estado,
                'agente_nombre': pedido['agente_nombre'],
                'agente_telefono': pedido['agente_telefono'],
                'fecha_captura': pedido['fecha_captura'],
                'total_resultados_busqueda': 0,
                'matches_flexibles': [],
                'matches_estrictos': 0,
                'es_oportunidad_perdida': False,
                'razon_no_match': f"Error: {str(e)}",
            })

    return resultados


def print_report(resultados):
    """Imprime reporte formateado con analisis de oportunidades."""
    print("\n")
    print("=" * 80)
    print("  REPORTE DE AUTO-MATCHING — ANALISIS DE OPORTUNIDADES")
    print(f"  Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Threshold flexible: {SCORE_THRESHOLD_FLEXIBLE} | Threshold actual: {SCORE_THRESHOLD_ORIGINAL}")
    print("=" * 80)

    # --- Estadisticas generales ---
    total = len(resultados)
    con_match_flexible = sum(1 for r in resultados if r['matches_flexibles'])
    con_match_estricto = sum(1 for r in resultados if r['matches_estrictos'] > 0)
    oportunidades_perdidas = sum(1 for r in resultados if r['es_oportunidad_perdida'])
    sin_match = sum(1 for r in resultados if not r['matches_flexibles'])

    # Pedidos sin presupuesto que el auto-responder ignora
    sin_presupuesto = sum(1 for r in resultados if not r['presupuesto'])
    bajo_presupuesto_min = sum(1 for r in resultados if r['presupuesto'] and r['presupuesto'] < 450_000_000)

    print(f"\n📊 RESUMEN GENERAL ({total} pedidos analizados)")
    print(f"   {'─' * 50}")
    print(f"   Con match (score >= {SCORE_THRESHOLD_FLEXIBLE}):     {con_match_flexible:3d} ({con_match_flexible/total*100:.0f}%)" if total else "")
    print(f"   Con match (score >= {SCORE_THRESHOLD_ORIGINAL}):     {con_match_estricto:3d} ({con_match_estricto/total*100:.0f}%)" if total else "")
    print(f"   Sin match:                        {sin_match:3d} ({sin_match/total*100:.0f}%)" if total else "")
    print(f"   ⚡ Oportunidades perdidas:         {oportunidades_perdidas:3d}")
    print(f"      (matchean a score 30-39 pero NO a >= 40)")
    print(f"\n   Filtrados por auto-responder actual:")
    print(f"   Sin presupuesto detectado:         {sin_presupuesto:3d}")
    print(f"   Presupuesto < $450M:               {bajo_presupuesto_min:3d}")

    # Potencial total de auto-respuesta con filtros flexibles
    potencial_total = sum(1 for r in resultados if r['matches_flexibles'])
    print(f"\n   🎯 POTENCIAL: {potencial_total} pedidos PODRIAN haberse respondido")
    print(f"      automaticamente con filtros menos estrictos")
    if con_match_estricto > 0:
        mejora = ((potencial_total - con_match_estricto) / con_match_estricto) * 100
        print(f"      Mejora vs actual: +{mejora:.0f}% mas pedidos atendidos")

    # --- Detalle de oportunidades perdidas ---
    oportunidades = [r for r in resultados if r['es_oportunidad_perdida']]
    if oportunidades:
        print(f"\n\n{'=' * 80}")
        print(f"  ⚡ DETALLE DE OPORTUNIDADES PERDIDAS ({len(oportunidades)})")
        print(f"{'=' * 80}")

        for r in oportunidades:
            print(f"\n  Pedido #{r['pedido_id']} | {r['agente_nombre'] or 'N/A'} | {r['estado_original']}")
            print(f"  Presupuesto: {f'${r[\"presupuesto\"]:,.0f}' if r['presupuesto'] else 'N/A'}")
            print(f"  Texto: {r['texto_pedido'][:150]}")
            print(f"  Propiedades que matchean (score {SCORE_THRESHOLD_FLEXIBLE}-{SCORE_THRESHOLD_ORIGINAL - 1}):")
            for m in r['matches_flexibles']:
                print(f"    → ID {m['id']} | {m['tipo']} en {m['zona']}, {m['ciudad']} | ${m['precio']:,.0f} | {m['habitaciones']} hab | {m['area']}m² | Score: {m['match_score']:.0f}")

    # --- Detalle de pedidos sin match ---
    sin_matches = [r for r in resultados if not r['matches_flexibles']]
    if sin_matches:
        print(f"\n\n{'=' * 80}")
        print(f"  🔴 PEDIDOS SIN MATCH NI CON CRITERIOS FLEXIBLES ({len(sin_matches)})")
        print(f"{'=' * 80}")

        for r in sin_matches:
            print(f"\n  Pedido #{r['pedido_id']} | {r['agente_nombre'] or 'N/A'}")
            print(f"  Presupuesto: {f'${r[\"presupuesto\"]:,.0f}' if r['presupuesto'] else 'N/A'}")
            print(f"  Texto: {r['texto_pedido'][:150]}")
            print(f"  Razon: {r['razon_no_match']}")

    # --- Detalle completo de matches ---
    con_matches = [r for r in resultados if r['matches_flexibles']]
    if con_matches:
        print(f"\n\n{'=' * 80}")
        print(f"  🟢 PEDIDOS CON MATCHES FLEXIBLES ({len(con_matches)})")
        print(f"{'=' * 80}")

        for r in con_matches:
            strict_tag = " ✅ ya seria auto-respondido" if r['matches_estrictos'] > 0 else " ⚡ NUEVO con filtros flexibles"
            print(f"\n  Pedido #{r['pedido_id']} | {r['agente_nombre'] or 'N/A'} | {r['estado_original']}{strict_tag}")
            print(f"  Presupuesto: {f'${r[\"presupuesto\"]:,.0f}' if r['presupuesto'] else 'N/A'}")
            print(f"  Texto: {r['texto_pedido'][:150]}")
            for m in r['matches_flexibles']:
                score_tag = "✅" if m['match_score'] >= SCORE_THRESHOLD_ORIGINAL else "🟡"
                print(f"    {score_tag} ID {m['id']} | {m['tipo']} en {m['zona']}, {m['ciudad']} | ${m['precio']:,.0f} | {m['habitaciones']} hab | {m['area']}m² | Score: {m['match_score']:.0f}")


def save_report_json(resultados, filepath=None):
    """Guarda el reporte completo en JSON para analisis posterior."""
    if not filepath:
        filepath = f"scripts/matching_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json"

    report_data = {
        'generated_at': datetime.now().isoformat(),
        'config': {
            'score_threshold_flexible': SCORE_THRESHOLD_FLEXIBLE,
            'score_threshold_original': SCORE_THRESHOLD_ORIGINAL,
            'dias_atras': DIAS_ATRAS,
            'top_n': TOP_N,
        },
        'summary': {
            'total_pedidos': len(resultados),
            'con_match_flexible': sum(1 for r in resultados if r['matches_flexibles']),
            'con_match_estricto': sum(1 for r in resultados if r['matches_estrictos'] > 0),
            'oportunidades_perdidas': sum(1 for r in resultados if r['es_oportunidad_perdida']),
            'sin_match': sum(1 for r in resultados if not r['matches_flexibles']),
        },
        'pedidos': [{
            **{k: v for k, v in r.items() if k != 'fecha_captura'},
            'fecha_captura': r['fecha_captura'].isoformat() if r.get('fecha_captura') else None,
        } for r in resultados],
    }

    full_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), filepath)
    with open(full_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)

    print(f"\n💾 Reporte JSON guardado en: {filepath}")
    return filepath


def main():
    print("🔍 SCRIPT DE AUTO-MATCHING: Pedidos → Propiedades")
    print(f"   Consultando pedidos en estado {ESTADOS_OBJETIVO} de los ultimos {DIAS_ATRAS} dias")
    print(f"   Threshold flexible: {SCORE_THRESHOLD_FLEXIBLE} (vs {SCORE_THRESHOLD_ORIGINAL} actual)")

    # 1. Obtener pedidos
    with DatabaseManager() as db:
        pedidos = fetch_pedidos_recientes(db)

    if not pedidos:
        print("\n✅ No hay pedidos pendientes/no_match en los ultimos 7 dias.")
        return

    print(f"\n📋 Encontrados {len(pedidos)} pedidos para analizar")

    # 2. Ejecutar matching flexible
    resultados = run_matching(pedidos)

    # 3. Imprimir reporte
    print_report(resultados)

    # 4. Guardar JSON
    save_report_json(resultados)

    print("\n✅ Analisis completado.")


if __name__ == '__main__':
    main()
