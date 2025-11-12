# 🤖 Sistema de Búsqueda Inteligente de Propiedades

Sistema de búsqueda de propiedades usando **Claude (Anthropic)** para procesar consultas en lenguaje natural de agentes inmobiliarios.

---

## 🎯 ¿Qué hace?

Permite a los agentes inmobiliarios buscar propiedades escribiendo mensajes en lenguaje natural (como los que envían por WhatsApp), y el sistema:

1. **Analiza el mensaje** con Claude para extraer criterios de búsqueda
2. **Genera consultas SQL** optimizadas para la base de datos
3. **Busca propiedades** que coincidan con los criterios
4. **Rankea resultados** según relevancia (scoring inteligente)
5. **Formatea respuesta** lista para enviar al cliente

---

## ✨ Características

- ✅ **Lenguaje natural**: Acepta mensajes informales de WhatsApp
- ✅ **Claude AI**: Usa el modelo más reciente (claude-3-5-sonnet-20241022)
- ✅ **Búsqueda inteligente**: Extrae ubicación, precio, habitaciones, amenidades, etc.
- ✅ **Scoring de relevancia**: Rankea resultados por coincidencia
- ✅ **Formato amigable**: Salida lista para enviar por WhatsApp
- ✅ **Exportación JSON**: Guarda resultados en archivos
- ✅ **Manejo de precios colombianos**: Entiende "800 millones", "1000 millones", etc.

---

## 📋 Requisitos Previos

### 1. API Key de Anthropic

Necesitas una API key de Anthropic (Claude):

1. Ve a https://console.anthropic.com/
2. Crea una cuenta o inicia sesión
3. Ve a **API Keys** en el menú
4. Crea una nueva API key
5. Cópiala (la usarás en el siguiente paso)

**Costo aproximado**: ~$0.003 USD por búsqueda (3 centavos por 10 búsquedas)

### 2. Dependencias

Instala el SDK de Anthropic:

```powershell
pip install anthropic
```

O instala todas las dependencias:

```powershell
pip install -r requirements.txt
```

### 3. Configurar `.env`

Agrega tu API key al archivo `.env`:

```env
# API Key de Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxxxxxxxxxx
```

**Importante**: Ya debes tener configurado `DATABASE_URL` de pasos anteriores.

---

## 🚀 Uso Rápido

### Opción 1: Ejecutar el script de prueba

```powershell
python busqueda_propiedades.py
```

Esto ejecutará una búsqueda de prueba con los ejemplos de consultas que compartiste.

**Salida esperada**:

```
================================================================================
  BÚSQUEDA INTELIGENTE DE PROPIEDADES
================================================================================

📝 Consulta:
   Busco apto cliente tu 360 en ciudad del Río o Laureles...

🧠 Analizando criterios con Claude...
✅ Criterios extraídos:
{
  "ubicaciones": ["Ciudad del Río", "Laureles"],
  "tipo_propiedad": "Apartamento",
  "precio_max": 1000000000,
  "habitaciones_min": 2,
  "habitaciones_max": 3,
  "piso": 1,
  "amenidades_requeridas": ["portería"]
}

🔍 Buscando en base de datos...
📊 Propiedades encontradas: 8

⭐ Rankeando resultados...

🏠 PROPIEDADES ENCONTRADAS
==================================================

📋 Criterios de búsqueda:
   📍 Ubicación: Ciudad del Río, Laureles
   🏢 Tipo: Apartamento
   💰 Hasta: $1000M
   🛏️  Habitaciones: 2+

✅ 8 propiedades coinciden

━━━ #1 - Match: 47 pts ━━━
🏠 Apartamento en Laureles, Laureles - 95m²
💵 $520,000,000 COP
📍 Laureles - Medellín
📐 95m² | 3 hab | 2 baños | 1 pkdros
🏢 Piso: 1
✨ Ubicación: Laureles, Precio dentro del presupuesto, Tiene: portería
👤 María González +573123456789
🔗 https://pulppo.com/propiedad/pulppo-00001

...
```

### Opción 2: Usar programáticamente

```python
from busqueda_propiedades import PropertySearchAgent

# Crear agente
agent = PropertySearchAgent()

# Consulta en lenguaje natural
query = """
Busco apto para cliente en Laureles o El Poblado
Hasta 800 millones
2 o 3 habitaciones
Con gimnasio y piscina
Urgente!
"""

# Buscar
resultados = agent.search(query, limit=10)

# Formatear para WhatsApp
mensaje = agent.format_results_for_agent(resultados)

print(mensaje)

# Guardar JSON
import json
with open('resultados.json', 'w') as f:
    json.dump(resultados, f, indent=2, ensure_ascii=False)
```

