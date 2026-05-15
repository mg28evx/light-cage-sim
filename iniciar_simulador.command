#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "======================================================="
    echo "ERROR: Python3 no encontrado."
    echo "Instálalo desde https://www.python.org/ o con: brew install python"
    echo "======================================================="
    read -n 1 -s -r -p "Presiona cualquier tecla para salir..."
    exit 1
fi

if [ ! -f "venv/bin/activate" ]; then
    echo "[1/3] Creando entorno virtual local (esto tomará un momento)..."
    python3 -m venv venv
fi

echo "[2/3] Activando entorno virtual..."
source venv/bin/activate

echo "[3/3] Verificando e instalando librerías necesarias..."
pip install --upgrade pip setuptools wheel --quiet
pip install -r requirements.txt --quiet

echo ""
echo "======================================================="
echo "Todo listo! Iniciando el Simulador Evolux..."
echo "Por favor, NO cierres esta ventana mientras usas la app."
echo "======================================================="
echo ""

# Abrir el navegador nativamente en macOS de forma segura
(sleep 2 && open http://localhost:5001) &

# Iniciar el servidor Flask
python app_sim.py