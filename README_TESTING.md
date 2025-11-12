# 🧪 Sistema de Testing del Agente de Búsqueda

Script completo para probar el agente de búsqueda con múltiples consultas y generar logs detallados para análisis y mejora.

---

## 🎯 ¿Qué hace?

El script `test_busqueda_completo.py`:

1. ✅ **Ejecuta 10 pruebas** con consultas variadas y reales
2. ✅ **Retorna exactamente 5 propiedades** por búsqueda, ordenadas por match score
3. ✅ **Genera logs detallados** en JSON para cada test
4. ✅ **Crea un resumen consolidado** con estadísticas
5. ✅ **Genera un reporte de texto** fácil de leer y analizar

---

## 🚀 Cómo Ejecutar

### Paso 1: Asegúrate de tener propiedades en la DB

```powershell
# Si no tienes propiedades, carga algunas
python cargar_pulppo_auto.py
```

### Paso 2: Ejecuta el script de testing

```powershell
python test_busqueda_completo.py
```

**Duración estimada**: ~30-40 segundos (10 tests con pausa de 2 seg entre cada uno)

---

## 📊 Tests Incluidos

El script incluye **10 casos de prueba** que cubren diferentes escenarios:

| ID | Nombre | Características |
|----|--------|-----------------|
| TEST-001 | Apartamento Laureles - Presupuesto Alto | Persona mayor, primer piso, 1000M |
| TEST-002 | Apartamento El Poblado - Requisitos Específicos | Baño en cada habitación, balcón, piscina, 800M |
| TEST-003 | Apartamento Envigado - Presupuesto Medio | 3 habitaciones, 500M |
| TEST-004 | Casa Familiar - Presupuesto Alto | 4-5 habitaciones, jardín, 1.5B |
| TEST-005 | Apartamento Pequeño - Presupuesto Bajo | 1-2 habitaciones, 300M |
| TEST-006 | Penthouse Lujo - Sin límite | 3+ habitaciones, vista, 2B |
| TEST-007 | Apartamento Nuevo - Zona Norte | Castilla/Robledo, 600M |
| TEST-008 | Duplex - Sabaneta/Envigado | 2-3 habitaciones, 700M |
| TEST-009 | Apartamento Estudiante | 1 habitación, 250M |
| TEST-010 | Apartamento Inversión | Para arrendar, 300-500M |

---

## 📁 Archivos Generados

Después de ejecutar, se crea un directorio `test_logs_YYYYMMDD_HHMMSS/` con:

### 1. Logs Individuales (JSON)
```
test_logs_20251031_153045/
├── TEST-001_Apartamento_Laureles_Presupuesto_Alto.json
├── TEST-002_Apartamento_El_Poblado_Requisitos_Específicos.json
├── TEST-003_Apartamento_Envigado_Presupuesto_Medio.json
├── ... (10 archivos JSON)
```

**Contenido de cada log:**
```json
{
  "test_id": "TEST-001",
  "test_nombre": "Apartamento Laureles - Presupuesto Alto",
  "query_original": "Busco apto cliente...",
  "success": true,
  "criteria": {
    "ubicaciones": ["Laureles", "Ciudad del Río"],
    "tipo_propiedad": "Apartamento",
    "precio_max": 1000000000,
    "habitaciones_min": 2,
    "habitaciones_max": 3,
    "piso": 1,
    "amenidades_requeridas": ["portería"]
  },
  "total_found": 5,
  "results": [
    {
      "id": 1,
      "titulo": "Apartamento en Laureles...",
      "precio": 520000000,
      "match_score": 47,
      "match_reasons": [
        "Ubicación: Laureles",
        "Precio dentro del presupuesto",
        "Tipo: Apartamento",
        "Piso 1"
      ],
      "zona": "Laureles",
      "habitaciones": 3,
      "banos": 2,
      ...
    },
    ... (5 resultados total)
  ],
  "timestamp": "2025-10-31T15:30:45.123456"
}
```

---

### 2. Resumen Consolidado (JSON)

`RESUMEN_CONSOLIDADO.json`:

```json
{
  "timestamp": "20251031_153045",
  "total_tests": 10,
  "tests": [
    {
      "test_id": "TEST-001",
      "nombre": "Apartamento Laureles - Presupuesto Alto",
      "success": true,
      "criterios_extraidos": 7,
      "resultados_encontrados": 5,
      "log_file": "test_logs_20251031_153045/TEST-001_..."
    },
    ...
  ]
}
```

---

### 3. Reporte de Análisis (TXT)

`REPORTE_ANALISIS.txt`:

