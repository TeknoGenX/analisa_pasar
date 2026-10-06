# 📈 Tekno-Pasar: Terminal Analisa Pasar Keuangan Multi-Timeframe & Mesin Prediksi Kuantitatif

![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat&logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.1-092E20?style=flat&logo=django&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-Distributed_Tasks-37814A?style=flat&logo=celery&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-Cache_%26_Broker-DC382D?style=flat&logo=redis&logoColor=white)
![Pandas](https://img.shields.io/badge/Pandas-Native_Vectorization-150458?style=flat&logo=pandas&logoColor=white)
![Database](https://img.shields.io/badge/SQLite-WAL_Mode-003B57?style=flat&logo=sqlite&logoColor=white)

**Tekno-Pasar** adalah platform analitik dan terminal kuantitatif pasar finansial mutakhir berbasis **Django**, **Celery**, **Redis**, dan **Native Pandas Vectorization**. Sistem ini dirancang untuk melakukan penggalian data massal (*data ingestion*), kalkulasi indikator teknikal berkecepatan tinggi, penyajian sinyal perdagangan (*trading signals*), serta mesin prediksi arah lilin 1 menit ($t+1$) dan 5 menit ($t+5$) ke depan secara *real-time* untuk berbagai kelas instrumen pasar.

---

## 🌟 Fitur Utama Sistem

- **Cakupan Multi-Pasar Luas (255 Instrumen Aktif)**:
  - 💱 **Forex (20 Pasangan)**: EUR/USD, GBP/USD, USD/JPY, USD/IDR, AUD/USD, USD/CAD, USD/CHF, NZD/USD, EUR/GBP, EUR/JPY, GBP/JPY, dan lainnya.
  - 🪙 **Cryptocurrency (14 Aset)**: Bitcoin (BTC-USD), Ethereum (ETH-USD), Solana (SOL-USD), Binance Coin (BNB-USD), XRP, Cardano, Dogecoin, dan lainnya.
  - 🏢 **Saham AS & Global**: Apple (AAPL), Nvidia (NVDA), Tesla (TSLA), Microsoft (MSFT), Google (GOOGL), Amazon (AMZN), Meta (META), BABA, AMD, dll.
  - 🇮🇩 **Saham IDX Indonesia (200+ Emiten)**: BBCA, BBRI, BMRI, BBNI, TLKM, ASII, UNVR, GOTO, ANTM, AMMN, BREN, BRPT, CPIN, KLBF, ICBP, dan ratusan saham LQ45 & Kompas100.
  - 🛢️ **Komoditas Berjangka (13 Kontrak)**: Emas (GC=F), Minyak Mentah WTI (CL=F), Minyak Brent (BZ=F), Gas Alam (NG=F), Perak (SI=F), Tembaga (HG=F), Jagung (ZC=F), Gandum (KE=F/ZW=F), Kedelai (ZS=F), Kopi (KC=F).

- **Dukungan Kerangka Waktu Lengkap (Multi-Timeframe)**:
  - Mendukung timeframe cepat intraday hingga mingguan: **`1m`**, **`5m`**, **`15m`**, **`30m`**, **`1h`**, **`1d`**, dan **`1wk`**.
  - Database SQLite telah terisi **lebih dari 650.000 candle bar historis** dengan penarikan otomatis inkremental berkinerja tinggi.

- **Mesin Prediksi Kuantitatif Lilin 1 Menit & 5 Menit ke Depan**:
  - **Arah Terbuka**: `NAIK (BULLISH)`, `TURUN (BEARISH)`, atau `KONSOLIDASI (WAIT)`.
  - **Probabilitas Terukur**: Persentase peluang naik vs turun (contoh: *75% Naik | 25% Turun*).
  - **Tingkat Keyakinan**: `TINGGI`, `SEDANG`, atau `RENDAH`.
  - **Multi-Timeframe Confluence**: Filter konfirmasi hirarkis ($M15 \rightarrow M5 \rightarrow M1$).
  - **Proyeksi Target Volatilitas (ATR 14)**: Target Take Profit (TP), Target Stop Loss (SL), dan rekomendasi taktis scalper.

- **Performa Komputasi Super Cepat (Native Vectorization 35x Lipat)**:
  - Indikator teknikal (EMA 9/21, SMA 5/20, Wilder's Smoothing RSI 14, Native Stochastic RSI, MACD, dan Wilder's ATR) dihitung menggunakan **Native Pandas Vectorization**.
  - Memangkas latensi dari **~37 ms menjadi ~1 ms per instrumen** (35x lebih cepat dari pustaka konvensional).
  - Pemuatan instrumen individual hanya membutuhkan **~50 milidetik**, dan seluruh 255 instrumen selesai dikomputasi dalam hitungan detik.

- **Mode Fokus 1 Pasar vs Ringkasan Global Multi-Pasar**:
  - **Mode 1 Pasar**: Tampilan hero prediksi pergerakan, kartu matriks 4 pilar teknikal, estimasi target harga, dan tabel 15 bar lilin terakhir terperinci.
  - **Mode Semua Pasar**: Tabel ikhtisar seluruh instrumen, filter per kategori aset (Forex, Crypto, Stock, Commodity), indikator sentimen global agregat, dan ekspor CSV lengkap.

- **Arsitektur Berkecepatan Tinggi & Tangguh**:
  - Penulisan massal database menggunakan `bulk_create` dengan resolusi konflik (*upsert*) dan pembaruan lilin terakhir secara akurat.
  - Basis data SQLite dioptimalkan dengan mode **WAL (Write-Ahead Logging)** sehingga operasi pembacaan di web server tidak pernah terblokir oleh penulisan Celery di latar belakang.
  - *In-memory Cache* Redis adaptif yang tersinkronisasi otomatis dengan siklus *auto-refresh* peramban dan penarikan data Celery.

---

## 📂 Struktur Direktori Proyek

```plaintext
analisa_pasar/
├── config/                          # Konfigurasi Inti Django & Celery
│   ├── settings.py                  # Pengaturan DB SQLite WAL, Redis Cache, & Celery Beat Cron
│   ├── celery.py                    # Inisialisasi aplikasi Celery
│   ├── urls.py                      # Rute URL utama sistem
│   ├── asgi.py                      # Konfigurasi ASGI
│   └── wsgi.py                      # Konfigurasi WSGI
├── data_ingestion/                  # Modul Penarikan Data Pasar
│   ├── models.py                    # Model MarketInstrument (255 instrumen) & MarketData (650k+ baris)
│   ├── tasks.py                     # Celery shared_task penarikan yfinance incremental upsert
│   ├── admin.py                     # Panel admin untuk manajemen instrumen
│   ├── apps.py                      # Konfigurasi aplikasi
│   └── management/commands/         # Utilitas Command-Line Interface (CLI)
│       ├── seed_instruments.py      # Seeding 255 instrumen pasar multi-kategori
│       ├── fetch_market_data.py     # CLI penarikan data multi-timeframe manual
│       ├── stream_crypto_realtime.py# Streaming data WebSocket Binance real-time
│       ├── stream_forex_mt5.py      # Integrasi feed harga MetaTrader 5 (MT5 API)
│       └── validate_model.py        # Pengujian walk-forward backtesting akurasi model
├── technical_indicators/            # Modul Mesin Indikator & Algoritma Prediksi
│   ├── services.py                  # Mesin komputasi kuantitatif (EMA, RSI, StochRSI, MACD, ATR, Prediksi)
│   ├── models.py                    # Definisi model indikator
│   └── tests.py                     # Unit test indikator teknikal
├── trading_dashboard/               # Antarmuka Terminal Web (UI)
│   ├── views.py                     # View controller, resolusi simbol cerdas, cache adaptif, CSV exporter
│   ├── urls.py                      # Routing antarmuka web (/ & /sync/ & /export-csv/)
│   └── templates/trading_dashboard/
│       └── index.html               # Templat UI Dashboard responsif Bootstrap 5 (Dark Terminal Theme)
├── start.sh                         # Skrip otomasi peluncur seluruh sistem (Django, Celery Worker, Beat)
├── stop.sh                          # Skrip penghenti seluruh proses di latar belakang
├── README.md                        # Dokumentasi ringkas proyek
├── MAKALAH.md                       # Makalah komprehensif presentasi hasil rekayasa sistem dari nol
├── ANALISIS_BUG_DAN_PERBAIKAN.md    # Laporan audit bug menyeluruh dan catatan implementasi solusi
├── PANDUAN_PREDIKSI_1M_5M.md        # Panduan strategi kuantitatif, scalping intraday, dan probabilitas
└── PANDUAN_PENGOPERASIAN_SISTEM.md  # Manual operasional lengkap untuk operator server
```

---

## 🚀 Memulai Cepat (Quick Start)

### 1. Prasyarat Lingkungan
- **Sistem Operasi**: Linux (Parrot OS, Ubuntu, Debian, atau WSL2)
- **Python**: Versi 3.10+ (Direkomendasikan Python 3.13)
- **Redis Server**: Aktif di `localhost:6379` (`sudo service redis-server start`)
- **Virtual Environment**: Terpasang di direktori `./venv`

### 2. Menjalankan Seluruh Sistem (Otomatis)
Cukup jalankan satu skrip otomasi:
```bash
./start.sh
```
Skrip ini akan secara otomatis:
1. Memeriksa dan mengaktifkan virtual environment (`venv`).
2. Menyalakan servis Redis jika belum berjalan.
3. Membuka terminal untuk **Django Server** (`http://127.0.0.1:8000/`).
4. Membuka terminal untuk **Celery Worker** (eksekutor penarikan & komputasi data).
5. Membuka terminal untuk **Celery Beat** (penjadwal cron multi-timeframe).
6. Menampilkan prompt konfirmasi penarikan data instan.

### 3. Menghentikan Seluruh Sistem
Untuk menghentikan seluruh proses:
```bash
./stop.sh
```

---

## ⌨️ Penggunaan Melalui Terminal (CLI)

Anda dapat mengoperasikan sistem langsung dari terminal tanpa peramban:

### A. Penarikan Data Pasar Manual (`fetch_market_data`):
```bash
# Tarik seluruh kerangka waktu sekaligus (1m, 5m, 15m, 30m, 1h, 1d, 1wk)
./venv/bin/python manage.py fetch_market_data --all

# Tarik kerangka waktu tertentu
./venv/bin/python manage.py fetch_market_data --timeframe 1m
./venv/bin/python manage.py fetch_market_data --timeframes 1m,5m,15m
```

### B. Seeding Ulang Instrumen Pasar (`seed_instruments`):
```bash
./venv/bin/python manage.py seed_instruments
```

### C. Validasi Ilmiah & Backtesting Model Prediksi (`validate_model`):
```bash
# Jalankan pengujian walk-forward 300 candle untuk BTC-USD pada timeframe 1m
./venv/bin/python manage.py validate_model --symbol BTC-USD --timeframe 1m --candles 300
```

### D. Streaming Kripto Real-Time via Binance WebSocket (`stream_crypto_realtime`):
```bash
./venv/bin/python manage.py stream_crypto_realtime --symbol BTC-USD
```

---

## ⏰ Jadwal Otomatisasi (Celery Beat Cron)

Celery Beat secara otomatis menarik dan memperbarui data candle ke SQLite dengan jadwal berkala:

| Kerangka Waktu | Interval Pembaruan | Jadwal Cron | Keterangan |
| :---: | :---: | :---: | :--- |
| **`1m`** | Tiap **2 menit** | `*/2 * * * *` | Penarikan data lilin 1 menit tercepat |
| **`5m`** | Tiap **5 menit** | `*/5 * * * *` | Penarikan data lilin 5 menit |
| **`15m`** | Tiap **15 menit** | `*/15 * * * *` | Konfirmasi tren intraday primer |
| **`30m`** | Tiap **30 menit** | `*/30 * * * *` | Tren sesi jangka menengah |
| **`1h`** | Tiap **1 jam** | `0 * * * *` | Tren per jam |
| **`1d`** | Tiap **4 jam** | `0 */4 * * *` | Tren harian (*Swing Trading*) |
| **`1wk`** | Tiap **hari (00:30 WIB)** | `30 0 * * *` | Tren makro mingguan |

---

## 📚 Berkas Dokumentasi & Panduan Resmi

Pelajari dokumen mendalam lainnya yang tersedia dalam repositori ini:

1. 🎓 [**`MAKALAH.md`**](MAKALAH.md):
   **Makalah komprehensif** untuk presentasi hasil kerja rekayasa sistem dari nol sampai beroperasi penuh, mencakup latar belakang, landasan teori, arsitektur perangkat lunak, kronologi pengembangan, hasil uji coba, validasi model, dan analisis data.
2. 🛠️ [**`ANALISIS_BUG_DAN_PERBAIKAN.md`**](ANALISIS_BUG_DAN_PERBAIKAN.md):
   Laporan audit menyeluruh terhadap 12+ bug kritis (termasuk *stale candle bug*, *bottleneck pandas-ta*, *database locking*, *caching alignment*), analisis akar masalah (*root cause*), dan rincian perbaikan teknis.
3. 📊 [**`PANDUAN_PREDIKSI_1M_5M.md`**](PANDUAN_PREDIKSI_1M_5M.md):
   Metodologi ilmiah dan teknikal cara membaca prediksi arah harga 1–5 menit ke depan, prinsip probabilitas, konfluensi multi-timeframe, indikator momentum intraday, dan manajemen risiko ATR.
4. 📖 [**`PANDUAN_PENGOPERASIAN_SISTEM.md`**](PANDUAN_PENGOPERASIAN_SISTEM.md):
   Manual operasional bagi pengguna dan administrator sistem untuk menjalankan, memantau, dan memelihara seluruh layanan di lingkungan Linux.

---

## 🛡️ Lisensi & Catatan Risiko Finansial
Sistem ini dikembangkan untuk tujuan riset kuantitatif, analisis data algoritma, dan edukasi finansial. Seluruh transaksi di pasar finansial mengandung risiko modal; gunakan selalu prinsip manajemen risiko yang ketat dan disiplin.
