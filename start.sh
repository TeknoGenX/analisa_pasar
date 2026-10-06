#!/bin/bash
# ==============================================================================
# Skrip Otomatisasi Eksekutor Mesin Analisa Pasar
# Menjalankan: Django Runserver, Celery Worker, Celery Beat, dan Penarikan Data
# ==============================================================================

PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$PROJECT_DIR" || exit 1

echo "=================================================================="
echo "  🚀 MEMULAI OTOMASI SISTEM ANALISA PASAR (PARROT OS)"
echo "=================================================================="

# 1. Cek Virtual Environment
if [ ! -f "$PROJECT_DIR/venv/bin/activate" ]; then
    echo "❌ Error: Virtual environment tidak ditemukan di $PROJECT_DIR/venv"
    exit 1
fi

# 2. Cek Status Redis Server
echo "🔍 Memeriksa status Redis Server..."
if ! redis-cli ping > /dev/null 2>&1; then
    echo "⚠️ Redis belum aktif. Mencoba menyalakan Redis service..."
    sudo systemctl start redis > /dev/null 2>&1 || sudo service redis-server start > /dev/null 2>&1 || redis-server --daemonize yes > /dev/null 2>&1
    sleep 1
    if ! redis-cli ping > /dev/null 2>&1; then
        echo "❌ Gagal menghubungkan ke Redis. Silakan jalankan 'sudo service redis-server start' terlebih dahulu."
        exit 1
    fi
fi
echo "✅ Redis Server aktif dan siap."

# 3. Fungsi Peluncur Terminal
launch_terminal() {
    local TITLE="$1"
    local CMD="$2"

    local SCRIPT_CONTENT="cd '$PROJECT_DIR' && source '$PROJECT_DIR/venv/bin/activate' && echo -e '\033[1;32m=====================================================\033[0m' && echo -e '\033[1;36m  $TITLE\033[0m' && echo -e '\033[1;32m=====================================================\033[0m' && $CMD; exec bash"

    if command -v konsole >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
        konsole --separate -p tabtitle="$TITLE" -e bash -c "$SCRIPT_CONTENT" &
    elif command -v mate-terminal >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
        mate-terminal --title="$TITLE" -e "bash -c \"$SCRIPT_CONTENT\"" &
    elif command -v xfce4-terminal >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
        xfce4-terminal --title="$TITLE" -e "bash -c \"$SCRIPT_CONTENT\"" &
    elif command -v gnome-terminal >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
        gnome-terminal --title="$TITLE" -- bash -c "$SCRIPT_CONTENT" &
    elif command -v x-terminal-emulator >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
        x-terminal-emulator -T "$TITLE" -e bash -c "$SCRIPT_CONTENT" &
    elif command -v xterm >/dev/null 2>&1 && [ -n "$DISPLAY" ]; then
        xterm -T "$TITLE" -hold -e bash -c "$SCRIPT_CONTENT" &
    else
        echo "⚠️ Tidak ada GUI terminal emulator ditemukan. Menjalankan di latar belakang (background)..."
        bash -c "source '$PROJECT_DIR/venv/bin/activate' && $CMD" > "$PROJECT_DIR/logs_${TITLE// /_}.log" 2>&1 &
    fi
}

# 4. Buka Terminal 1: Django Runserver
echo "🌐 [1/3] Membuka Terminal Django Server..."
launch_terminal "Terminal 1: Server Django" "python manage.py runserver"
sleep 1

# 5. Buka Terminal 2: Celery Worker
echo "⚙️ [2/3] Membuka Terminal Celery Worker..."
launch_terminal "Terminal 2: Celery Worker" "celery -A config worker -l info"
sleep 2

# 6. Buka Terminal 3: Celery Beat
echo "⏰ [3/3] Membuka Terminal Celery Beat..."
launch_terminal "Terminal 3: Celery Beat" "celery -A config beat -l info"
sleep 2

echo ""
echo "=================================================================="
echo "✅ Seluruh terminal mesin telah berhasil dibuka:"
echo "   1. Server Web: http://127.0.0.1:8000/"
echo "   2. Celery Worker: Siap mengeksekusi penarikan data"
echo "   3. Celery Beat: Menjadwalkan penarikan data berkala tiap jam"
echo "=================================================================="
echo ""

# 7. Kirim Pemicu Penarikan Data Instan Sekarang Juga (1m, 5m, 15m, 30m, 1h, 1d, 1wk)
read -r -p "Apakah Anda ingin memicu penarikan seluruh data pasar sekarang (1m, 5m, 15m, 30m, 1h, 1d, 1wk)? (y/n): " trigger_choice
if [[ "$trigger_choice" =~ ^[Yy]$ ]]; then
    echo "📡 Mengirim sinyal penarikan data lengkap ke Celery Worker..."
    export DJANGO_SETTINGS_MODULE=config.settings
    "$PROJECT_DIR/venv/bin/python" -c "import django; django.setup(); from data_ingestion.tasks import fetch_all_active_timeframes; fetch_all_active_timeframes.delay(['1m', '5m', '15m', '30m', '1h', '1d', '1wk']); print('✅ Sinyal terkirim! Cek Terminal Celery Worker untuk melihat proses pengunduhan.')"
fi

echo ""
echo "💡 Untuk menghentikan semua mesin, jalankan: ./stop.sh"