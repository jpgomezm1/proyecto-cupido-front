# 🗄️ Integración con Neon PostgreSQL

## 📋 Resumen

El scraper ahora guarda automáticamente todas las propiedades en una base de datos **Neon PostgreSQL** en la nube, además de los archivos CSV/JSON/Excel.

---

## 🎯 Características

- ✅ **Guardado automático** en base de datos después del scraping
- ✅ **Campo "fuente"** para identificar de dónde vienen los datos (Wasi, Fincaraiz, etc.)
- ✅ **37 campos** almacenados por propiedad
- ✅ **Actualización automática** si la propiedad ya existe (ON CONFLICT)
- ✅ **Índices optimizados** para búsquedas rápidas
- ✅ **Estadísticas** de la base de datos
- ✅ **Context manager** para manejo seguro de conexiones

---

## 📦 Dependencias Nuevas

Agregadas al `requirements.txt`:

```
psycopg2-binary==2.9.9    # Driver PostgreSQL
python-dotenv==1.0.0      # Manejo de variables de entorno
```

Instalar con:
```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuración

### 1️⃣ Crear cuenta en Neon

1. Ve a [https://neon.tech](https://neon.tech)
2. Crea una cuenta gratuita
3. Crea un nuevo proyecto
4. Copia la **Connection String** (formato: `postgresql://...`)

### 2️⃣ Configurar archivo .env

```bash
# Copiar el archivo de ejemplo
cp .env.example .env

# Editar el archivo .env
nano .env
```

Contenido del archivo `.env`:

```env
# URL de conexión de Neon PostgreSQL
DATABASE_URL=postgresql://tu_usuario:tu_password@ep-xxxx.us-east-2.aws.neon.tech/tu_database?sslmode=require

# Configuración del Scraper (opcional)
DELAY_BETWEEN_REQUESTS=2
VERBOSE_MODE=True
```

**IMPORTANTE:** Reemplaza con tu URL real de Neon.

### 3️⃣ Crear las tablas

Ejecuta el script SQL en Neon:

**Opción A: Desde la consola de Neon**
1. Ve a tu proyecto en Neon
2. Abre el **SQL Editor**
3. Pega el contenido de `schema.sql`
4. Ejecuta

**Opción B: Desde Python**
```bash
python3 -c "from database import DatabaseManager; db = DatabaseManager(); db.connect(); db.create_tables(); db.disconnect()"
```

---

## 🚀 Uso

### Scraping con guardado automático en DB

```bash
# Ejecutar scraper (guarda en archivos + DB)
python scrapper_wasi.py
```

**Salida esperada:**
```
🚀 Iniciando scraper de Wasi
📁 Leyendo URLs desde: links_wasi.txt

✓ Se encontraron 5 URLs para procesar

Scrapeando propiedades: 100%|███████| 5/5 [00:15<00:00]

✓ Scraping completado!
  • Propiedades extraídas: 5
  • Errores: 0

💾 Guardando datos...

✓ CSV guardado: data/propiedades_wasi_TIMESTAMP.csv
✓ JSON guardado: data/propiedades_wasi_TIMESTAMP.json
✓ Excel guardado: data/propiedades_wasi_TIMESTAMP.xlsx

🗄️  Guardando en base de datos Neon PostgreSQL...
✅ Conexión a Neon PostgreSQL establecida
✅ Tablas creadas/verificadas correctamente
✅ Propiedad 9512913 guardada en DB (ID: 1)
✅ Propiedad 9562791 guardada en DB (ID: 2)
✅ Propiedad 9560158 guardada en DB (ID: 3)
✅ Propiedad 9557701 guardada en DB (ID: 4)
✅ Propiedad 8479156 guardada en DB (ID: 5)
🔌 Conexión cerrada
✓ Base de datos actualizada:
  • Propiedades guardadas: 5

✅ Todos los archivos guardados en: data/
```

---

## 📊 Estructura de la Base de Datos

