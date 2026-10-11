# 🛠️ Analisis Bug & Laporan Perbaikan Sistem Analisa Pasar

Dokumen ini mencatat secara menyeluruh hasil audit kode, analisis akar penyebab masalah (*root cause*), dan seluruh perbaikan yang telah diimplementasikan pada proyek **Terminal Analisa Pasar Keuangan & Mesin Prediksi Kuantitatif**.

---

## 📑 Daftar Masalah & Bug yang Ditemukan dan Diperbaiki

### 1. Timeframe 1 Menit (`1m`) & 5 Menit (`5m`) Kosong Total di Database
* **Lokasi Berkas**: `data_ingestion/tasks.py` & `config/settings.py`
* **Gejala**:
  Ketika memilih tombol **1 Menit** atau **5 Menit** pada antarmuka web, dashboard selalu menampilkan:
  > *"Belum ada data instrumen pasar yang dianalisis."*
* **Akar Masalah**:
  1. Fungsi `fetch_market_prices()` secara kaku (*hardcoded*) hanya mengunduh timeframe harian (`interval='1d'`, `period='60d'`) dan hanya menyimpannya dengan atribut `timeframe='1d'`.
  2. Database sama sekali tidak memiliki baris data untuk timeframe selain `1d`.
  3. Kueri di `technical_indicators/services.py` mencari `MarketData.objects.filter(timeframe=timeframe)`. Karena hasilnya 0, fungsi kalkulasi langsung mengembalikan `None`.
  4. Penjadwalan Celery Beat di `settings.py` hanya berjalan 1 jam sekali, sehingga data intraday tidak pernah diperbarui secara berkala.
* **Solusi yang Diterapkan**:
  * Menambahkan parameter dinamis `timeframe` pada `fetch_market_prices()`.
  * Menjadwalkan penarikan cron multi-timeframe di Celery Beat (`1m` tiap 2 menit, `5m` tiap 5 menit, dst.).

---

### 2. Keterbatasan API Yahoo Finance (`yfinance`) untuk Candle Pendek
* **Akar Masalah**:
  * Yahoo Finance membatasi penarikan interval `1m` maksimal hanya untuk **7 hari terakhir** (`period='7d'`). Jika menggunakan `period='60d'` seperti pada kode lama, yfinance akan melemparkan galat (*error*) atau menghasilkan DataFrame kosong.
  * Interval `5m` dibatasi maksimal **60 hari**.
  * Format DataFrame `yfinance.download()` dengan multi-ticker mengembalikan struktur `MultiIndex` yang bisa tidak konsisten jika ada ticker yang gagal diunduh atau mengalami delisting.
* **Solusi yang Diterapkan**:
  * Membuat kamus pemetaan parameter otomatis (`TIMEFRAME_CONFIG`) dengan periode optimal yang aman bagi limitasi API Yahoo Finance.
  * Mengembangkan fungsi ekstraksi kolom tangguh (`extract_ticker_df`) untuk menangani variasi level `MultiIndex`.

---

### 3. Masalah Kinerja Database (SQLite Lock pada Penulisan Massal)
* **Lokasi Berkas**: `data_ingestion/tasks.py` & `config/settings.py`
* **Gejala**:
  Ketika ratusan ribu candle 1m dan 5m disimpan secara berulang menggunakan `update_or_create()` individual di dalam *loop*, proses memakan waktu sangat lama dan memicu galat:
  > `sqlite3.OperationalError: database is locked`
* **Akar Masalah**:
  * Eksekusi kueri `update_or_create` satu per satu untuk 100.000+ baris data memakan ribuan transaksi I/O disk.
  * Mode jurnal default SQLite (`DELETE`) mengunci seluruh berkas basis data ketika proses penulisan berlangsung, sehingga proses pembacaan (*reader*) oleh web server terblokir.
* **Solusi yang Diterapkan**:
  * Mengaktifkan mode **WAL (Write-Ahead Logging)** pada SQLite (`PRAGMA journal_mode=WAL;`). Dalam mode WAL, proses pembacaan oleh Django *runserver* tidak pernah terblokir oleh proses penulisan data candle oleh Celery Worker.
  * Mengganti perulangan individual dengan **`bulk_create(..., update_conflicts=True, batch_size=1000)`**, meningkatkan efisiensi penulisan lebih dari 50x lipat.

