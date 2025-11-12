# Instrucciones de Uso - Wasi Scraper

## 📋 Requisitos Previos

### Opción 1: Usando entorno virtual (Recomendado)
```bash
# 1. Instalar python3-venv si no lo tienes
sudo apt install python3.12-venv

# 2. Crear entorno virtual
python3 -m venv venv

# 3. Activar entorno virtual
source venv/bin/activate  # En Linux/Mac
# o
venv\Scripts\activate  # En Windows

# 4. Instalar dependencias
pip install -r requirements.txt
```

### Opción 2: Instalación global (No recomendado)
```bash
pip install --user -r requirements.txt
```

## 🚀 Cómo Ejecutar el Scraper

### Ejecución básica
```bash
python3 scrapper_wasi.py
```

### Ejecución con entorno virtual activado
```bash
source venv/bin/activate  # Activar entorno
python scrapper_wasi.py   # Ejecutar scraper
deactivate                # Desactivar entorno al terminar
```

## 📁 Archivos Generados

El scraper generará los siguientes archivos en la carpeta `data/`:

- `propiedades_wasi_TIMESTAMP.csv` - Datos en formato CSV (Excel compatible)
- `propiedades_wasi_TIMESTAMP.json` - Datos en formato JSON
- `propiedades_wasi_TIMESTAMP.xlsx` - Datos en formato Excel
- `scraper_errors_TIMESTAMP.log` - Log de errores (si los hay)

## 🎯 Funcionalidades Principales

El scraper extrae la siguiente información de cada propiedad:

### Información Básica
- Título de la propiedad
- Precio (valor numérico y texto)
- Código de propiedad
- Tipo de propiedad (Apartamento, Casa, Lote, etc.)
- Estado (Disponible, Vendida, etc.)

### Ubicación
- País, Departamento, Ciudad, Zona
- Coordenadas GPS (latitud y longitud)
- Dirección completa

### Características Físicas
- Área construida (m²)
- Número de habitaciones
- Número de baños
- Número de parqueaderos
- Estrato
- Piso
- Año de construcción

### Costos Adicionales
- Valor de administración
- Valor del predial

### Amenidades
- Amenidades internas (balcón, cocina integral, etc.)
- Amenidades externas (ascensor, vigilancia, etc.)
- Total de amenidades

### Contacto
- Nombre del asesor
- Teléfono de contacto
- Inmobiliaria

### Multimedia
- URLs de todas las imágenes
- Total de imágenes
- URL de imagen principal

### Descripción
- Descripción completa de la propiedad
- Longitud de la descripción

## ⚙️ Configuración

Puedes modificar estos parámetros en `scrapper_wasi.py` (función `main()`):

```python
INPUT_FILE = 'links_wasi.txt'  # Archivo con URLs
OUTPUT_DIR = 'data'            # Carpeta de salida
DELAY = 2                      # Segundos entre requests (evita bloqueos)
VERBOSE = True                 # Modo detallado (True/False)
```

## 📝 Agregar Más Links

Simplemente edita el archivo `links_wasi.txt` y agrega más URLs (una por línea):

```
https://info.wasi.co/apartamento-venta-ciudad-barrio/12345
https://info.wasi.co/casa-venta-ciudad-barrio/67890
...
```

## 🔧 Solución de Problemas

### Error: Module not found
```bash
# Asegúrate de tener las dependencias instaladas
pip install -r requirements.txt
```

### Error: Permission denied
```bash
# Usa --user para instalar localmente
pip install --user -r requirements.txt
```

### Error: SSL Certificate
```bash
# Si hay problemas con certificados SSL
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

### El scraper es bloqueado
- Aumenta el valor de `DELAY` en el código (ej: 5 segundos)
- Reduce la cantidad de URLs a procesar simultáneamente

## 📊 Análisis de Datos

Una vez extraídos, puedes analizar los datos:

### Con Python/Pandas
```python
import pandas as pd

df = pd.read_csv('data/propiedades_wasi_TIMESTAMP.csv')
print(df.describe())
print(df['precio'].mean())
```

### Con Excel
Abre el archivo `.xlsx` o `.csv` directamente en Excel o Google Sheets

## 🆘 Soporte

Si encuentras errores:
1. Revisa el archivo `scraper_errors_TIMESTAMP.log` en la carpeta `data/`
2. Verifica que las URLs en `links_wasi.txt` sean válidas
3. Comprueba tu conexión a internet