```
================================================================================
  REPORTE DE ANÁLISIS - SISTEMA DE BÚSQUEDA INTELIGENTE
================================================================================

Fecha: 2025-10-31 15:30:45
Total de tests: 10
Tests exitosos: 10
Tests fallidos: 0

================================================================================
  DETALLE POR TEST
================================================================================

================================================================================
TEST 1: TEST-001 - Apartamento Laureles - Presupuesto Alto
================================================================================

CONSULTA ORIGINAL:
--------------------------------------------------------------------------------
Busco apto cliente tu 360 en ciudad del Río o Laureles
Persona mayor primer piso. 2 o 3 habitaciones.
Con portería.
Presupuesto 1000 millones.
...
--------------------------------------------------------------------------------

CRITERIOS EXTRAÍDOS:
--------------------------------------------------------------------------------
  • ubicaciones: ['Laureles', 'Ciudad del Río']
  • tipo_propiedad: Apartamento
  • precio_max: 1000000000
  • habitaciones_min: 2
  • habitaciones_max: 3
  • piso: 1
  • amenidades_requeridas: ['portería']

PROPIEDADES ENCONTRADAS: 5
--------------------------------------------------------------------------------

  Resultado #1 - Score: 47 pts
  Apartamento en Laureles, Laureles - 95m²
  Precio: $520,000,000 COP
  Zona: Laureles
  Razones: Ubicación: Laureles, Precio dentro del presupuesto, Tipo: Apartamento, Piso 1

  Resultado #2 - Score: 35 pts
  ...
```

---

## 📈 Salida en Consola

Durante la ejecución verás:

```
================================================================================
  TEST COMPLETO DEL SISTEMA DE BÚSQUEDA INTELIGENTE
================================================================================

🤖 Inicializando agente de búsqueda...
✅ Usando modelo: claude-3-opus-20240229
✅ Agente creado exitosamente

📁 Logs se guardarán en: test_logs_20251031_153045/

================================================================================
  TEST 1/10: TEST-001 - Apartamento Laureles - Presupuesto Alto
================================================================================

📝 Consulta:
Busco apto cliente tu 360 en ciudad del Río o Laureles...

================================================================================
  BÚSQUEDA INTELIGENTE DE PROPIEDADES
================================================================================

🧠 Analizando criterios con Claude...
✅ Criterios extraídos:
{
  "ubicaciones": ["Laureles", "Ciudad del Río"],
  "tipo_propiedad": "Apartamento",
  ...
}

🔍 Buscando en base de datos...
📊 Propiedades encontradas: 12

⭐ Rankeando resultados...

✅ Búsqueda exitosa
📊 Criterios extraídos: 7 campos
🏠 Propiedades encontradas: 5

⭐ Ranking de resultados:
   #1: 47 pts - Apartamento en Laureles, Laureles - 95m² - $520,000,000 COP
   #2: 35 pts - Apartamento en Laureles, Laureles - 118m² - $403,000,000 COP
   #3: 28 pts - Apartamento en El Poblado, El Poblado - 142m² - $672,000,000 COP
   #4: 23 pts - Casa en Laureles, Laureles - 254m² - $982,000,000 COP
   #5: 18 pts - Duplex en Estadio, Estadio - 134m² - $458,000,000 COP

💾 Log guardado: test_logs_20251031_153045/TEST-001_...json

⏳ Esperando 2 segundos antes del siguiente test...

================================================================================
  TEST 2/10: TEST-002 - ...
...

================================================================================
  RESUMEN FINAL
================================================================================

📊 Tests ejecutados: 10
✅ Exitosos: 10
❌ Fallidos: 0

📈 Estadísticas:
   • Criterios extraídos (promedio): 6.2
   • Resultados encontrados (promedio): 4.8

📁 Todos los logs guardados en: test_logs_20251031_153045/
📄 Resumen consolidado: test_logs_20251031_153045/RESUMEN_CONSOLIDADO.json

📝 Generando reporte de texto...
✅ Reporte generado: test_logs_20251031_153045/REPORTE_ANALISIS.txt

================================================================================
  TESTING COMPLETADO
================================================================================

📂 Archivos generados:
   • 10 logs individuales (JSON)
   • 1 resumen consolidado (JSON)
   • 1 reporte de análisis (TXT)

🔍 Revisa los logs en: test_logs_20251031_153045/

💡 Siguiente paso:
   1. Revisa REPORTE_ANALISIS.txt para análisis rápido
   2. Revisa logs individuales JSON para detalles técnicos
   3. Comparte los archivos para mejorar el agente
```

---

## 🔍 Análisis de Logs

### Para análisis rápido:
```powershell
# Abrir el reporte de texto
notepad test_logs_XXXXXXXXX_XXXXXX/REPORTE_ANALISIS.txt
```

### Para análisis detallado:
```powershell
# Ver un log individual específico
cat test_logs_XXXXXXXXX_XXXXXX/TEST-001_*.json | python -m json.tool
```