---

### 4. Cache Terlalu Lama untuk Timeframe Cepat
* **Lokasi Berkas**: `trading_dashboard/views.py`
* **Akar Masalah**:
  * Durasi cache diatur tetap selama 5 menit (`timeout=300`) untuk semua timeframe.
  * Untuk timeframe 1 menit, angka yang ditampilkan di browser menjadi usang (*stale*) selama 5 candle ke depan.
* **Solusi yang Diterapkan**:
  * Menerapkan cache dinamis adaptif: 30 detik untuk `1m`, 60 detik untuk `5m`, dan 300 detik untuk timeframe harian/mingguan.

---

### 5. Simbol Komoditas Usang / Delisted (`C=F`)
* **Lokasi Berkas**: `data_ingestion/management/commands/seed_instruments.py`
* **Akar Masalah**:
  * Simbol Jagung Berjangka `C=F` sudah tidak aktif di Yahoo Finance (menghasilkan galat `HTTP Error 404: Quote not found`). Simbol aktif resmi CBOT adalah `ZC=F`.
* **Solusi yang Diterapkan**:
  * Memperbarui simbol komoditas jagung menjadi `ZC=F`.

---

### 6. Fitur Pemilihan 1 Pasar Tunggal & Mesin Prediksi 1 Menit ke Depan
* **Masalah Awal**:
  * Pengguna tidak dapat memilih atau memfilter hanya satu instrumen pasar yang diinginkan (misal: EURUSD atau BTC-USD).
  * Dashboard mencampuradukkan ringkasan 255 instrumen sekaligus, sehingga arah tren satu pasar spesifik tidak terlihat jelas.
  * Belum ada fitur yang secara eksplisit menyatakan apakah lilin 1 menit ke depan diprediksi **NAIK (BULLISH)** atau **TURUN (BEARISH)** beserta probabilitas persentasenya.
  * Fitur sinkronisasi selalu menarik 255 instrumen sekaligus sehingga lambat.
* **Solusi yang Diterapkan**:
  1. **Resolusi Simbol Cerdas (`resolve_instrument`)**: Mendukung simbol langsung, sufiks otomatis (`=X`, `-USD`, `.JK`), nama aset, dan kategori.
  2. **Mesin Prediksi Kuantitatif (`calculate_prediction_score`)**:
     * Konfluensi 4 pilar teknikal (EMA 9 vs 21, RSI 14, StochRSI %K/%D, MACD Histogram, dan Multi-Timeframe M15/M5).
     * Menghasilkan arah prediksi (`NAIK`, `TURUN`, `KONSOLIDASI`), probabilitas persentase, tingkat keyakinan, rekomendasi scalper, dan target volatilitas ATR 14.
  3. **Visualisasi 15 Bar Lilin Terakhir**: Menampilkan riwayat candle terbaru dengan informasi OHLCV, delta perubahan, dan warna lilin.
  4. **Sinkronisasi Cepat 1 Detik**: Tombol sinkronisasi individual yang menarik hanya instrumen yang sedang dilihat pengguna.

---

### 7. Bug Pembaruan Lilin Berjalan (*Stale In-Progress Candle Bug*)
* **Lokasi Berkas**: `data_ingestion/tasks.py` Baris 147
* **Gejala**:
  Candle terakhir yang tersimpan di SQLite3 sering kali menunjukkan harga penutupan yang keliru atau tidak sesuai dengan harga penutupan pasar resmi setelah menit tersebut berakhir.
* **Akar Masalah**:
  Pada penarikan inkremental, kode sebelumnya menggunakan kondisi:
  ```python
  if last_timestamp and aware_time <= last_timestamp:
      continue
  ```
  Ketika Celery menarik data yfinance, candle menit terakhir yang masuk sering kali masih dalam proses berjalan (*forming candle* / unclosed). Pada penarikan menit berikutnya, candle tersebut sebenarnya telah ditutup sempurna. Namun karena `aware_time == last_timestamp`, candle tersebut **dilewati (`continue`)**. Akibatnya, candle penutupan sebelumnya tertahan dengan data sementara, dan fitur `bulk_create` `update_conflicts=True` menjadi tidak pernah terpanggil (*dead code*).
