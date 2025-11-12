# 🚀 Quick Start - Wasi Scraper

## Instalación en 3 Pasos

### 1️⃣ Instalar python3-venv
```bash
sudo apt install python3.12-venv
```

### 2️⃣ Crear y activar entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3️⃣ Ejecutar el scraper
```bash
python scrapper_wasi.py
```

## 📊 Resultado

Los datos se guardarán en la carpeta `data/` en 3 formatos:
- CSV (para Excel)
- JSON (datos estructurados)
- XLSX (Excel nativo)

## ✅ Verificar antes de ejecutar

```bash
python3 check_dependencies.py
```

## 📝 Agregar más propiedades

Edita `links_wasi.txt` y agrega más URLs:
```
https://info.wasi.co/apartamento-venta-ciudad-barrio/12345
https://info.wasi.co/casa-venta-ciudad-barrio/67890
```

## 🎯 Datos Extraídos

Cada propiedad incluye:
- ✓ Información básica (título, precio, código)
- ✓ Ubicación completa + GPS
- ✓ Características (área, habitaciones, baños, parqueaderos)
- ✓ Costos adicionales (administración, predial)
- ✓ Amenidades internas y externas
- ✓ Contacto (asesor, teléfono)
- ✓ URLs de todas las imágenes
- ✓ Descripción completa

**Total: Más de 35 campos por propiedad**

---

**¿Problemas?** Consulta `INSTRUCCIONES.md` o `README_SCRAPER.md`
