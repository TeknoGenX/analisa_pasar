# 🚀 Panduan Pengoperasian Sistem Analisa Pasar & Terminal Kuantitatif

Dokumen ini merupakan panduan praktis bagi operator dan administrator untuk menjalankan, memantau, menguji, dan memelihara seluruh komponen sistem **Terminal Analisa Pasar Keuangan & Mesin Prediksi Kuantitatif** di lingkungan Linux (Parrot OS / Ubuntu / Debian / WSL2).

---

## 🏗️ Komponen Arsitektur Sistem

Sistem ini terdiri dari 4 lapisan arsitektur yang saling terintegrasi secara asinkron:

1. **Django Web Server (`runserver`)**: 
   * Menyajikan dasbor web interaktif di `http://127.0.0.1:8000/`.
   * Menampilkan visualisasi prediksi 1 menit, kartu 4 pilar teknikal, estimasi volatilitas ATR, tabel 15 bar lilin terakhir, filter kategori, dan ekspor CSV.
2. **Redis In-Memory Server**: 
   * Port default: `6379`.
   * Berperan ganda sebagai *message broker* untuk antrean Celery dan *in-memory cache* untuk hasil komputasi Pandas.
3. **Celery Worker**: 
   * Mengeksekusi penarikan data massal dari Yahoo Finance di latar belakang tanpa memblokir server web.
   * Melakukan pembaruan data lilin inkremental (*upsert*) dan pembersihan cache otomatis.
4. **Celery Beat**: 
   * Penjadwal cron berkala otomatis untuk seluruh kerangka waktu (`1m`, `5m`, `15m`, `30m`, `1h`, `1d`, `1wk`).

---

## ⚡ 1. Menjalankan Seluruh Sistem (Otomatis)

Gunakan skrip otomasi yang telah disediakan:

```bash
./start.sh
```

### Rangkaian Eksekusi Skrip:
1. Memverifikasi ketersediaan direktori `venv/` dan mengaktifkannya.
2. Memeriksa status servis **Redis Server**. Jika belum aktif, skrip akan menyalakannya secara otomatis.
3. Membuka jendela terminal independen untuk **Django Server** (`http://127.0.0.1:8000/`).
4. Membuka jendela terminal independen untuk **Celery Worker**.
5. Membuka jendela terminal independen untuk **Celery Beat** (penjadwal berkala).
6. Menampilkan prompt opsi jika Anda ingin langsung memicu penarikan seluruh data pasar (1m hingga 1wk).

---

## 🛑 2. Menghentikan Seluruh Sistem

Untuk mematikan seluruh proses Django, Celery Worker, dan Celery Beat secara aman:

```bash
./stop.sh
```

Skrip ini akan mematikan proses Python terkait dan membersihkan file antrean sementara secara rapi.

---

## ⌨️ 3. Perintah Command-Line Interface (CLI)

Seluruh perintah CLI dieksekusi menggunakan interpreter virtual environment:

### A. Penarikan Data Pasar Manual (`fetch_market_data`)
```bash
# Tarik seluruh kerangka waktu sekaligus (1m, 5m, 15m, 30m, 1h, 1d, 1wk)
./venv/bin/python manage.py fetch_market_data --all

# Tarik kerangka waktu spesifik
./venv/bin/python manage.py fetch_market_data --timeframe 1m
./venv/bin/python manage.py fetch_market_data --timeframe 5m
./venv/bin/python manage.py fetch_market_data --timeframes 1m,5m,15m
```

### B. Seeding Daftar Instrumen Pasar (`seed_instruments`)
Mengisi atau memperbarui daftar 255 instrumen pasar (Forex, Crypto, Saham IDX & US, Komoditas):
```bash
./venv/bin/python manage.py seed_instruments
```

### C. Validasi Model & Backtesting Walk-Forward (`validate_model`)
Menguji akurasi model prediksi pada data candle historis:
```bash
# Uji 300 candle terakhir BTC-USD pada timeframe 1 menit dengan ambang batas probabilitas 65%
./venv/bin/python manage.py validate_model --symbol BTC-USD --timeframe 1m --candles 300 --min-conf 65

# Uji EUR/USD pada timeframe 5 menit
./venv/bin/python manage.py validate_model --symbol EURUSD=X --timeframe 5m --candles 500
```