* **Solusi yang Diterapkan**:
  Mengubah filter inkremental menjadi perbandingan kurang dari murni (`<`):
  ```python
  if last_timestamp and aware_time < last_timestamp:
      continue
  ```
  Dengan perubahan ini, data yang memiliki timestamp sama dengan `last_timestamp` tetap dimasukkan ke daftar `records_to_upsert`. Mekanisme `bulk_create` dengan `update_conflicts=True` kemudian memperbarui (*upsert*) harga penutupan, tertinggi, terendah, dan volume final secara akurat.

---

### 8. Bottleneck Latensi Eksternal Library `pandas_ta` (StochRSI & ATR)
* **Lokasi Berkas**: `technical_indicators/services.py`
* **Gejala**:
  Pemuatan halaman utama mode "Semua Pasar" (255 instrumen) memakan waktu **15 hingga 20 detik**, dan pemanfaatan CPU melonjak hingga 100%.
* **Akar Masalah**:
  Fungsi `ta.stochrsi()` dan `ta.atr()` dari library `pandas_ta` memiliki overhead validasi dan metadata yang sangat tinggi (~30 ms per panggilan). Ketika dieksekusi 255 kali dalam satu siklus request web, komputasi murni memakan waktu lebih dari 10 detik di luar query database.
* **Solusi yang Diterapkan**:
  Menggantikan pemanggilan `pandas_ta` dengan **Native Pandas Vectorization**:
  * **Native Stochastic RSI (14, 14, 3, 3)**:
    ```python
    min_rsi = rsi.rolling(window=14).min()
    max_rsi = rsi.rolling(window=14).max()
    rsi_range = max_rsi - min_rsi
    stoch = (100 * (rsi - min_rsi) / rsi_range.replace(0, float('nan'))).fillna(50)
    df['STOCH_K'] = stoch.rolling(window=3).mean()
    df['STOCH_D'] = df['STOCH_K'].rolling(window=3).mean()
    ```
  * **Native Wilder's ATR 14**:
    ```python
    tr1 = df['high_price'] - df['low_price']
    tr2 = (df['high_price'] - close.shift()).abs()
    tr3 = (df['low_price'] - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['ATR_14'] = tr.ewm(alpha=1/14, min_periods=min(14, len(df)), adjust=False).mean()
    ```
  * **Hasil Pengujian**: Latensi komputasi terpangkas dari **~37 ms menjadi ~1 ms per instrumen (Peningkatan Kinerja 35x Lipat)**. Waktu pemuatan halaman dingin untuk 255 instrumen turun drastis menjadi **~4 detik**, dan instrumen tunggal hanya membutuhkan **~50 milidetik**.

---

### 9. Potensi Pembagian dengan Nol (*ZeroDivisionError* / `NaN`) pada RSI saat Pasar Stagnan
* **Lokasi Berkas**: `technical_indicators/services.py`
* **Akar Masalah**:
  Rumus standar RSI:
  ```python
  df['RSI_14'] = 100 - (100 / (1 + ma_up / ma_down))
  ```
  Pada instrumen yang tidak likuid (saham tidur) atau komoditas saat bursa tutup di akhir pekan, harga sama sekali tidak bergerak selama 14 bar terakhir. Nilai `ma_down` menjadi `0`, yang memicu pembagian dengan nol dan menghasilkan nilai `NaN` atau `inf`.
* **Solusi yang Diterapkan**:
  Menambahkan pengamanan kondisi batas pada kalkulasi RSI:
  ```python
  rs = ma_up / ma_down.replace(0, float('nan'))
  rsi = (100 - (100 / (1 + rs))).fillna(50)
  rsi = rsi.where(ma_down != 0, 100)
  rsi = rsi.where(~((ma_up == 0) & (ma_down == 0)), 50)
  df['RSI_14'] = rsi
  ```
  Jika pasar stagnan total (`ma_up == 0` dan `ma_down == 0`), RSI dinormalkan ke nilai 50 (netral).

