#!/bin/bash
# Script de configuración para el Wasi Scraper

echo "=================================="
echo "   WASI SCRAPER - SETUP"
echo "=================================="
echo ""

# Verificar Python
echo "1. Verificando Python..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "   ✓ $PYTHON_VERSION encontrado"
else
    echo "   ✗ Python3 no encontrado. Por favor instálalo."
    exit 1
fi

echo ""

# Verificar pip
echo "2. Verificando pip..."
if command -v pip3 &> /dev/null; then
    PIP_VERSION=$(pip3 --version)
    echo "   ✓ pip encontrado"
else
    echo "   ✗ pip no encontrado. Instalando..."
    sudo apt install python3-pip -y
fi

echo ""

# Opción de instalación
echo "3. Selecciona método de instalación:"
echo "   a) Entorno virtual (Recomendado)"
echo "   b) Instalación con --user"
echo "   c) Salir"
echo ""
read -p "Selecciona una opción (a/b/c): " option

case $option in
    a)
        echo ""
        echo "Instalando python3-venv si es necesario..."
        sudo apt install python3.12-venv -y 2>/dev/null || sudo apt install python3-venv -y

        echo "Creando entorno virtual..."
        python3 -m venv venv

        echo "Activando entorno virtual..."
        source venv/bin/activate

        echo "Instalando dependencias..."
        pip install -r requirements.txt

        echo ""
        echo "✅ Instalación completada!"
        echo ""
        echo "Para ejecutar el scraper:"
        echo "  1. source venv/bin/activate"
        echo "  2. python scrapper_wasi.py"
        echo "  3. deactivate (cuando termines)"
        ;;
    b)
        echo ""
        echo "Instalando dependencias con --user..."
        pip3 install --user -r requirements.txt

        echo ""
        echo "✅ Instalación completada!"
        echo ""
        echo "Para ejecutar el scraper:"
        echo "  python3 scrapper_wasi.py"
        ;;
    c)
        echo "Saliendo..."
        exit 0
        ;;
    *)
        echo "Opción inválida"
        exit 1
        ;;
esac

echo ""
echo "=================================="
echo "   ¡LISTO PARA USAR!"
echo "=================================="