---

## 📊 Ejemplos de Consultas Soportadas

El sistema entiende mensajes informales como los que compartiste:

### Ejemplo 1: Búsqueda con ubicación y presupuesto

```
Busco apto cliente tu 360 en ciudad del Río o Laureles
Persona mayor primer piso. 2 o 3 habitaciones.
Con portería.
Presupuesto 1000 millones.
Rocío Escudero Vega
3103721706
```

**Criterios extraídos**:
- Ubicaciones: Ciudad del Río, Laureles
- Tipo: Apartamento
- Precio máximo: 1,000,000,000 COP
- Habitaciones: 2-3
- Piso: 1
- Amenidades: portería

---

### Ejemplo 2: Búsqueda con requisitos específicos

```
Busco para una cliente de tu 360inmobiliario
Súper compradora !!!!!!!!

Hasta $800 millones
Apartamento de dos alcobas CADA UNA CON BAÑO.
BALCON
Baño social
Ojalá con un estudio o que la alcoba principal sea amplia
80 m2 o más
Ojalá unidad con piscina
Directo por favor !
LE GUSTA :
Loma de san Julián
Loma del encierro
Castropol
Lalinde
```

**Criterios extraídos**:
- Ubicaciones: Loma de San Julián, Loma del Encierro, Castropol, Lalinde
- Tipo: Apartamento
- Precio máximo: 800,000,000 COP
- Habitaciones: 2
- Área mínima: 80 m²
- Amenidades: balcón, piscina
- Características especiales: "baño en cada habitación"

---

### Ejemplo 3: Búsqueda simple

```
APTO EL TRIANON EL DORADO LA CUENCA LAS ANTILLAS ALCALA

✅500.000 MILLONES
 3 HABITACIONES
Ojala unidad completa

Soy Sandra Echeverri Asesora inmobiliaria
📲Contáctame:
Cel :3235075028
```

**Criterios extraídos**:
- Ubicaciones: El Trianon, El Dorado, La Cuenca, Las Antillas, Alcalá
- Tipo: Apartamento
- Precio máximo: 500,000,000 COP
- Habitaciones: 3

---

## 🧠 Cómo Funciona

### 1. Extracción de Criterios con Claude

Claude analiza el mensaje y extrae:

```json
{
  "ubicaciones": ["Laureles", "El Poblado"],
  "tipo_propiedad": "Apartamento",
  "precio_max": 800000000,
  "habitaciones_min": 2,
  "habitaciones_max": 3,
  "amenidades_requeridas": ["gimnasio", "piscina"],
  "urgencia": true
}
```

### 2. Generación de Consulta SQL

El sistema genera SQL dinámico:

```sql
SELECT * FROM propiedades
WHERE activa = TRUE
  AND (zona ILIKE '%Laureles%' OR zona ILIKE '%El Poblado%')
  AND tipo_propiedad ILIKE '%Apartamento%'
  AND precio <= 800000000
  AND habitaciones >= 2
  AND habitaciones <= 3
  AND (amenidades_internas ILIKE '%gimnasio%' OR amenidades_externas ILIKE '%gimnasio%')
  AND (amenidades_internas ILIKE '%piscina%' OR amenidades_externas ILIKE '%piscina%')
ORDER BY total_amenidades DESC, precio ASC
LIMIT 20;
```

### 3. Scoring de Relevancia

Cada propiedad recibe un score basado en:

| Criterio | Puntos |
|----------|--------|
| Ubicación exacta | +10 |
| Tipo de propiedad | +5 |
| Precio 10% bajo máximo | +8 |
| Precio dentro presupuesto | +5 |
| Habitaciones exactas | +7 |
| Habitaciones en rango | +3 |
| Amenidad requerida (cada una) | +6 |
| Piso preferido | +8 |
| Muchas amenidades (15+) | +4 |

**Ejemplo**:
- Apartamento en Laureles (ubicación exacta): +10
- Tipo Apartamento: +5
- Precio $520M (bajo $800M): +8
- 2 habitaciones (exacto): +7
- Tiene gimnasio: +6
- Tiene piscina: +6
- **Total: 42 puntos**

---

## 📁 Archivos del Sistema

