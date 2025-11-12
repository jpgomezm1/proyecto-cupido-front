# 📸 Mejora de Extracción de Imágenes - Scraper Wasi

## 🔍 Problema Identificado

El scraper anterior extraía imágenes, pero eran **miniaturas de baja resolución** (156x117 píxeles).

### Antes:
- ❌ Extraía URLs con `"width":156,"height":117` (miniaturas)
- ❌ Usaba atributo `src` de las etiquetas `<img>`
- ⚠️ Resolución: 156x117px (muy baja para uso profesional)

### Después:
- ✅ Extrae URLs con `"width":979,"height":743` (alta resolución)
- ✅ Usa atributo `href` de las etiquetas `<a>` dentro de `.fotorama`
- ✅ Resolución: 979x743px (alta calidad)

---

## 🎯 Solución Implementada

### Nueva función `_extract_images()` con 3 métodos:

#### **MÉTODO 1: Galería Fotorama (Principal)** ⭐
```python
# Busca en contenedor <div class="fotorama">
# Extrae URLs de ALTA RESOLUCIÓN desde atributo 'href'
fotorama = soup.find('div', class_='fotorama')
for link in fotorama.find_all('a', href=True):
    href = link.get('href')
    if 'image.wasi.co' in href:
        images_hd.append(href)  # ✅ Alta resolución
```

**Ventajas:**
- ✅ Imágenes en alta resolución (979x743px)
- ✅ Todas las imágenes de la galería principal
- ✅ URLs limpias y directas

#### **MÉTODO 2: Contenedor Gallery (Fallback)**
```python
# Si no encuentra fotorama, busca en <div class="Gallery">
gallery = soup.find('div', class_='Gallery')
for link in gallery.find_all('a', href=True):
    # Extrae enlaces de imágenes
```

#### **MÉTODO 3: Búsqueda Global (Último recurso)**
```python
# Busca todas las imágenes de Wasi en la página
all_imgs = soup.find_all('img')
# Filtra por URLs de image.wasi.co
```

---

## 📊 Estructura de URLs de Wasi

Las imágenes de Wasi usan URLs codificadas en Base64:

### URL Miniatura (ANTES):
```
https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIz...
```

Decodificado:
```json
{
  "bucket": "staticw",
  "key": "inmuebles/gr23496152025100810121.jpg",
  "edits": {
    "resize": {"width": 156, "height": 117}  // ❌ Miniatura
  }
}
```

### URL Alta Resolución (AHORA):
```
https://image.wasi.co/eyJidWNrZXQiOiJzdGF0aWN3Iiwia2V5IjoiaW5tdWVibGVzXC9ncjIz...
```

Decodificado:
```json
{
  "bucket": "staticw",
  "key": "inmuebles/gr23496152025100810121.jpg",
  "edits": {
    "resize": {"width": 979, "height": 743}  // ✅ Alta resolución
  }
}
```

**¡La misma imagen, diferente resolución!**

---

## ✅ Nuevas Columnas en CSV

Además de las columnas existentes, ahora se agregan:

| Columna | Descripción |
|---------|-------------|
| `imagenes_urls` | URLs de todas las imágenes en **ALTA RESOLUCIÓN** separadas por ` \| ` |
| `total_imagenes` | Número total de imágenes extraídas |
| `imagen_principal` | URL de la primera imagen (portada) |
| `imagenes_hd_count` | Contador de imágenes en HD (debugging) |
| `imagenes_thumb_count` | Contador de miniaturas encontradas (debugging) |

---

## 🔬 Características de la Mejora

### 1. **Eliminación de Duplicados**
```python
seen = set()
unique_images = []
for img in final_images:
    if img not in seen:
        seen.add(img)
        unique_images.append(img)
```

### 2. **Prioridad HD > Miniaturas**
```python
final_images = images_hd if images_hd else images_thumb
```

### 3. **Logging en Modo Verbose**
```python
self.log(f"Imagen HD encontrada: {href[:80]}...")
```

### 4. **Validación de URLs**
```python
if href and 'image.wasi.co' in href:
    # Solo URLs válidas de Wasi
```

---

## 📈 Resultados Esperados

### Antes de la Mejora:
```csv
total_imagenes,imagen_principal
18,https://image.wasi.co/...width":156...  ❌ Miniatura
```

### Después de la Mejora:
```csv
total_imagenes,imagen_principal,imagenes_hd_count
18,https://image.wasi.co/...width":979...  ✅ Alta Resolución
```

---

## 🚀 Cómo Probar

### 1. Ejecutar el scraper mejorado:
```bash
source venv/bin/activate
python scrapper_wasi.py
```

### 2. Verificar las imágenes en el CSV:
```bash
# Ver columnas de imágenes
python3 -c "import pandas as pd; df = pd.read_csv('data/propiedades_wasi_*.csv'); print(df[['total_imagenes', 'imagenes_hd_count', 'imagenes_thumb_count']].head())"
```

### 3. Copiar una URL y abrirla en el navegador:
```bash
# Extraer primera imagen de la primera propiedad
python3 -c "import pandas as pd; df = pd.read_csv('data/propiedades_wasi_*.csv'); print(df['imagen_principal'].iloc[0])"
```

Pega esa URL en el navegador y verás la **imagen en alta resolución** 🎉

---

## 🔧 Activar Modo Verbose (Opcional)

Para ver en tiempo real qué imágenes HD se están extrayendo:

```python
# En scrapper_wasi.py, línea ~510
VERBOSE = True  # Cambiar de False a True
```

Salida en consola:
```
[LOG] Obteniendo página: https://info.wasi.co/...
[LOG] Imagen HD encontrada: https://image.wasi.co/eyJidWNrZXQiOi...
[LOG] Imagen HD encontrada: https://image.wasi.co/eyJidWNrZXQiOi...
...
```

---

## 📸 Ejemplo Comparativo

### Miniatura (156x117px):
```
https://image.wasi.co/eyJ...ImhlaWdodCI6MTE3...
```

### Alta Resolución (979x743px):
```
https://image.wasi.co/eyJ...ImhlaWdodCI6NzQz...
```

**La diferencia está en los parámetros de resolución dentro de la URL codificada.**

---

## ✅ Ventajas de Esta Implementación

1. ✅ **Extrae TODAS las imágenes** de la galería
2. ✅ **Alta resolución** (979x743px vs 156x117px)
3. ✅ **Sin duplicados**
4. ✅ **3 métodos de extracción** (fallback robusto)
5. ✅ **Debugging** con contadores HD vs miniaturas
6. ✅ **Ordenadas** en el mismo orden que aparecen en la galería

---

## 🎯 Resumen

| Aspecto | Antes | Después |
|---------|-------|---------|
| Resolución | 156x117px ❌ | 979x743px ✅ |
| Fuente | `<img src>` | `<a href>` ✅ |
| Calidad | Miniatura | Alta resolución ✅ |
| Duplicados | Posibles | Eliminados ✅ |
| Debugging | No | Contadores HD/thumb ✅ |

---

**¡Ahora el scraper extrae TODAS las imágenes en la mejor calidad disponible!** 📸✨
