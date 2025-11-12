@echo off
echo ================================================================================
echo   CONFIGURACION DEL BOT DE WHATSAPP - WINDOWS
echo ================================================================================
echo.

REM Verificar si existe .env
if not exist .env (
    echo ERROR: Archivo .env no encontrado
    echo Por favor verifica que existe el archivo .env con las credenciales
    pause
    exit /b 1
)

echo [OK] Archivo .env encontrado
echo.

REM Activar entorno virtual si existe
if exist venv\Scripts\activate.bat (
    echo Activando entorno virtual...
    call venv\Scripts\activate.bat
) else (
    echo Creando entorno virtual...
    python -m venv venv
    call venv\Scripts\activate.bat
)

echo.
echo ================================================================================
echo   INSTALANDO DEPENDENCIAS
echo ================================================================================
echo.

REM Instalar dependencias
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo ================================================================================
echo   VERIFICANDO INSTALACION
echo ================================================================================
echo.

python -c "import flask, requests, anthropic, psycopg2; print('[OK] Todas las dependencias instaladas correctamente')"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Algunas dependencias no se instalaron correctamente
    pause
    exit /b 1
)

echo.
echo ================================================================================
echo   CONFIGURACION COMPLETADA
echo ================================================================================
echo.
echo El entorno esta listo para usar.
echo.
echo Opciones disponibles:
echo   1. python quick_test.py          - Test rapido de conexion
echo   2. python test_whatsapp.py       - Tests completos
echo   3. python webhook_server.py      - Iniciar servidor webhook
echo.
pause