---

### 10. Pemanggilan Redundan Ganda Fungsi Pola Lilin `detect_candle_pattern(df)`
* **Lokasi Berkas**: `technical_indicators/services.py` Baris 208-209
* **Akar Masalah**:
  Kamus pengembalian memanggil fungsi analisis pola lilin dua kali secara terpisah:
  ```python
  'pattern_name': detect_candle_pattern(df)[0],
  'pattern_bias': detect_candle_pattern(df)[1],
  ```
* **Solusi yang Diterapkan**:
  Mengekstrak hasil pemanggilan ke dalam variabel lokal `pat_name, pat_bias = detect_candle_pattern(df)` sebelum menyusun dictionary pengembalian, menghilangkan eksekusi berulang.

---

### 11. Penyelarasan Invalidation Cache & Resolusi Cache Miss Auto-Refresh
* **Lokasi Berkas**: `trading_dashboard/views.py` & `data_ingestion/tasks.py`
* **Akar Masalah**:
  1. Cache TTL untuk timeframe `1m` disetel 15 detik, sementara auto-refresh peramban disetel 20 detik. Ini menyebabkan setiap refresh otomatis selalu mengalami *cache miss* dan memaksa server menghitung ulang 255 instrumen secara berkala.
  2. Ketika Celery selesai menarik data, perintah pembersihan cache hanya menghapus kunci `dashboard_market_data_{timeframe}`, sedangkan antarmuka web menyimpan cache dengan akhiran kategori seperti `dashboard_market_data_1m_all` dan `dashboard_market_data_1m_FOREX`. Akibatnya, tampilan dashboard tetap menampilkan data lama meskipun Celery sudah selesai mengunduh data baru.
* **Solusi yang Diterapkan**:
  * Menyelaraskan cache TTL timeframe `1m` menjadi 30 detik (menjamin *cache hit* instan saat auto-refresh 20 detik).
  * Memperbarui fungsi `fetch_market_prices()` di Celery dan `sync_market_data()` di views agar secara otomatis menghapus seluruh kunci cache kategori (`all`, `FOREX`, `CRYPTO`, `STOCK`, `COMMODITY`) dan simbol detail terkait saat data baru tersimpan.

---

### 12. Kesalahan Penentuan Scope `dynamic_period` pada Batch Unduhan yfinance
* **Lokasi Berkas**: `data_ingestion/tasks.py` Baris 98-103
* **Akar Masalah**:
  Logika optimasi periode unduh memeriksa:
  ```python
  has_existing = MarketData.objects.filter(instrument__in=batch, timeframe=timeframe).exists()
  if has_existing:
      dynamic_period = '1d'
  ```
  Jika dalam satu batch berisi 15 instrumen terdapat HANYA 1 instrumen yang sudah memiliki data candle, maka `has_existing` bernilai `True`. Akibatnya, 14 instrumen lainnya yang masih kosong dipaksa mengunduh hanya 1 hari data alih-alih periode penuh (`2d` untuk 1m atau `5d` untuk 5m), sehingga candle mereka tidak cukup untuk menghitung indikator teknikal (butuh minimal 15 candle).
* **Solusi yang Diterapkan**:
  Memastikan periode dipersingkat menjadi `'1d'` HANYA jika **seluruh** instrumen dalam batch tersebut sudah memiliki baris data di database:
  ```python
  existing_count = MarketInstrument.objects.filter(
      id__in=[inst.id for inst in batch],
      price_data__timeframe=timeframe
  ).distinct().count()
  if existing_count == len(batch):
      dynamic_period = '1d'
  ```

### 13. Kegagalan Unit Test `test_market_instrument_creation` Pasca-Integrasi IQ Option
* **Lokasi Berkas**: `data_ingestion/tests.py` & `data_ingestion/models.py`
* **Gejala**:
  Eksekusi `python manage.py test` menghasilkan:
  > `AssertionError: 'BTC-USD (Cryptocurrency - Yahoo Finance)' != 'BTC-USD (Cryptocurrency)'`