```
proyecto-cupido-tu360/
├── busqueda_propiedades.py       # ⭐ Sistema principal
├── database.py                    # Conexión a DB (ya existente)
├── .env                          # Configuración (DATABASE_URL + ANTHROPIC_API_KEY)
├── requirements.txt              # Dependencias (incluye anthropic)
└── busqueda_resultado_*.json     # Resultados guardados
```

---

## ⚙️ Configuración Avanzada

### Cambiar modelo de Claude

En `busqueda_propiedades.py`, línea 32:

```python
MODEL = "claude-3-5-sonnet-20241022"  # Modelo actual (recomendado)

# Alternativas:
# MODEL = "claude-3-opus-20240229"      # Más potente, más caro
# MODEL = "claude-3-haiku-20240307"     # Más rápido, más económico
```

### Ajustar límite de resultados

```python
resultados = agent.search(query, limit=20)  # Hasta 20 resultados
```

### Personalizar sistema de scoring

En `busqueda_propiedades.py`, método `_rank_results()` (líneas 229-297), puedes ajustar los puntajes:

```python
# Ejemplo: darle más peso a la ubicación
if ubicacion.lower() in result.get('zona', '').lower():
    score += 20  # Cambiado de 10 a 20
    reasons.append(f"Ubicación: {ubicacion}")
```

---

## 🔍 Consultas SQL de Ejemplo

### Ver todas las búsquedas realizadas

Los resultados se guardan en archivos JSON con timestamp:

```powershell
ls busqueda_resultado_*.json
```

### Verificar propiedades en ubicaciones específicas

```sql
SELECT zona, COUNT(*) as total
FROM propiedades
WHERE activa = TRUE
  AND zona IN ('Laureles', 'El Poblado', 'Envigado')
GROUP BY zona;
```

### Propiedades por rango de precio

```sql
SELECT
  CASE
    WHEN precio < 500000000 THEN 'Hasta $500M'
    WHEN precio < 800000000 THEN '$500M - $800M'
    WHEN precio < 1000000000 THEN '$800M - $1B'
    ELSE 'Más de $1B'
  END as rango_precio,
  COUNT(*) as total
FROM propiedades
WHERE activa = TRUE
GROUP BY rango_precio
ORDER BY MIN(precio);
```

---

## 🚨 Solución de Problemas

### Error: `ANTHROPIC_API_KEY no configurada`

**Causa**: Falta la API key en `.env`

**Solución**:
1. Obtén tu API key en https://console.anthropic.com/
2. Agrégala al archivo `.env`:
   ```env
   ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxxxxxxx
   ```

---

### Error: `Módulo 'anthropic' no instalado`

**Causa**: SDK no instalado

**Solución**:
```powershell
pip install anthropic
```

O:
```powershell
pip install -r requirements.txt
```

---

### Error: `No se pudieron extraer criterios de búsqueda`

**Causa**: Claude no pudo parsear el mensaje o error en API

**Solución**:
1. Verifica que ANTHROPIC_API_KEY sea válida
2. Revisa que tengas créditos en tu cuenta de Anthropic
3. Prueba con una consulta más simple:
   ```python
   query = "Busco apartamento en Laureles hasta 500 millones"
   ```

---

### No se encuentran propiedades

**Causa**: Criterios demasiado restrictivos o DB vacía

**Solución**:
1. Verifica que tienes propiedades en la DB:
   ```python
   from database import DatabaseManager
   with DatabaseManager() as db:
       stats = db.get_statistics()
       print(stats)
   ```

2. Si DB está vacía, carga propiedades:
   ```powershell
   python cargar_pulppo_auto.py
   ```

3. Prueba con criterios más amplios:
   ```python
   query = "Busco apartamento en Medellín"  # Sin restricciones
   ```

---

## 💡 Casos de Uso

### 1. WhatsApp Bot

Integra el sistema en un bot de WhatsApp:

```python
from busqueda_propiedades import PropertySearchAgent

agent = PropertySearchAgent()

def procesar_mensaje_whatsapp(mensaje):
    resultados = agent.search(mensaje, limit=5)
    respuesta = agent.format_results_for_agent(resultados)
    enviar_whatsapp(respuesta)  # Tu función de envío
```

---

### 2. API REST

Crea un endpoint para el sistema:

```python
from flask import Flask, request, jsonify
from busqueda_propiedades import PropertySearchAgent

app = Flask(__name__)
agent = PropertySearchAgent()

@app.route('/buscar', methods=['POST'])
def buscar():
    query = request.json.get('query')
    resultados = agent.search(query, limit=10)
    return jsonify(resultados)
```