### Tabla: `propiedades`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `id` | SERIAL | ID autoincremental (PK) |
| `codigo_propiedad` | VARCHAR(50) | Código único (UNIQUE) |
| **`fuente`** | **VARCHAR(50)** | **'Wasi', 'Fincaraiz', etc.** |
| `url` | TEXT | URL de la propiedad |
| `titulo` | TEXT | Título de la propiedad |
| `precio` | BIGINT | Precio en COP |
| ... | ... | 37 campos en total |
| `fecha_extraccion` | TIMESTAMP | Cuándo se scrapeó |
| `fecha_creacion` | TIMESTAMP | Cuándo se guardó en DB |
| `fecha_actualizacion` | TIMESTAMP | Última actualización |
| `activa` | BOOLEAN | Si está disponible |

### Índices Creados

- `codigo_propiedad` (UNIQUE)
- `fuente` (para filtrar por fuente)
- `ciudad`, `zona` (búsquedas por ubicación)
- `precio`, `tipo_propiedad` (filtros)
- `latitud, longitud` (búsquedas geoespaciales)

---

## 🔍 Consultas Útiles

### Ver todas las propiedades de Wasi

```python
from database import DatabaseManager

with DatabaseManager() as db:
    propiedades = db.get_all_properties(fuente='Wasi')
    print(f"Total propiedades Wasi: {len(propiedades)}")
    for prop in propiedades[:5]:
        print(f"- {prop['titulo']} - ${prop['precio']:,}")
```

### Buscar propiedad por código

```python
from database import DatabaseManager

with DatabaseManager() as db:
    prop = db.get_property_by_code('9512913')
    if prop:
        print(f"Título: {prop['titulo']}")
        print(f"Precio: ${prop['precio']:,}")
        print(f"Fuente: {prop['fuente']}")
```

### Estadísticas de la base de datos

```python
from database import DatabaseManager

with DatabaseManager() as db:
    stats = db.get_statistics()
    print(f"Total propiedades: {stats['total_propiedades']}")
    print(f"Por fuente: {stats['por_fuente']}")
    print(f"Precio promedio: ${stats['precios']['promedio']:,.0f}")
```

### SQL directo

```sql
-- Todas las propiedades de Wasi en Medellín
SELECT titulo, precio, zona, habitaciones, banos
FROM propiedades
WHERE fuente = 'Wasi'
  AND ciudad = 'Medellín'
  AND activa = TRUE
ORDER BY precio DESC;

-- Propiedades por ciudad
SELECT ciudad, COUNT(*) as total, AVG(precio) as precio_promedio
FROM propiedades
WHERE fuente = 'Wasi'
GROUP BY ciudad
ORDER BY total DESC;

-- Propiedades con más imágenes
SELECT titulo, total_imagenes, imagenes_hd_count
FROM propiedades
ORDER BY total_imagenes DESC
LIMIT 10;
```

---

## 🛠️ API del Módulo Database

### Clase `DatabaseManager`

```python
from database import DatabaseManager

# Uso con context manager (recomendado)
with DatabaseManager() as db:
    db.create_tables()
    db.insert_property(property_dict)
    props = db.get_all_properties()
    stats = db.get_statistics()

# Uso manual
db = DatabaseManager()
db.connect()
# ... operaciones ...
db.disconnect()
```

### Métodos Principales

#### `connect()`
Establece conexión con Neon PostgreSQL.

#### `create_tables()`
Crea las tablas si no existen (ejecuta `schema.sql`).

#### `insert_property(property_data)`
Inserta o actualiza una propiedad.
- Si `codigo_propiedad` existe → UPDATE
- Si no existe → INSERT

#### `get_property_by_code(codigo)`
Obtiene una propiedad por su código.

#### `get_all_properties(limit=None, fuente=None)`
Obtiene todas las propiedades activas.
- `limit`: Limitar resultados
- `fuente`: Filtrar por fuente ('Wasi', etc.)

#### `get_statistics()`
Retorna estadísticas de la base de datos.

### Función Helper

```python
from database import save_properties_to_db

# Guardar lista de propiedades
exitosas, fallidas = save_properties_to_db(lista_propiedades)
```

---

