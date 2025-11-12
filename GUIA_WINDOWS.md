# 🪟 Guía de Instalación - Windows

## 📋 Pasos para configurar en Windows

### Método 1: Script automático (Recomendado)

#### Opción A: PowerShell

1. Abre PowerShell en la carpeta del proyecto
2. Ejecuta:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup_windows.ps1
```

#### Opción B: Command Prompt (CMD)

1. Abre CMD en la carpeta del proyecto
2. Ejecuta:
```cmd
setup_windows.bat
```

### Método 2: Manual (paso a paso)

#### 1. Activar entorno virtual

```powershell
# Si ya existe venv
.\venv\Scripts\Activate.ps1

# Si no existe, créalo primero
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Nota:** Si tienes error de ejecución de scripts en PowerShell:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

#### 2. Actualizar pip

```powershell
python -m pip install --upgrade pip
```

#### 3. Instalar dependencias

```powershell
pip install -r requirements.txt
```

Si da error, instala manualmente:
```powershell
pip install flask
pip install requests
pip install python-dotenv
pip install anthropic
pip install psycopg2-binary
pip install beautifulsoup4
pip install pandas
```

#### 4. Verificar instalación

```powershell
python -c "import flask, requests, anthropic, psycopg2; print('OK - Todo instalado')"
```

Si ves "OK - Todo instalado", ¡estás listo!

### 🧪 Probar el bot

#### Test rápido:

```powershell
python quick_test.py
```

Cuando pregunte si quieres enviar mensaje, escribe `s` y luego tu número: `+573001234567`

#### Test completo:

```powershell
python test_whatsapp.py
```

#### Iniciar servidor:

```powershell
python webhook_server.py
```

## 🐛 Solución de problemas comunes

### Error: "python no se reconoce"

Instala Python desde: https://www.python.org/downloads/

**Importante:** Marca la opción "Add Python to PATH" durante la instalación.

### Error: "No se puede ejecutar scripts"

En PowerShell:
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### Error: "Module not found: dotenv"

```powershell
pip install python-dotenv
```

### Error: "pip no se reconoce"

```powershell
python -m pip install python-dotenv
```

### El venv no activa correctamente

Usa el path completo:
```powershell
.\venv\Scripts\Activate.ps1
```

O en CMD:
```cmd
venv\Scripts\activate.bat
```

### Error de SSL al instalar

```powershell
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
```

## 📱 Usar el bot desde Windows

### 1. Test rápido (enviar mensaje)

```powershell
python quick_test.py
```

### 2. Iniciar servidor webhook

Terminal 1:
```powershell
python webhook_server.py
```

Terminal 2 (exponer con ngrok):
```powershell
# Descargar ngrok: https://ngrok.com/download
ngrok http 5000
```

Copia la URL que da ngrok (ej: `https://abc123.ngrok.io`)

### 3. Configurar webhook en UltraMSG

1. Ve a: https://user.ultramsg.com/
2. Settings → Webhooks
3. Webhook URL: `https://abc123.ngrok.io/webhook`
4. Activa "Incoming messages"
5. Guarda

### 4. ¡Probar!

Envía un mensaje de WhatsApp al número conectado:
```
Busco apto en Laureles, 2 habitaciones, hasta 500 millones
```

## 🔧 Comandos útiles de Windows

### Ver si el servidor está corriendo:

```powershell
netstat -ano | findstr :5000
```

### Matar proceso en puerto 5000:

```powershell
# Ver el PID
netstat -ano | findstr :5000
# Matar el proceso (reemplaza PID con el número)
taskkill /PID <PID> /F
```

### Ver archivos de logs:

```powershell
Get-ChildItem webhook_logs | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-Content
```

## 📝 Atajos de teclado

- `Ctrl + C` - Detener servidor
- `Ctrl + Z` - Pausar (no recomendado, usa Ctrl+C)

## ✅ Checklist de instalación

- [ ] Python instalado (verificar con `python --version`)
- [ ] Entorno virtual creado (`python -m venv venv`)
- [ ] Entorno virtual activado (ver `(venv)` en el prompt)
- [ ] Dependencias instaladas (`pip install -r requirements.txt`)
- [ ] Verificación exitosa (importar módulos sin error)
- [ ] `.env` existe con credenciales
- [ ] Test rápido ejecutado (`python quick_test.py`)

## 🎯 Inicio rápido (resumen)

```powershell
# 1. Activar venv
.\venv\Scripts\Activate.ps1

# 2. Instalar dependencias (solo primera vez)
pip install -r requirements.txt

# 3. Probar
python quick_test.py
```

## 💡 Tips para Windows

1. **Usa PowerShell o Windows Terminal** (mejor que CMD clásico)
2. **Instala Windows Terminal** desde Microsoft Store (opcional pero recomendado)
3. **Mantén Python actualizado** (última versión de python.org)
4. **Usa ngrok para testing** (más fácil que configurar puerto forwarding)

## 🚀 Siguiente paso

Una vez instalado todo:

```powershell
python quick_test.py
```

Escribe `s` cuando pregunte, ingresa tu número, y recibirás un mensaje de prueba!

**¡Ya estás listo para usar el bot desde Windows! 🎉**
