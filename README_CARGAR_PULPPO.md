# 🏠 Carga de Propiedades Pulppo

Scripts para cargar propiedades de prueba de **Pulppo** en Neon PostgreSQL.

---

## 📋 ¿Qué hace?

Genera y carga propiedades realistas en Medellín con:
- ✅ Datos inventados pero realistas (precios, zonas, características)
- ✅ **Fuente: "Pulppo"** (se diferencia de Wasi en la DB)
- ✅ **Reutiliza imágenes HD** extraídas del scraper de Wasi
- ✅ Propiedades en 10 zonas diferentes de Medellín
- ✅ 4 tipos: Apartamento, Casa, Penthouse, Duplex

---

## 🚀 Opciones de Uso

### **Opción 1: Interactiva** (te pregunta cuántas propiedades)

```powershell
python cargar_pulppo.py
```

**Ejemplo:**
```
¿Cuántas propiedades de Pulppo deseas cargar? (recomendado: 10-50): 20

🏗️  Generando 20 propiedades de Pulppo en Medellín...

  ✓ Generada: Apartamento en El Tesoro, El Poblado - 95m² - $520,000,000
  ✓ Generada: Casa en Laureles, Laureles - 280m² - $1,200,000,000
  ...

¿Deseas guardar estas propiedades en Neon? (s/n): s

💾 Conectando a Neon PostgreSQL...
🗄️  Guardando propiedades en la base de datos...

✅ Propiedades guardadas exitosamente: 20
📊 Total procesadas: 20

📈 ESTADÍSTICAS:
  • Total propiedades: 25
  • Por fuente:
    - Wasi: 5
    - Pulppo: 20

🎉 ¡Carga completada exitosamente!
```

---

### **Opción 2: Automática** (sin preguntas, carga directo)

```powershell
python cargar_pulppo_auto.py
```

Por defecto carga **20 propiedades**. Para cambiar el número, edita el archivo:

```python
# En cargar_pulppo_auto.py, línea 11
NUM_PROPIEDADES = 50  # Cambia este número
```

---

## 📊 Datos Generados

### Zonas de Medellín (10)
- El Poblado
- Laureles
- Envigado
- Sabaneta
- Belén
- Estadio
- La América
- Castilla
- Robledo
- Buenos Aires

### Tipos de Propiedad
| Tipo | Área | Habitaciones | Precio |
|------|------|--------------|--------|
| Apartamento | 60-150m² | 2-4 | $250M - $800M |
| Casa | 120-400m² | 3-6 | $400M - $1.5B |
| Penthouse | 150-300m² | 3-5 | $800M - $2B |
| Duplex | 100-200m² | 2-4 | $300M - $900M |

### Características Realistas
- ✅ Estratos: 3, 4, 5, 6
- ✅ Coordenadas GPS aleatorias cerca de Medellín
- ✅ Año de construcción: 2010-2024
- ✅ Amenidades internas: 4-7 (cocina, balcón, closets, etc.)
- ✅ Amenidades externas: 5-9 (ascensor, vigilancia, gimnasio, etc.)
- ✅ Imágenes HD: 3-6 por propiedad (reutilizadas de Wasi)
- ✅ Códigos únicos: PULPPO-00001, PULPPO-00002, etc.

---

## 🔍 Consultar Propiedades Cargadas

### En Neon SQL Editor

```sql
-- Ver todas las propiedades de Pulppo
SELECT titulo, precio, zona, tipo_propiedad
FROM propiedades
WHERE fuente = 'Pulppo'
ORDER BY fecha_creacion DESC;

-- Contar por zona
SELECT zona, COUNT(*) as total
FROM propiedades
WHERE fuente = 'Pulppo'
GROUP BY zona
ORDER BY total DESC;

-- Propiedades más caras de Pulppo
SELECT titulo, precio, zona, habitaciones, banos
FROM propiedades
WHERE fuente = 'Pulppo'
ORDER BY precio DESC
LIMIT 10;

-- Comparar Wasi vs Pulppo
SELECT fuente, COUNT(*) as total, AVG(precio) as precio_promedio
FROM propiedades
GROUP BY fuente;
```

### En Python

```python
from database import DatabaseManager

with DatabaseManager() as db:
    # Ver todas las propiedades de Pulppo
    propiedades = db.get_all_properties(fuente='Pulppo')

    for prop in propiedades[:5]:
        print(f"- {prop['titulo']}")
        print(f"  Precio: ${prop['precio']:,}")
        print(f"  Zona: {prop['zona']}")
        print()
```

---