### D. Streaming Kripto Real-Time via Binance WebSocket (`stream_crypto_realtime`)
Menerima candle 1m real-time dengan latensi < 50ms langsung dari feed Binance:
```bash
./venv/bin/python manage.py stream_crypto_realtime --symbol BTC-USD
```

### E. Integrasi MetaTrader 5 API (`stream_forex_mt5`)
Menghubungkan terminal ke feed broker Forex MetaTrader 5:
```bash
./venv/bin/python manage.py stream_forex_mt5 --symbol EURUSD
```

---

## 🌐 4. Panduan Penggunaan Antarmuka Web (Dashboard)

Akses dasbor melalui peramban: `http://127.0.0.1:8000/`

### A. Fitur Pemilihan 1 Pasar Tunggal (Mode Fokus)
1. Pada bagian navigasi atas, gunakan dropdown **"🎯 Pilih 1 Pasar"** atau ketik URL langsung:
   * Bitcoin: `http://127.0.0.1:8000/?symbol=BTC-USD&tf=1m`
   * Euro / USD: `http://127.0.0.1:8000/?symbol=EURUSD&tf=1m`
   * Bank Central Asia: `http://127.0.0.1:8000/?symbol=BBCA&tf=1d`
   * Emas Antam / Gold: `http://127.0.0.1:8000/?symbol=GC=F&tf=5m`
2. **Hero Card**: Menampilkan arah lilin ($t+1$), tingkat keyakinan (*Tinggi/Sedang*), dan bar probabilitas (*% Peluang Naik vs Turun*).
3. **Pilar Indikator**: Menampilkan status EMA 9/21, RSI 14, StochRSI, MACD, dan Confluence M15/M5.
4. **Target Volatilitas ATR**: Rekomendasi level Stop Loss dan Take Profit berbasis rentang volatilitas riil.
5. **Tombol "⚡ Tarik Data (1s)"**: Melakukan penarikan instan khusus 1 instrumen tersebut langsung ke Yahoo Finance tanpa menunggu antrean massal.

### B. Fitur Ringkasan Multi-Pasar (Global Overview)
1. Pilih opsi **"🌍 Semua Pasar"** pada dropdown atau klik tautan di header.
2. Gunakan tab kategori untuk memfilter: **💱 Forex**, **🪙 Crypto**, **📈 Saham**, atau **🛢️ Komoditas**.
3. **Auto-Refresh**: Switch toggle di kanan atas akan otomatis menyegarkan data setiap 20 detik (untuk 1m) atau 60 detik (untuk 5m) secara mulus memanfaatkan Redis Cache.
4. **Unduh CSV**: Klik tombol hijau **"📥 Unduh CSV"** untuk mengekspor seluruh hasil kalkulasi teknikal dan sinyal prediksi ke berkas spreadsheet `.csv`.

---

## 🔍 5. Pemeliharaan, Monitoring, & Troubleshooting

### A. Menjalankan Unit Tests Sistem:
```bash
./venv/bin/python manage.py test
```
*Pastikan seluruh 11 unit test menghasilkan status `OK`.*

### B. Memeriksa Jumlah Data di SQLite:
```bash
./venv/bin/python manage.py shell -c "
from data_ingestion.models import MarketData
print('Total Candle di Database:', MarketData.objects.count())
"
```

### C. Memuat Ulang (Reload) Celery Worker Pasca-Perubahan Kode:
Jika kode task diperbarui tanpa me-restart terminal:
```bash
pkill -HUP -f "celery -A config worker"
```

### D. Mengatasi SQLite Locked (Pencegahan Mode WAL):
Jika terjadi error database locked, pastikan mode WAL tetap aktif:
```bash
sqlite3 db.sqlite3 "PRAGMA journal_mode=WAL;"
```
Mode WAL memungkinkan ribuan baris data ditulis oleh Celery Worker tanpa pernah memblokir query pembacaan dashboard web.
