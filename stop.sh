#!/bin/bash

# ==============================================================================
# Skrip Otomatisasi Penghentian Mesin Analisa Pasar (Parrot OS)
# Menghentikan: Django Runserver, Celery Worker, Celery Beat, dan Proses Terkait
# ==============================================================================

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$PROJECT_DIR" || exit 1

echo "=================================================================="
echo "  🛑 MENGHENTIKAN SELURUH LAYANAN ANALISA PASAR (PARROT OS)"
echo "=================================================================="

# 1. Hentikan Celery Worker & Beat secara spesifik
echo "[*] Menghentikan proses Celery Worker & Beat..."
pkill -f "celery -A config worker"
pkill -f "celery -A config beat"
pkill -f "celery -A config"

# 2. Hentikan Server Django development (runserver)
echo "[*] Menghentikan Server Django Runserver..."
pkill -f "manage.py runserver"

# 3. Bersihkan sisa proses Python manajemen perintah atau task yang mungkin masih menggantung
echo "[*] Membersihkan proses latar belakang terkait..."
pkill -f "python manage.py"

# 4. Konfirmasi opsional untuk menghentikan layanan Redis (Default: biarkan aktif agar siap pakai)
read -r -p "Apakah Anda juga ingin mematikan layanan Redis Server? (y/n): " stop_redis
if [[ "$stop_redis" =~ ^[Yy]$ ]]; then
    echo "🛑 Menghentikan Redis Server..."
    sudo systemctl stop redis > /dev/null 2>&1 || sudo service redis-server stop > /dev/null 2>&1
    echo "✅ Redis Server dihentikan."
else
    echo "ℹ️ Redis Server dibiarkan tetap aktif di latar belakang."
fi

echo ""
echo "=================================================================="
echo "  ✅ Seluruh layanan utama Analisa Pasar berhasil dihentikan."
echo "     Untuk menyalakan kembali, jalankan: ./start.sh"
echo "=================================================================="
echo ""