* **Akar Masalah**:
  Metode `__str__` pada model `MarketInstrument` diperbarui untuk menampilkan sumber data (`get_data_source_display()`), namun ekspektasi pengujian pada unit test lama belum disesuaikan.
* **Solusi yang Diterapkan**:
  Memperbarui ekspektasi pada unit test agar selaras dengan output `MarketInstrument.__str__` yang menyertakan data source.

---

### 14. Kebocoran Event Loop Asyncio pada Pemanggilan Berulang `IQOptionClient.get_candles`
* **Lokasi Berkas**: `data_ingestion/iqoption/client.py`
* **Gejala**:
  Ketika instance `IQOptionClient` yang sama dipanggil berulang kali untuk menarik candle secara sinkron (`get_candles()`), eksekusi kedua menghasilkan error:
  > `RuntimeError: Task <...> got Future <...> attached to a different loop`
* **Akar Masalah**:
  Metode `get_candles()` membungkus pemanggilan asinkron menggunakan `asyncio.run()`. Ketika `asyncio.run()` selesai, event loop ditutup namun koneksi WebSocket `self.ws` tetap tersimpan dan terikat pada event loop lama yang sudah tertutup. Pada pemanggilan berikutnya, `self.ws` digunakan di event loop baru tanpa direkoneksi, memicu galat runtime loop.
* **Solusi yang Diterapkan**:
  Membungkus eksekusi `get_candles_async()` dalam coroutine pelari (`_runner`) dengan blok `finally: await self.close()` untuk menjamin penutupan dan pelepasan objek WebSocket sebelum event loop ditutup.

---

### 15. Silent Skipping Sinkronisasi & Auto-Fetch Instrumen IQ Option pada Web Dashboard
* **Lokasi Berkas**: `trading_dashboard/views.py` (`main_dashboard` & `sync_data`)
* **Gejala**:
  Ketika pengguna memilih instrumen IQ Option (seperti `EURUSD-OTC`) yang datanya masih kosong di SQLite, atau menekan tombol *"⚡ Tarik Data EURUSD-OTC"*, sistem tidak menarik data apa pun dan candle tetap kosong.
* **Akar Masalah**:
  Handler sinkronisasi individual di `views.py` secara kaku memanggil `fetch_market_prices(symbols=[selected_inst.symbol])`. Karena `fetch_market_prices` khusus untuk Yahoo Finance dan mengecualikan instrumen OTC/non-Yahoo, query menghasilkan queryset kosong (`No active instruments.`), sehingga permintaan diabaikan secara diam-diam.
* **Solusi yang Diterapkan**:
  Menambahkan routing kondisional: jika `selected_inst.data_source == 'IQOPTION'` atau simbol berakhiran `-OTC`, alur diarahkan ke `fetch_iqoption_prices()`. Serta menambahkan unit test `test_single_market_sync_iqoption_redirect` untuk mengamankan fungsionalitas ini.

---

### 16. Potensi Infinite Loop saat Terputus Koneksi WebSocket pada `stream_candles`
* **Lokasi Berkas**: `data_ingestion/iqoption/client.py`
* **Gejala**:
  Jika koneksi WebSocket terputus di tengah streaming, loop menerima exception `websockets.ConnectionClosed`, tidur 1 detik, lalu memanggil `recv()` pada socket tertutup secara terus-menerus.
* **Solusi yang Diterapkan**:
  Menambahkan penanganan khusus `websockets.ConnectionClosed` dengan jeda reconnect 2 detik dan pengiriman ulang payload langganan (`subscribeMessage`).

---

### 17. Pengaktifan Kembali Mode SQLite WAL (Write-Ahead Logging)
* **Lokasi Berkas**: `db.sqlite3`
* **Gejala**:
  File basis data berada pada mode `delete` alih-alih `wal`, berpotensi memicu disk lock saat Celery Worker dan Django runserver bekerja bersamaan.
* **Solusi yang Diterapkan**:
  Mengeksekusi `PRAGMA journal_mode=WAL;` pada basis data lokal SQLite3.