---

### 3. Dashboard Interno

Interfaz web para agentes:

```python
import streamlit as st
from busqueda_propiedades import PropertySearchAgent

st.title("🏠 Búsqueda de Propiedades")

query = st.text_area("Escribe tu búsqueda:")

if st.button("Buscar"):
    agent = PropertySearchAgent()
    resultados = agent.search(query)
    st.json(resultados)
```

---

## 📈 Mejoras Futuras

Algunas ideas para extender el sistema:

- [ ] Búsqueda por imágenes (mostrar imagen principal)
- [ ] Filtros geográficos (radio desde un punto)
- [ ] Comparación de propiedades
- [ ] Historial de búsquedas del agente
- [ ] Notificaciones cuando aparezcan nuevas propiedades
- [ ] Integración con CRM inmobiliario
- [ ] Análisis de preferencias del cliente (ML)
- [ ] Generación automática de descripciones atractivas

---

## 📝 Ejemplo Completo

```powershell
# 1. Configurar API key
# Edita .env y agrega:
# ANTHROPIC_API_KEY=sk-ant-api03-xxxxx

# 2. Instalar dependencias
pip install anthropic

# 3. Verificar que tienes propiedades en DB
python -c "from database import DatabaseManager; db = DatabaseManager(); db.__enter__(); print(db.get_statistics()); db.__exit__(None, None, None)"

# 4. Ejecutar búsqueda de prueba
python busqueda_propiedades.py

# 5. Ver resultados
cat busqueda_resultado_*.json

# 6. Usar en tu código
python
>>> from busqueda_propiedades import PropertySearchAgent
>>> agent = PropertySearchAgent()
>>> query = "Busco casa en El Poblado hasta 1.5 billones con piscina"
>>> resultados = agent.search(query)
>>> print(agent.format_results_for_agent(resultados))
```

---

## 🎯 Resultado Esperado

Al ejecutar `python busqueda_propiedades.py`:

```
================================================================================
  BÚSQUEDA INTELIGENTE DE PROPIEDADES
================================================================================

📝 Consulta:
   Busco apto cliente tu 360 en ciudad del Río o Laureles...

🧠 Analizando criterios con Claude...
✅ Criterios extraídos:
{
  "ubicaciones": ["Ciudad del Río", "Laureles"],
  "tipo_propiedad": "Apartamento",
  "precio_max": 1000000000,
  "habitaciones_min": 2,
  "habitaciones_max": 3,
  "piso": 1,
  "amenidades_requeridas": ["portería"]
}

🔍 Buscando en base de datos...
📊 Propiedades encontradas: 12

⭐ Rankeando resultados...

🏠 PROPIEDADES ENCONTRADAS
==================================================

📋 Criterios de búsqueda:
   📍 Ubicación: Ciudad del Río, Laureles
   🏢 Tipo: Apartamento
   💰 Hasta: $1000M
   🛏️  Habitaciones: 2+

✅ 12 propiedades coinciden

━━━ #1 - Match: 47 pts ━━━
🏠 Apartamento en Laureles, Laureles - 95m²
💵 $520,000,000 COP
📍 Laureles - Medellín
📐 95m² | 3 hab | 2 baños | 1 pkdros
🏢 Piso: 1
✨ Ubicación: Laureles, Precio dentro del presupuesto, Tiene: portería
👤 María González +573123456789
🔗 https://pulppo.com/propiedad/pulppo-00001

━━━ #2 - Match: 42 pts ━━━
...

💾 Resultados guardados en: busqueda_resultado_20251031_152030.json
```

---

## 🚀 ¡Listo para usar!

El sistema está **listo para usar** en producción. Solo necesitas:

1. ✅ API key de Anthropic configurada
2. ✅ Propiedades en la base de datos
3. ✅ Ejecutar `python busqueda_propiedades.py`

**¡Ahora los agentes pueden buscar propiedades en lenguaje natural!** 🎉

---

## 📞 Soporte

Si tienes dudas sobre:
- **Anthropic/Claude**: https://docs.anthropic.com/
- **PostgreSQL/Neon**: Ver `INTEGRACION_NEON.md`
- **Este sistema**: Revisa el código en `busqueda_propiedades.py` (está documentado)

---

**Desarrollado para Tu360 Inmobiliario** 🏠✨