### Para estadísticas:
```powershell
# Ver el resumen consolidado
cat test_logs_XXXXXXXXX_XXXXXX/RESUMEN_CONSOLIDADO.json | python -m json.tool
```

---

## 📊 Métricas Importantes

El sistema evalúa cada búsqueda con:

### 1. **Criterios Extraídos**
Número de criterios que Claude pudo identificar del mensaje:
- `ubicaciones`
- `tipo_propiedad`
- `precio_max`
- `habitaciones_min`
- `amenidades_requeridas`
- etc.

**Ideal**: 6-8 criterios por consulta

---

### 2. **Resultados Encontrados**
Número de propiedades que coinciden (siempre retorna máximo 5)

**Ideal**: 5 resultados

---

### 3. **Match Score**
Puntuación de relevancia de cada resultado (0-100 pts):

| Score | Calidad |
|-------|---------|
| 40-60 | Excelente match |
| 25-39 | Buen match |
| 15-24 | Match aceptable |
| 5-14 | Match bajo |
| 0-4 | Match muy bajo |

**Cálculo del score**:
- Ubicación exacta: +10 pts
- Tipo correcto: +5 pts
- Precio 10% bajo máximo: +8 pts
- Precio dentro presupuesto: +5 pts
- Habitaciones exactas: +7 pts
- Cada amenidad: +6 pts
- Piso preferido: +8 pts
- Muchas amenidades (15+): +4 pts

---

### 4. **Match Reasons**
Razones por las que cada propiedad coincide:
- "Ubicación: Laureles"
- "Precio dentro del presupuesto"
- "3 habitaciones (exacto)"
- "Tiene: gimnasio"
- etc.

---

## 🎯 Cómo Usar los Logs para Mejorar

### 1. Identificar patrones de extracción incorrecta

Busca en los logs casos donde:
- Claude no extrae una ubicación mencionada
- El precio se interpreta mal ("800 millones" → 800000000)
- Amenidades importantes no se detectan

**Ejemplo**:
```json
{
  "query_original": "Busco en Laureles hasta 800 millones",
  "criteria": {
    "ubicaciones": [],  // ❌ No detectó Laureles
    "precio_max": 800   // ❌ Debería ser 800000000
  }
}
```

---

### 2. Analizar scoring inadecuado

Busca propiedades con score muy bajo que deberían tener score alto:

**Ejemplo**:
```json
{
  "titulo": "Apartamento en Laureles - 95m²",
  "match_score": 5,  // ❌ Muy bajo para Laureles
  "match_reasons": []  // ❌ No detectó coincidencias
}
```

---

### 3. Revisar consultas sin resultados

Si un test retorna 0 propiedades, puede ser:
- Criterios demasiado restrictivos
- Base de datos sin propiedades en esa zona
- Problema en la consulta SQL

---

## 🔧 Personalización

### Agregar más tests

Edita `test_busqueda_completo.py` y agrega a `test_queries`:

```python
{
    "id": "TEST-011",
    "nombre": "Tu Caso Personalizado",
    "query": """Tu consulta aquí"""
}
```

---

### Cambiar número de resultados

Por defecto retorna 5 resultados. Para cambiar:

```python
# En test_busqueda_completo.py, línea del agent.search
resultado = agent.search(query, limit=10)  # Cambiar a 10
```

---

### Ajustar pausa entre tests

Para evitar saturar la API de Claude:

```python
# En test_busqueda_completo.py, línea de time.sleep
time.sleep(5)  # Aumentar a 5 segundos
```

---

## 💡 Siguiente Paso

Después de ejecutar los tests:

1. **Lee el reporte**: `REPORTE_ANALISIS.txt`
2. **Identifica problemas**: Busca scores bajos, criterios mal extraídos
3. **Comparte los logs**: Envía la carpeta `test_logs_*/` completa para análisis
4. **Itera**: Mejora el prompt de Claude, ajusta el scoring, etc.

---

## 🚨 Troubleshooting

### Error: "No se encontraron propiedades"

→ Carga propiedades en la DB:
```powershell
python cargar_pulppo_auto.py
```

### Error: "ANTHROPIC_API_KEY no configurada"

→ Verifica tu archivo `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-api03-xxxxx
```

### Tests muy lentos

→ Reduce el número de tests o aumenta la pausa entre ellos

---

## ✅ Checklist antes de ejecutar

- [ ] Tienes propiedades en la base de datos
- [ ] ANTHROPIC_API_KEY está configurada en .env
- [ ] El módulo anthropic está instalado
- [ ] Tienes créditos en tu cuenta de Anthropic

---

**¡Listo para probar!** 🧪✨

Ejecuta: `python test_busqueda_completo.py` y analiza los resultados.