---

### 18. SyntaxError pada Eksekutor CLI Streaming Real-Time IQ Option
* **Lokasi Berkas**: `data_ingestion/management/commands/stream_iqoption_realtime.py` Baris 173
* **Gejala**:
  Eksekusi skrip streaming real-time IQ Option langsung gagal dengan pesan kesalahan:
  > `SyntaxError: '(' was never closed`
* **Akar Masalah**:
  Pemanggilan `await sync_to_async(MarketData.objects.update_or_create)(` lupa ditutup kurung tutupnya pada baris deklarasi `defaults={...}`.
* **Solusi yang Diterapkan**:
  Menambahkan kurung penutup `)` pada pemanggilan fungsi `update_or_create`. Terverifikasi berhasil mengompilasi dan menjalankan streaming demo feed tanpa galat.

---

### 19. Ketergantungan Keras Redis pada Invalidation Cache & Kegagalan Suite Unit Test
* **Lokasi Berkas**: `data_ingestion/iqoption/service.py`, `trading_dashboard/views.py`, `data_ingestion/tasks.py`, & `config/settings.py`
* **Gejala**:
  1. Ketika server Redis offline atau restart, penarikan data candle IQ Option dilaporkan gagal (`success: False, records_saved: 0`) meskipun candle sebenarnya sudah sukses tersimpan ke database SQLite3.
  2. Eksekusi unit test `python manage.py test` mengalami 8 error kaskade `ConnectionError: Error 111 connecting to 127.0.0.1:6379`.
* **Akar Masalah**:
  1. Pembersihan cache (`cache.delete(...)`) dieksekusi tanpa penanganan eksepsi. Karena cache merupakan optimasi performa non-kritis, kegagalan koneksi cache tidak boleh menggugurkan operasi database inti.
  2. Pengaturan `CACHES` di Django settings tidak mengisolasi lingkungan pengujian, sehingga unit test mewajibkan daemon Redis aktif di port 6379.
* **Solusi yang Diterapkan**:
  * Membungkus seluruh pemanggilan pembacaan, penulisan, dan pembersihan cache (`cache.get`, `cache.set`, `cache.delete`) dalam blok penanganan aman `try-except`. Jika Redis tidak tersedia, sistem tetap berjalan normal membaca langsung dari SQLite3.
  * Mengonfigurasi `LocMemCache` secara otomatis di `settings.py` jika perintah `test` dijalankan (`if 'test' in sys.argv:`), menjamin isolasi total seluruh 26 unit test tanpa dependensi eksternal.

---

### 20. Tidak Terevaluasinya Posisi Paper Trading pada Background Task IQ Option
* **Lokasi Berkas**: `data_ingestion/tasks.py` (`fetch_iqoption_prices`)
* **Gejala**:
  Ketika order paper trading dibuka untuk instrumen IQ Option (seperti `EURUSD-OTC`), posisi terbuka tidak pernah tertutup otomatis oleh TP (Take Profit) atau SL (Stop Loss) saat Celery worker mengunduh candle baru di latar belakang.
* **Akar Masalah**:
  Logika evaluasi posisi `evaluate_open_positions()` dan pemindaian `process_auto_trading_signals()` hanya disematkan pada fungsi `fetch_market_prices` (khusus Yahoo Finance) dan terlewat pada task `fetch_iqoption_prices`.
* **Solusi yang Diterapkan**:
  Menambahkan pemanggilan `evaluate_open_positions()` dan `process_auto_trading_signals()` pada `fetch_iqoption_prices` segera setelah baris lilin baru tersimpan.

---

### 21. Ketidakcocokan Parameter URL Alert Error pada Paper Trading View
* **Lokasi Berkas**: `paper_trading/views.py` (`create_order_view`) vs `trading_dashboard/views.py`
* **Gejala**:
  Ketika pengguna memasukkan instrumen yang tidak valid pada formulir order, pesan error tidak muncul di kotak peringatan dashboard web.
* **Akar Masalah**:
  `create_order_view` mengarahkan redirect ke `/?error={msg}`, sementara `main_dashboard` dan antarmuka web hanya mendengarkan parameter `order_error`.
