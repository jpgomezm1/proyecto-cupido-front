# 📋 PASO A PASO - Ejecutar el Wasi Scraper

Sigue estos pasos en orden para ejecutar el scraper por primera vez.

---

## ✅ PASO 1: Instalar python3-venv

Abre tu terminal y ejecuta:

```bash
sudo apt install python3.12-venv
```

Si te pide contraseña, ingrésala. Este comando instalará las herramientas necesarias para crear entornos virtuales.

**Salida esperada:** Mensajes de instalación y "python3.12-venv instalado"

---

## ✅ PASO 2: Navegar a la carpeta del proyecto

```bash
cd /mnt/c/Users/JuanPablo/Desktop/irrelevant-projects/proyecto-cupido-tu360
```

**Verificar que estás en la carpeta correcta:**
```bash
pwd
```

Deberías ver: `/mnt/c/Users/JuanPablo/Desktop/irrelevant-projects/proyecto-cupido-tu360`

---

## ✅ PASO 3: Crear el entorno virtual

```bash
python3 -m venv venv
```

Esto creará una carpeta llamada `venv` con tu entorno virtual aislado.

**Salida esperada:** El comando termina sin errores (puede tomar 10-20 segundos)

---

## ✅ PASO 4: Activar el entorno virtual

```bash
source venv/bin/activate
```

**Salida esperada:** Tu prompt cambiará y verás `(venv)` al inicio de la línea:

```
(venv) usuario@maquina:~/proyecto-cupido-tu360$
```

---

## ✅ PASO 5: Instalar las dependencias

Con el entorno virtual activado, ejecuta:

```bash
pip install -r requirements.txt
```

Esto instalará todas las librerías necesarias (beautifulsoup4, lxml, tqdm, etc.)

**Salida esperada:** Verás el progreso de descarga e instalación de cada paquete. Tomará 1-2 minutos.

---

## ✅ PASO 6: Verificar que todo está instalado

```bash
python check_dependencies.py
```

**Salida esperada:**
```
============================================================
  VERIFICACIÓN DE DEPENDENCIAS - WASI SCRAPER
============================================================

Verificando módulos de Python...

✓ requests             - INSTALADO
✓ beautifulsoup4       - INSTALADO
✓ pandas               - INSTALADO
✓ lxml                 - INSTALADO
✓ openpyxl             - INSTALADO
✓ tqdm                 - INSTALADO

============================================================
Resumen: 6/6 módulos instalados
============================================================

✅ TODAS LAS DEPENDENCIAS ESTÁN INSTALADAS

¡Puedes ejecutar el scraper con:
  python3 scrapper_wasi.py
```

---

## ✅ PASO 7: Ejecutar el scraper 🚀

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

Scrapeando propiedades: 100%|███████████| 5/5 [00:15<00:00,  3.2s/propiedad]

✓ Scraping completado!
  • Propiedades extraídas: 5
  • Errores: 0

💾 Guardando datos...

✓ CSV guardado: data/propiedades_wasi_20251028_091500.csv
✓ JSON guardado: data/propiedades_wasi_20251028_091500.json
✓ Excel guardado: data/propiedades_wasi_20251028_091500.xlsx

✅ Todos los archivos guardados en: data/

╔════════════════════════════════════════════════════════════╗
║           RESUMEN DE EXTRACCIÓN - WASI SCRAPER            ║
╚════════════════════════════════════════════════════════════╝

📊 Estadísticas Generales:
  • Total propiedades: 5
  • Errores: 0
  • Tasa de éxito: 100.0%

💰 Precios:
  • Precio promedio: $XXX,XXX,XXX COP
  • Precio mínimo: $XXX,XXX,XXX COP
  • Precio máximo: $XXX,XXX,XXX COP

[... más estadísticas ...]

🎉 ¡Proceso completado exitosamente!
```

---

## ✅ PASO 8: Ver los resultados

Los datos extraídos están en la carpeta `data/`:

```bash
ls -lh data/
```

Verás 3 archivos:
- `propiedades_wasi_TIMESTAMP.csv` - Para abrir en Excel/Google Sheets
- `propiedades_wasi_TIMESTAMP.json` - Datos estructurados
- `propiedades_wasi_TIMESTAMP.xlsx` - Excel nativo

**Para ver el CSV en la terminal:**
```bash
head -20 data/propiedades_wasi_*.csv
```

**Para contar propiedades extraídas:**
```bash
wc -l data/propiedades_wasi_*.csv
```

---

## ✅ PASO 9: Desactivar el entorno virtual (cuando termines)

Cuando hayas terminado de trabajar:

```bash
deactivate
```

Tu prompt volverá a la normalidad (sin `(venv)`).

---

## 🔄 Próximas Ejecuciones

Para ejecutar el scraper de nuevo en el futuro:

```bash
# 1. Ir a la carpeta
cd /mnt/c/Users/JuanPablo/Desktop/irrelevant-projects/proyecto-cupido-tu360

# 2. Activar entorno
source venv/bin/activate

# 3. Ejecutar scraper
python scrapper_wasi.py

# 4. Desactivar cuando termines
deactivate
```

---

## 📝 Agregar Más Propiedades

Para scrapear más propiedades, edita el archivo `links_wasi.txt`:

```bash
nano links_wasi.txt
```

Agrega más URLs (una por línea) y guarda. Luego ejecuta el scraper de nuevo.

---

## ❗ Solución de Problemas

### Problema: "python3-venv no encontrado"
```bash
# Intenta con:
sudo apt install python3-venv
```

### Problema: "No module named 'bs4'"
```bash
# Asegúrate de que el entorno virtual esté activado
source venv/bin/activate
# Reinstala dependencias
pip install -r requirements.txt
```

### Problema: "Permission denied al ejecutar setup.sh"
```bash
chmod +x setup.sh
./setup.sh
```

### Problema: El scraper falla en algunas URLs
- Es normal que algunas propiedades fallen
- Revisa el archivo `data/scraper_errors_*.log` para detalles
- Las propiedades exitosas se guardarán de todas formas

---

## 🎯 Resumen Ultra-Rápido

Para los que ya saben:

```bash
# Una sola vez
sudo apt install python3.12-venv
cd /mnt/c/Users/JuanPablo/Desktop/irrelevant-projects/proyecto-cupido-tu360
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Cada vez que quieras ejecutar
source venv/bin/activate
python scrapper_wasi.py
deactivate
```

---

**¡Listo! Ahora tienes todo para extraer datos de propiedades de Wasi** 🎉
