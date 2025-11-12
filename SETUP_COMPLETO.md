# 🚀 Setup Completo - Scraper Wasi + Neon PostgreSQL

## 📋 Resumen

Guía completa para configurar el scraper de propiedades Wasi con guardado automático en Neon PostgreSQL.

---

## ✅ Pre-requisitos

- Python 3.8 o superior
- Cuenta en Neon (gratis en https://neon.tech)
- Conexión a internet

---

## 📦 Paso 1: Instalar Dependencias

### 1.1 Instalar python3-venv (si no lo tienes)

```bash
sudo apt install python3.12-venv
```

### 1.2 Crear entorno virtual

```bash
cd /ruta/al/proyecto/proyecto-cupido-tu360
python3 -m venv venv
```

### 1.3 Activar entorno virtual

```bash
source venv/bin/activate
```

### 1.4 Instalar todas las dependencias

```bash
pip install -r requirements.txt
```

**Dependencias instaladas:**
- requests - Peticiones HTTP
- beautifulsoup4 - Parsing HTML
- pandas - Manipulación de datos
- lxml - Parser HTML
- openpyxl - Exportar Excel
- tqdm - Barras de progreso
- **psycopg2-binary** - Conexión PostgreSQL
- **python-dotenv** - Variables de entorno

---

## 🗄️ Paso 2: Configurar Neon PostgreSQL

### 2.1 Crear cuenta y proyecto en Neon

1. Ve a https://neon.tech
2. Crea una cuenta (gratis)
3. Crea un nuevo proyecto:
   - Nombre: "cupido-propiedades" (o el que prefieras)
   - Región: US East (recomendado)
4. Copia la **Connection String** (botón "Connect")

Ejemplo de Connection String:
```
postgresql://usuario:password@ep-xxx-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require
```

### 2.2 Crear archivo .env

```bash
# Copiar plantilla
cp .env.example .env

# Editar archivo
nano .env
```

**Contenido del archivo .env:**
```env
# URL de conexión de Neon PostgreSQL (REEMPLAZA CON LA TUYA)
DATABASE_URL=postgresql://usuario:password@ep-xxx-xxx.us-east-2.aws.neon.tech/neondb?sslmode=require

# Configuración del Scraper
DELAY_BETWEEN_REQUESTS=2
VERBOSE_MODE=True
```

**IMPORTANTE:**
- Reemplaza `DATABASE_URL` con tu URL real de Neon
- Guarda el archivo

### 2.3 Crear tablas en Neon

**Opción A: Desde Neon SQL Editor (Recomendado)**

1. Ve a tu proyecto en Neon
2. Abre el **SQL Editor**
3. Abre el archivo `schema.sql` y copia TODO su contenido
4. Pega en el SQL Editor
5. Haz clic en "Run"

**Opción B: Desde Python**

```bash
python3 -c "from database import DatabaseManager; db = DatabaseManager(); db.connect(); db.create_tables(); db.disconnect()"
```

### 2.4 Verificar conexión

```bash
python test_database.py
```

**Salida esperada:**
```
============================================================
  TEST DE CONEXIÓN - NEON POSTGRESQL
============================================================

✅ Archivo .env encontrado
✅ DATABASE_URL encontrada
   Host: ep-xxx.us-east-2.aws.neon.tech

Verificando módulos de Python...
✅ psycopg2 instalado
✅ database.py encontrado

Probando conexión a Neon PostgreSQL...
✅ Conexión exitosa a Neon PostgreSQL

Creando/verificando tablas...
✅ Tablas verificadas correctamente

📊 ESTADÍSTICAS:
   • Total propiedades: 0

============================================================
✅ TEST COMPLETADO EXITOSAMENTE
============================================================
```

---

## 🕷️ Paso 3: Ejecutar el Scraper

### 3.1 Verificar links

Edita `links_wasi.txt` si quieres agregar más URLs:

```bash
nano links_wasi.txt
```

Agrega una URL por línea:
```
https://info.wasi.co/apartamento-venta-ciudad-barrio/12345
https://info.wasi.co/casa-venta-ciudad-barrio/67890
...
```

### 3.2 Ejecutar scraper

```bash
python scrapper_wasi.py
```

**Salida esperada:**
```
╔════════════════════════════════════════════════════════════╗
║                   WASI PROPERTY SCRAPER                    ║
║                    Proyecto Cupido Tu360                   ║
╚════════════════════════════════════════════════════════════╝

🚀 Iniciando scraper de Wasi
📁 Leyendo URLs desde: links_wasi.txt

✓ Se encontraron 5 URLs para procesar

Scrapeando propiedades: 100%|██████████| 5/5 [00:15<00:00]

✓ Scraping completado!
  • Propiedades extraídas: 5
  • Errores: 0

💾 Guardando datos...

✓ CSV guardado: data/propiedades_wasi_20251028_150000.csv
✓ JSON guardado: data/propiedades_wasi_20251028_150000.json
✓ Excel guardado: data/propiedades_wasi_20251028_150000.xlsx

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

[Estadísticas adicionales...]

🎉 ¡Proceso completado exitosamente!
```

---

## 📊 Paso 4: Verificar Datos en Neon

### Opción A: SQL Editor de Neon

1. Ve a tu proyecto en Neon
2. Abre el **SQL Editor**
3. Ejecuta consultas:

```sql
-- Ver todas las propiedades
SELECT titulo, precio, ciudad, fuente
FROM propiedades
ORDER BY fecha_creacion DESC;

-- Contar por fuente
SELECT fuente, COUNT(*) as total
FROM propiedades
GROUP BY fuente;

-- Propiedades de Wasi en Medellín
SELECT titulo, precio, zona, habitaciones, banos
FROM propiedades
WHERE fuente = 'Wasi'
  AND ciudad = 'Medellín'
ORDER BY precio DESC;
```

### Opción B: Python

```python
from database import DatabaseManager

with DatabaseManager() as db:
    # Estadísticas
    stats = db.get_statistics()
    print(f"Total propiedades: {stats['total_propiedades']}")
    print(f"Por fuente: {stats['por_fuente']}")

    # Todas las propiedades de Wasi
    propiedades = db.get_all_properties(fuente='Wasi', limit=10)
    for prop in propiedades:
        print(f"- {prop['titulo']} - ${prop['precio']:,}")
```

---

## 🔧 Solución de Problemas

### Error: "No module named 'bs4'"

```bash
# Verifica que el entorno virtual esté activado
source venv/bin/activate

# Reinstala dependencias
pip install -r requirements.txt
```

### Error: "DATABASE_URL no está definida"

```bash
# Verifica que .env existe
ls -la .env

# Verifica contenido
cat .env

# Debe tener DATABASE_URL definida
```

### Error de conexión a Neon

1. Verifica que la URL sea correcta (cópiala de Neon)
2. Verifica que termine en `?sslmode=require`
3. Verifica que Neon no esté en modo sleep (abre Neon Dashboard)
4. Prueba la conexión manualmente:

```bash
python test_database.py
```

### Las imágenes salen en baja resolución

Las imágenes ahora se extraen en **alta resolución (979x743px)**. Verifica con:

```bash
python validar_imagenes.py
```

---

## 📁 Estructura del Proyecto

```
proyecto-cupido-tu360/
├── .env                          # Credenciales (NO subir a git)
├── .env.example                  # Plantilla de .env
├── .gitignore                    # Ignorar archivos sensibles
├── requirements.txt              # Dependencias Python
├── schema.sql                    # Esquema de base de datos
├── database.py                   # Módulo de conexión DB
├── scrapper_wasi.py             # Scraper principal ⭐
├── links_wasi.txt               # URLs a scrapear
├── test_database.py             # Test de conexión DB
├── validar_imagenes.py          # Validar imágenes HD
├── check_dependencies.py        # Verificar dependencias
├── setup.sh                     # Script de instalación
├── data/                        # Resultados (CSV/JSON/Excel)
├── venv/                        # Entorno virtual
└── docs/
    ├── INTEGRACION_NEON.md      # Doc de integración DB
    ├── MEJORA_IMAGENES.md       # Doc de imágenes HD
    ├── RESUMEN_FINAL.md         # Resumen general
    └── SETUP_COMPLETO.md        # Esta guía
```

---

## 🎯 Flujo Completo

```mermaid
graph TD
    A[1. Instalar dependencias] --> B[2. Configurar .env con Neon URL]
    B --> C[3. Crear tablas en Neon]
    C --> D[4. Ejecutar scraper]
    D --> E[5. Datos guardados en archivos]
    D --> F[6. Datos guardados en Neon DB]
    F --> G[7. Consultar en SQL Editor o Python]
```

---

## ✅ Checklist Final

**Instalación:**
- [ ] Python 3.8+ instalado
- [ ] python3-venv instalado
- [ ] Entorno virtual creado y activado
- [ ] Dependencias instaladas (`pip install -r requirements.txt`)

**Neon:**
- [ ] Cuenta creada en Neon
- [ ] Proyecto creado
- [ ] Connection String copiada
- [ ] Archivo `.env` configurado con DATABASE_URL
- [ ] Tablas creadas (desde SQL Editor o Python)
- [ ] Conexión verificada (`python test_database.py`)

**Scraper:**
- [ ] URLs agregadas a `links_wasi.txt`
- [ ] Scraper ejecutado (`python scrapper_wasi.py`)
- [ ] Archivos CSV/JSON/Excel generados en `data/`
- [ ] Propiedades guardadas en Neon
- [ ] Datos verificados en Neon SQL Editor

---

## 🚀 Próximos Pasos

### Agregar más URLs

```bash
nano links_wasi.txt
# Agregar más URLs
python scrapper_wasi.py
```

### Consultar datos

```python
from database import DatabaseManager

with DatabaseManager() as db:
    propiedades = db.get_all_properties(fuente='Wasi')
    # Hacer análisis...
```

### Expandir a otras fuentes

Cuando agregues scrapers para Fincaraiz, Properati, etc.:

1. Crea `scrapper_fincaraiz.py` (copia de `scrapper_wasi.py`)
2. Cambia `data['fuente'] = 'Fincaraiz'`
3. Ajusta selectores HTML según Fincaraiz
4. Ejecuta y todas las propiedades se guardarán en la misma DB

La tabla `propiedades` soporta múltiples fuentes automáticamente.

---

## 📞 Resumen Ejecutivo

```bash
# 1. Instalación (una sola vez)
sudo apt install python3.12-venv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Configurar Neon (una sola vez)
cp .env.example .env
nano .env  # Pegar DATABASE_URL de Neon
# Ejecutar schema.sql en Neon SQL Editor
python test_database.py  # Verificar

# 3. Scrapear (cada vez)
source venv/bin/activate
python scrapper_wasi.py

# ✅ Datos guardados en:
# - data/ (archivos)
# - Neon PostgreSQL (base de datos)
```

---

**¡Setup completo!** 🎉

Tienes un scraper funcional que extrae 37 campos por propiedad, incluyendo imágenes en alta resolución, y guarda todo automáticamente en Neon PostgreSQL con el campo **`fuente: 'Wasi'`**.