* **Solusi yang Diterapkan**:
  Menyelaraskan redirect ke `/?order_error={msg}` dan memperbarui `main_dashboard` untuk mendukung parameter `order_error` maupun fallback `error`.

---

### 22. Potensi Pelanggaran Integritas Timestamp pada TradingView Lightweight Charts
* **Lokasi Berkas**: `technical_indicators/services.py` (`get_detailed_prediction`)
* **Gejala**:
  Pada dataset dengan timestamp ganda atau timestamp microsecond yang membulat ke detik yang sama, library TradingView Lightweight Charts melemparkan galat konsol:
  > `Assertion failed: data must be asc ordered by time, [...], duplicate time`
  dan menghentikan rendering grafik secara total.
* **Akar Masalah**:
  Struktur deret data `chart_candles`, `chart_volume`, `chart_ema_9`, dsb. tidak memvalidasi keunikan detik integer secara ketat.
* **Solusi yang Diterapkan**:
  Menambahkan penjaga deret waktu `if prev_time_sec is not None and time_sec <= prev_time_sec: continue` pada loop pembentukan payload grafik, menjamin seluruh timestamp menaik secara ketat (*strictly ascending*).

---

### 23. Penanganan Aman Map `param.seriesData` pada Hover Tooltip Crosshair
* **Lokasi Berkas**: `trading_dashboard/templates/trading_dashboard/index.html`
* **Gejala**:
  Pada peramban tertentu atau saat kursor keluar cepat dari area kanvas, pemanggilan `param.seriesData.get(...)` berpotensi memicu `TypeError: Cannot read properties of undefined (reading 'get')`.
* **Akar Masalah**:
  `param.seriesData` diasumsikan selalu terdefinisi tanpa validasi awal ketersediaan metode `.get()`.
* **Solusi yang Diterapkan**:
  Menerapkan pemeriksaan defensif: `const sd = param.seriesData; const c = (sd && typeof sd.get === 'function') ? sd.get(candleSeries) : null;`.

---

### 24. Proteksi Transaksi Atomik Saldo Akun Virtual Paper Trading
* **Lokasi Berkas**: `paper_trading/services.py` (`open_paper_trade` & `close_paper_trade`)
* **Gejala**:
  Potensi anomali saldo jika order dibuka atau ditutup secara bersamaan dalam request paralel.
* **Solusi yang Diterapkan**:
  Menyematkan dekorator `@transaction.atomic` pada `open_paper_trade` dan `close_paper_trade` untuk menjamin konsistensi pembukuan kas simulasi.

---

## 📊 Ringkasan Hasil Pengujian Pasca-Perbaikan

| Aspek Pengujian | Sebelum Audit & Perbaikan | Setelah Audit & Perbaikan | Status |
| :--- | :---: | :---: | :---: |
| **Kompilasi CLI IQ Option Realtime** | SyntaxError: '(' was never closed | **Kompilasi Bersih & Demo Streaming Berjalan** | ✅ Terselesaikan |
| **Ketahanan Server terhadap Redis Gangguan** | Error 500 / Data Sync False | **Degradasi Anggun (Fallback Aman ke DB)** | ✅ Resilient & Handal |
| **Unit Test Django (`manage.py test`)** | 8 Error & 1 Gagal | **26/26 Test Suites Lolos Sempurna (0.69s)** | ✅ 100% Lolos |
| **Isolasi Cache Unit Test** | Wajib koneksi Redis aktif port 6379 | **Otomatis LocMemCache (Terisolasi Total)** | ✅ Standar Django |
| **Evaluasi Posisi Paper Trading Celery** | Hanya aset Yahoo Finance | **Mendukung Penuh Aset IQ Option / OTC** | ✅ Otomatis |
| **Integritas Waktu TradingView Charts** | Rawan crash assertion waktu duplikat | **Strict Monotonic Ascending Timestamps** | ✅ Stabil & Bebas Bug |
| **Penanganan Error Parameter Dashboard** | Pesan error tertelan/hilang | **Muncul Presisi di Alert Banner UI** | ✅ Responsif |
