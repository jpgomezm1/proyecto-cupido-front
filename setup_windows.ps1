# Script de configuración para Windows PowerShell

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  CONFIGURACIÓN DEL BOT DE WHATSAPP - WINDOWS" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Verificar si existe .env
if (-not (Test-Path .env)) {
    Write-Host "ERROR: Archivo .env no encontrado" -ForegroundColor Red
    Write-Host "Por favor verifica que existe el archivo .env con las credenciales" -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "[OK] Archivo .env encontrado" -ForegroundColor Green
Write-Host ""

# Activar o crear entorno virtual
if (Test-Path venv\Scripts\Activate.ps1) {
    Write-Host "Activando entorno virtual..." -ForegroundColor Yellow
    & .\venv\Scripts\Activate.ps1
} else {
    Write-Host "Creando entorno virtual..." -ForegroundColor Yellow
    python -m venv venv
    & .\venv\Scripts\Activate.ps1
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  INSTALANDO DEPENDENCIAS" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Instalar dependencias
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  VERIFICANDO INSTALACIÓN" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Verificar instalación
python -c "import flask, requests, anthropic, psycopg2; print('[OK] Todas las dependencias instaladas correctamente')"

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Algunas dependencias no se instalaron correctamente" -ForegroundColor Red
    pause
    exit 1
}

Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "  CONFIGURACIÓN COMPLETADA" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "El entorno está listo para usar." -ForegroundColor Green
Write-Host ""
Write-Host "Opciones disponibles:" -ForegroundColor Yellow
Write-Host "  1. python quick_test.py          - Test rápido de conexión" -ForegroundColor White
Write-Host "  2. python test_whatsapp.py       - Tests completos" -ForegroundColor White
Write-Host "  3. python webhook_server.py      - Iniciar servidor webhook" -ForegroundColor White
Write-Host ""