## 🔧 Solución de Problemas

### Error: "DATABASE_URL no está definida"

```bash
# Verificar que .env existe
ls -la .env

# Verificar contenido
cat .env

# Debe tener:
DATABASE_URL=postgresql://...
```

### Error: "No module named 'psycopg2'"

```bash
pip install psycopg2-binary
```

### Error de conexión a Neon

1. Verifica que la URL sea correcta
2. Verifica que termine en `?sslmode=require`
3. Prueba la conexión manualmente:

```python
import psycopg2
conn = psycopg2.connect("postgresql://...")
print("✅ Conexión exitosa")
conn.close()
```

### Las propiedades no se guardan en DB

1. Verifica que `save_to_db=True` en el scraper
2. Verifica que `database.py` esté en la misma carpeta
3. Revisa los logs de error

---

## 📈 Características Avanzadas

### ON CONFLICT - Actualización automática

Si scrapeás la misma propiedad dos veces:
- 1ra vez: INSERT (crea registro nuevo)
- 2da vez: UPDATE (actualiza registro existente)

El `codigo_propiedad` es UNIQUE, así que no hay duplicados.

### Trigger de actualización

Cada vez que se actualiza una propiedad:
```sql
fecha_actualizacion = CURRENT_TIMESTAMP
```

Se actualiza automáticamente vía trigger.

### Campo "activa"

Por defecto, todas las propiedades son `activa = TRUE`.

Puedes marcar propiedades como inactivas:
```sql
UPDATE propiedades
SET activa = FALSE
WHERE codigo_propiedad = '9512913';
```

Las consultas por defecto solo traen propiedades activas.

---

## 🎯 Próximos Pasos

### Expansión del campo "fuente"

Cuando agregues scrapers para otras plataformas:

```python
# En scrapper_wasi.py
data['fuente'] = 'Wasi'

# En scrapper_fincaraiz.py (futuro)
data['fuente'] = 'Fincaraiz'

# En scrapper_properati.py (futuro)
data['fuente'] = 'Properati'
```

Todas las propiedades se guardarán en la misma tabla con el campo `fuente` diferenciándolas.

### API REST (sugerido)

```python
# Crear API con FastAPI o Flask
# Para consultar propiedades desde frontend

@app.get("/propiedades")
def get_propiedades(fuente: str = None, ciudad: str = None):
    with DatabaseManager() as db:
        return db.get_all_properties(fuente=fuente)
```

### Dashboard

- Conectar con Streamlit o Dash
- Visualizar propiedades en mapa
- Gráficos de precios por zona
- Comparador de propiedades

---

## ✅ Checklist de Integración

- [x] Archivo `schema.sql` creado
- [x] Archivo `database.py` creado
- [x] Archivo `.env.example` creado
- [x] `.gitignore` actualizado
- [x] `requirements.txt` actualizado
- [x] `scrapper_wasi.py` modificado (campo fuente + guardado DB)
- [x] Documentación completa

**Pasos para el usuario:**
- [ ] Crear cuenta en Neon
- [ ] Configurar archivo `.env` con DATABASE_URL
- [ ] Instalar dependencias: `pip install -r requirements.txt`
- [ ] Ejecutar schema.sql en Neon
- [ ] Ejecutar scraper: `python scrapper_wasi.py`
- [ ] Verificar datos en Neon SQL Editor

---

## 📞 Resumen Rápido

```bash
# 1. Configurar .env
cp .env.example .env
nano .env  # Pegar DATABASE_URL de Neon

# 2. Instalar dependencias
pip install psycopg2-binary python-dotenv

# 3. Crear tablas (en Neon SQL Editor o Python)
# Pegar contenido de schema.sql

# 4. Ejecutar scraper
python scrapper_wasi.py

# ✅ Los datos se guardan en:
# - data/ (CSV/JSON/Excel)
# - Neon PostgreSQL (base de datos)
```

---

**¡La integración con Neon está completa!** 🎉🗄️

Todas las propiedades ahora se guardan automáticamente en la nube con el campo **`fuente: 'Wasi'`**.
