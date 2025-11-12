# 📋 Instrucciones para Carga Inicial de Propiedades

## 🎯 Resumen

Este documento explica cómo limpiar la base de datos y cargar las 30 propiedades de Wasi desde el archivo `Carga Inicial Wasi.txt`.

---

## 📦 Requisitos Previos

1. Tener el entorno virtual de Python activado
2. Tener acceso a la base de datos Neon (variable `DATABASE_URL` en `.env`)
3. Tener el archivo `carga_inicial/Carga Inicial Wasi.txt` con las URLs

---

## 🚀 Opción 1: Proceso Completo Automático (RECOMENDADO)

Este comando hace **TODO**:
1. ✅ Limpia la base de datos (con confirmación)
2. ✅ Lee las URLs del archivo .txt
3. ✅ Scrapea cada propiedad de Wasi
4. ✅ Guarda cada propiedad en la BD
5. ✅ Muestra un resumen final

### Comando:

```bash
python3 cargar_propiedades_wasi.py
```

### ¿Qué va a pasar?

1. **Paso 1 - Limpieza de BD:**
   ```
   ⚠️  Se encontraron 149 propiedades en la base de datos.
   ¿Estás seguro de que quieres ELIMINAR TODAS las propiedades? (escribe 'SI' para confirmar):
   ```
   - Escribe `SI` (en mayúsculas) y presiona Enter
   - Escribe cualquier otra cosa para cancelar

2. **Paso 2 - Lectura de URLs:**
   ```
   ✅ Se encontraron 30 URLs únicas en el archivo
   ```

3. **Paso 3 - Scraping y Carga:**
   ```
   [1/30] Procesando: https://info.wasi.co/apartamento-venta-poblado-medellín/9555780
   [LOG] Obteniendo página...
   ✓ Datos extraídos exitosamente
   ✅ Propiedad guardada exitosamente (1/30)
   ⏳ Esperando 3 segundos...
   ```

4. **Paso 4 - Resumen Final:**
   ```
   ✅ Propiedades cargadas exitosamente: 28
   ❌ Propiedades fallidas: 2
   📊 Total procesado: 30
   ✅ Tasa de éxito: 93.3%
   ```

### ⏱️ Tiempo Estimado:
- **~2-3 minutos** (3 segundos de delay entre cada propiedad + tiempo de scraping)

---

## 🔧 Opción 2: Proceso Manual (Paso a Paso)

Si prefieres tener más control, puedes ejecutar cada paso por separado:

### Paso 1: Solo Limpiar la Base de Datos

```bash
python3 limpiar_bd.py
```

Este script:
- Muestra cuántas propiedades hay actualmente
- Pide confirmación (escribir `SI`)
- Elimina todas las propiedades
- Muestra el resultado

### Paso 2: Solo Cargar Propiedades (sin limpiar)

Si ya limpiaste manualmente y solo quieres cargar:

```bash
python3 cargar_propiedades_wasi.py
```

Cuando te pregunte si quieres limpiar, escribe `NO` y solo hará la carga.

---

## 📊 Verificar la Carga

Después de ejecutar el script, verifica que las propiedades se cargaron correctamente:

### Opción A: Desde Python

```bash
python3 -c "from database import DatabaseManager; db = DatabaseManager(); db.connect(); db.cursor.execute('SELECT COUNT(*) FROM propiedades'); print(f'Propiedades en BD: {db.cursor.fetchone()[0]}'); db.disconnect()"
```

### Opción B: Desde la API

```bash
curl http://localhost:5000/api/health
```

Deberías ver:
```json
{
  "success": true,
  "status": "healthy",
  "database": "connected",
  "properties_count": 30
}
```

### Opción C: Desde el Frontend

1. Abre el navegador en `http://localhost:8080`
2. Deberías ver "30 inmuebles encontrados"
3. Las propiedades deben aparecer en el catálogo

---

## ⚠️ Solución de Problemas

### Error: "No se encontró el archivo Carga Inicial Wasi.txt"

**Solución:** Verifica que el archivo existe:
```bash
ls -la carga_inicial/
```

### Error: "No module named 'beautifulsoup4'"

**Solución:** Instala las dependencias:
```bash
pip install beautifulsoup4 lxml requests tqdm pandas
```

### Error: "Connection refused" o "Database error"

**Solución:** Verifica que tu `.env` tiene la variable `DATABASE_URL` correcta:
```bash
cat .env | grep DATABASE_URL
```

### Error: "503 Service Unavailable" de Wasi

**Solución:** Wasi puede estar bloqueando temporalmente. Opciones:
1. Espera unos minutos y vuelve a intentar
2. Aumenta el delay en el scraper (edita `cargar_propiedades_wasi.py` línea 147, cambia `delay=3` a `delay=5`)

### Algunas propiedades fallan

**Esto es normal.** Algunas URLs pueden:
- Ser propiedades ya eliminadas de Wasi
- Tener formato HTML diferente
- Estar temporalmente no disponibles

Si la tasa de éxito es >85%, está bien. Las propiedades que fallaron simplemente no se cargarán.

---

## 🔄 Re-ejecutar la Carga

Si algo salió mal y quieres volver a cargar:

1. **Limpia de nuevo:**
   ```bash
   python3 limpiar_bd.py
   ```

2. **Carga de nuevo:**
   ```bash
   python3 cargar_propiedades_wasi.py
   ```
   (Escribe `NO` cuando pregunte si quieres limpiar, ya que ya limpiaste en el paso 1)

---

## 📝 Notas Importantes

1. **Delay entre requests:** El script espera 3 segundos entre cada propiedad para no sobrecargar el servidor de Wasi. **NO reduzcas este tiempo** o podrían bloquear tu IP.

2. **URLs duplicadas:** El script detecta y elimina URLs duplicadas automáticamente (vi que la URL 15 y 16 son iguales, y 22 y 23 también).

3. **Códigos de propiedad:** Se extrae automáticamente de la URL de Wasi (el número al final).

4. **Fuente:** Todas las propiedades se marcarán con `fuente='Wasi'` en la base de datos.

5. **Estado activa:** Todas las propiedades se cargan con `activa=TRUE`, por lo que aparecerán inmediatamente en el frontend.

---

## 🎯 Comandos Rápidos (Cheat Sheet)

```bash
# Todo en uno (limpiar + cargar)
python3 cargar_propiedades_wasi.py

# Solo limpiar BD
python3 limpiar_bd.py

# Ver cuántas propiedades hay
python3 -c "from database import DatabaseManager; db = DatabaseManager(); db.connect(); db.cursor.execute('SELECT COUNT(*) FROM propiedades'); print(f'Total: {db.cursor.fetchone()[0]}'); db.disconnect()"

# Ver propiedades por fuente
python3 -c "from database import DatabaseManager; db = DatabaseManager(); db.connect(); db.cursor.execute('SELECT fuente, COUNT(*) FROM propiedades GROUP BY fuente'); print(db.cursor.fetchall()); db.disconnect()"
```

---

## ✅ ¿Listo para empezar?

Ejecuta:
```bash
python3 cargar_propiedades_wasi.py
```

Y sigue las instrucciones en pantalla. 🚀
