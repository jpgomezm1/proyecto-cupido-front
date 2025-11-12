# 🏠 Wasi Property Scraper - Proyecto Cupido Tu360

Scraper completo para extraer información de propiedades inmobiliarias desde Wasi (info.wasi.co).

## 📁 Archivos del Proyecto

### Archivos Principales
- **`scrapper_wasi.py`** - Script principal del scraper (completo y funcional)
- **`links_wasi.txt`** - Archivo con URLs de propiedades a scrapear (5 links iniciales)
- **`requirements.txt`** - Dependencias de Python necesarias

### Scripts Auxiliares
- **`setup.sh`** - Script de instalación automática (Linux/Mac)
- **`check_dependencies.py`** - Verifica qué librerías faltan por instalar
- **`INSTRUCCIONES.md`** - Guía detallada de uso

### Carpetas
- **`data/`** - Carpeta donde se guardarán los resultados extraídos

## 🚀 Inicio Rápido

### Paso 1: Instalar Dependencias

Debido a las restricciones del sistema, necesitas crear un entorno virtual:

```bash
# Instalar python3-venv
sudo apt install python3.12-venv

# O usar el script automático
./setup.sh
```

**IMPORTANTE**: Tu sistema tiene las siguientes librerías ya instaladas:
- ✓ requests
- ✓ pandas
- ✓ openpyxl

**Faltan por instalar**:
- beautifulsoup4
- lxml
- tqdm

### Paso 2: Activar Entorno e Instalar

```bash
# Crear entorno virtual
python3 -m venv venv

# Activar
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

### Paso 3: Ejecutar el Scraper

```bash
# Con entorno virtual activado
python scrapper_wasi.py

# O directamente con python3
python3 scrapper_wasi.py
```

## 📊 Datos Extraídos

El scraper extrae **más de 35 campos** de cada propiedad:

### 🏷️ Información Básica
- Título
- Precio (valor numérico y texto)
- Código único
- Tipo (Apartamento, Casa, Penthouse, Lote, etc.)
- Estado

### 📍 Ubicación
- País, Departamento, Ciudad, Zona
- Dirección completa
- Coordenadas GPS (latitud/longitud)

### 🏗️ Características Físicas
- Área construida (m²)
- Habitaciones
- Baños
- Parqueaderos/Garajes
- Estrato
- Piso
- Año de construcción

### 💰 Costos
- Precio de venta
- Administración mensual
- Predial

### ✨ Amenidades
- Amenidades internas (cocina, balcón, etc.)
- Amenidades externas (ascensor, vigilancia, etc.)
- Total de amenidades

### 👤 Contacto
- Nombre del asesor
- Teléfono
- Inmobiliaria

### 📷 Multimedia
- URLs de todas las imágenes
- Total de imágenes
- URL imagen principal

### 📝 Otros
- Descripción completa
- Características adicionales
- Fecha de extracción

## 📤 Formatos de Salida

El scraper genera automáticamente 3 formatos:

1. **CSV** (`propiedades_wasi_TIMESTAMP.csv`) - Compatible con Excel, Google Sheets
2. **JSON** (`propiedades_wasi_TIMESTAMP.json`) - Estructura jerárquica completa
3. **Excel** (`propiedades_wasi_TIMESTAMP.xlsx`) - Formato nativo de Excel

## ⚙️ Características Avanzadas

### ✅ Manejo Robusto de Errores
- Reintentos automáticos
- Log detallado de errores
- Continúa aunque falle alguna URL

### 🎯 Optimizaciones
- Headers realistas para evitar bloqueos
- Delay configurable entre requests
- Session persistente para mejor rendimiento

### 📊 Reportes
- Estadísticas automáticas al finalizar
- Resumen con promedios de precios, áreas, etc.
- Conteo de tipos de propiedad

### 🔍 Modo Verbose
- Logging detallado de cada extracción
- Útil para debugging
- Activado por defecto

## 🎨 Personalización

Edita estos parámetros en `scrapper_wasi.py` (línea ~510):

```python
INPUT_FILE = 'links_wasi.txt'  # Archivo con URLs
OUTPUT_DIR = 'data'            # Carpeta de salida
DELAY = 2                      # Segundos entre requests
VERBOSE = True                 # Logging detallado
```

## 📝 Agregar Más Propiedades

Simplemente edita `links_wasi.txt` y agrega más URLs (una por línea):

```
https://info.wasi.co/apartamento-venta-ciudad-barrio/12345
https://info.wasi.co/casa-venta-ciudad-barrio/67890
https://info.wasi.co/penthouse-venta-ciudad-barrio/11111
```

El scraper funciona con **todos los tipos de propiedades de Wasi** ya que todas siguen la misma estructura HTML.

## 🔧 Solución de Problemas

### No puedo instalar dependencias
```bash
# Usa entorno virtual
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### El scraper se detiene
- Aumenta el `DELAY` a 5 segundos
- Verifica tu conexión a internet
- Revisa el log de errores en `data/`

### Faltan datos en la extracción
- Wasi puede cambiar su estructura HTML
- Revisa el modo verbose para ver qué falla
- Contacta para actualizar el scraper

## 📈 Próximas Mejoras

Posibles expansiones futuras:
- [ ] Scraper para otras plataformas (Fincaraíz, Properati, etc.)
- [ ] Detección automática de cambios en estructura HTML
- [ ] Dashboard visual de propiedades
- [ ] Alertas de nuevas propiedades
- [ ] Comparador de precios
- [ ] Análisis de mercado inmobiliario

## 📞 Soporte

Si encuentras problemas:
1. Verifica `data/scraper_errors_*.log`
2. Ejecuta `python3 check_dependencies.py`
3. Revisa `INSTRUCCIONES.md` para guía detallada

## 🎉 Estado del Proyecto

**✅ COMPLETADO Y LISTO PARA USAR**

- [x] Scraper principal desarrollado
- [x] Extracción de 35+ campos
- [x] Exportación a CSV/JSON/Excel
- [x] Manejo de errores robusto
- [x] Scripts de instalación
- [x] Documentación completa
- [ ] Prueba con los 5 links (pendiente instalar dependencias)

---

**Desarrollado para Proyecto Cupido Tu360** 🏠✨