## 🎨 Imágenes Reutilizadas

Las propiedades de Pulppo usan imágenes HD extraídas del scraper de Wasi:
- 5 imágenes base disponibles
- Cada propiedad recibe 3-6 imágenes aleatorias
- Resolución: 979x743px (alta calidad)
- Formato: URLs de image.wasi.co

**Ventaja:** No necesitas descargar imágenes nuevas, se reutilizan las existentes.

---

## ⚙️ Configuración

### Cambiar cantidad de propiedades

**En `cargar_pulppo_auto.py`:**
```python
NUM_PROPIEDADES = 100  # Genera 100 propiedades
```

### Agregar más zonas

Edita las listas en el script:
```python
ZONAS_MEDELLIN = [
    "El Poblado", "Laureles", ..., "Tu Nueva Zona"
]

BARRIOS_POR_ZONA = {
    "Tu Nueva Zona": ["Barrio 1", "Barrio 2", ...]
}
```

### Agregar más imágenes

Agrega URLs al array `IMAGENES_DISPONIBLES`:
```python
IMAGENES_DISPONIBLES = [
    "https://image.wasi.co/...",  # Existentes
    "https://nueva-imagen.com/...",  # Nuevas
]
```

---

## ✅ Requisitos

Antes de ejecutar, asegúrate de tener:

1. **Archivo .env configurado** con DATABASE_URL
2. **Dependencias instaladas:**
   ```powershell
   pip install psycopg2-binary python-dotenv
   ```
3. **Tablas creadas en Neon** (ejecutar schema.sql)
4. **Módulo database.py** en la misma carpeta

**Verificar:**
```powershell
python check_db_setup.py
```

---

## 📈 Casos de Uso

### 1. Testing de la Base de Datos
Cargar propiedades de prueba para validar que todo funciona.

```powershell
python cargar_pulppo_auto.py
```

### 2. Dataset de Desarrollo
Generar un dataset grande para desarrollo/pruebas.

```python
# Editar NUM_PROPIEDADES = 100
python cargar_pulppo_auto.py
```

### 3. Demostración
Mostrar propiedades de múltiples fuentes (Wasi + Pulppo).

```sql
SELECT fuente, COUNT(*) FROM propiedades GROUP BY fuente;
-- Wasi: 5
-- Pulppo: 20
```

---

## 🔄 Actualizar Propiedades

Si ejecutas el script dos veces con las mismas propiedades:
- **1ra vez:** INSERT (crea nuevos registros)
- **2da vez:** UPDATE (actualiza existentes)

Cada propiedad tiene código único (`PULPPO-00001`), así que no hay duplicados.

---

## 🗑️ Limpiar Propiedades de Pulppo

```sql
-- Eliminar todas las propiedades de Pulppo
DELETE FROM propiedades WHERE fuente = 'Pulppo';

-- O marcar como inactivas (recomendado)
UPDATE propiedades SET activa = FALSE WHERE fuente = 'Pulppo';
```

---

## 📝 Ejemplo Completo

```powershell
# 1. Verificar setup
python check_db_setup.py

# 2. Cargar 30 propiedades de Pulppo
python cargar_pulppo.py
# Ingresa: 30
# Confirma: s

# 3. Ver en Neon SQL Editor
SELECT titulo, precio, zona
FROM propiedades
WHERE fuente = 'Pulppo'
LIMIT 10;

# 4. Ver estadísticas
SELECT fuente, COUNT(*), AVG(precio)
FROM propiedades
GROUP BY fuente;
```

---

## 🎯 Resultado Esperado

Después de ejecutar:

```
📊 ESTADÍSTICAS DE LA BASE DE DATOS:
  • Total propiedades: 25
  • Por fuente:
    - Wasi: 5
    - Pulppo: 20
  • Propiedades en Medellín: 25
```

**En Neon verás:**
- 5 propiedades reales de Wasi (scrapeadas)
- 20 propiedades de prueba de Pulppo (generadas)
- Todas con el campo `fuente` diferenciando la procedencia
- Todas con imágenes HD

---

## 🚀 Siguiente Paso

Una vez cargadas las propiedades de Pulppo, puedes:
1. Consultarlas en Neon SQL Editor
2. Crear una API para exponerlas
3. Desarrollar un frontend que las muestre
4. Agregar scrapers para otras fuentes (Fincaraiz, etc.)

---

**¡Listo para cargar propiedades de Pulppo!** 🏠✨

Ejecuta: `python cargar_pulppo_auto.py` y en segundos tendrás 20 propiedades de prueba en Neon.
