# 📡 Panduan Integrasi IQ Option Traderoom (`https://iqoption.com/traderoom`)

Dokumen ini menjelaskan arsitektur, metode autentikasi, serta cara pengoperasian modul integrasi data langsung dari platform **IQ Option Traderoom** ke dalam sistem **Tekno-Pasar**.

---

## 🌟 Fitur Integrasi IQ Option

1. **Dukungan Pasangan OTC (Over-The-Counter) 24/7 & Weekend**:
   - Memungkinkan analisa teknikal dan prediksi arah lilin pada akhir pekan (Sabtu & Minggu) saat pasar Forex reguler tutup.
   - Contoh instrumen: `EURUSD-OTC`, `GBPUSD-OTC`, `USDJPY-OTC`, `EURGBP-OTC`, `USDCHF-OTC`, `EURJPY-OTC`, `NZDUSD-OTC`, `GBPJPY-OTC`, `AUDCAD-OTC`.

2. **Dukungan Seluruh Timeframe Standar**:
   - Timeframe cepat: `1m` (60s), `5m` (300s), `15m` (900s), `30m` (1800s), `1h` (3600s), `1d` (86400s).

3. **Mesin Prediksi Kuantitatif Real-Time 1M & 5M**:
   - Setiap lilin IQ Option yang selesai ditutup langsung dihitung indikatornya (EMA 9/21, Wilder's RSI, StochRSI, MACD, Wilder's ATR).
   - Menghasilkan probabilitas arah ($t+1$), tingkat keyakinan, proyeksi target Take Profit (TP), dan Stop Loss (SL).

4. **Koneksi WebSocket Native Ringan Tanpa Pustaka Kadaluwarsa**:
   - Berjalan langsung di atas Python `websockets` modern (Python 3.13) yang terhubung ke `wss://iqoption.com/echo/websocket`.

---

## 🔐 2 Metode Autentikasi

IQ Option Traderoom memerlukan autentikasi sesi. Sistem ini menyediakan 2 metode:

### Metode 1: Menggunakan Cookie `SSID` dari Browser (SANGAT DIREKOMENDASIKAN ⭐)
Metode ini **paling aman dan stabil** karena:
- Menghindari masalah verifikasi 2FA (Two-Factor Authentication / Email Code / SMS).
- Menghindari blokir Cloudflare bot protection.

**Langkah-langkah mengambil SSID:**
1. Buka browser (Chrome, Firefox, Edge, atau Brave) dan buka [https://iqoption.com/traderoom](https://iqoption.com/traderoom).
2. Login ke akun IQ Option Anda (bisa akun Real atau Demo).
3. Buka **Developer Tools** dengan menekan tombol **F12** (atau klik kanan > *Inspect*).
4. Masuk ke tab **Application** (Chrome/Edge) atau **Storage** (Firefox).
5. Pada menu sebelah kiri, buka **Cookies** > klik `https://iqoption.com`.
6. Cari baris bernama **`ssid`**.
7. Salin (copy) nilai pada kolom **Value** (berupa deretan string acak).
8. Buka file `.env` di proyek ini dan tempelkan:
   ```env
   IQOPTION_SSID=string_ssid_hasil_salinan_anda
   ```

### Metode 2: Menggunakan Email & Password
Jika akun Anda tidak mengaktifkan 2FA:
Buka file `.env` dan masukkan:
```env
IQOPTION_EMAIL=email_anda@example.com
IQOPTION_PASSWORD=password_akun_anda
```
Sistem akan otomatis melakukan login HTTP ke `https://auth.iqoption.com/api/v2/login` dan meminta token sesi `ssid`.

### Metode 3: Mode Simulasi Demo Feed (`--demo-feed`)
Jika Anda ingin menguji seluruh alur kerja sistem, penyimpanan database, mesin prediksi, dan dasbor web tanpa memasukkan kredensial:
Cukup sertakan flag `--demo-feed`.

---

## 🛠️ Perintah Operasional CLI

### 1. Mendaftarkan Instrumen Populer IQ Option (Seeding)
Mendaftarkan instrumen Forex reguler dan pasangan OTC khusus IQ Option ke basis data SQLite:
```bash
python manage.py seed_iqoption_instruments
```

### 2. Mengunduh Data Lilin Historis (`fetch_iqoption_data`)
Mengambil riwayat lilin dari IQ Option dan menyimpannya secara massal (*bulk upsert*) ke basis data:

- **Mengunduh 1 instrumen OTC (EUR/USD OTC, timeframe 1m, 200 lilin):**
  ```bash
  python manage.py fetch_iqoption_data --symbol EURUSD-OTC --timeframe 1m --count 200
  ```

- **Mengunduh beberapa instrumen sekaligus:**
  ```bash
  python manage.py fetch_iqoption_data --symbol EURUSD-OTC,GBPUSD-OTC,USDJPY-OTC --timeframe 1m --count 100
  ```

- **Mengunduh seluruh instrumen populer IQ Option:**
  ```bash
  python manage.py fetch_iqoption_data --symbol all-popular --timeframe 5m --count 150
  ```

- **Menguji dengan mode Demo Feed (tanpa login):**
  ```bash
  python manage.py fetch_iqoption_data --symbol EURUSD-OTC --demo-feed --count 100
  ```

### 3. Streaming WebSocket Real-Time (`stream_iqoption_realtime`)
Membuka koneksi langsung ke WebSocket IQ Option Traderoom untuk mendengarkan pergerakan harga tick dan penutupan candle 1 menit secara *real-time*:

```bash
python manage.py stream_iqoption_realtime --symbol EURUSD-OTC --timeframe 1m
```

**Fitur selama streaming berlangsung:**
- Menampilkan pergerakan tick harga real-time dan persentase perubahan.
- Saat lilin 1 menit ditutup:
  - Menyimpan lilin ke SQLite3.
  - Membandingkan hasil riil dengan prediksi sebelumnya (menghitung akurasi win-rate sesi).
  - Menjalankan mesin prediksi kuantitatif untuk 1 menit ke depan ($t+1$).
  - Memperbarui cache Redis sehingga Dasbor Web langsung ter-refresh secara instan.

**Contoh uji coba dengan mode demo:**
```bash
python manage.py stream_iqoption_realtime --symbol EURUSD-OTC --timeframe 1m --demo-feed
```

---

## 🌐 Menampilkan di Dasbor Terminal Web

Setelah data tersimpan atau saat streaming berjalan, Anda dapat memantau pergerakan lilin dan prediksi di browser:

- Buka URL: [http://127.0.0.1:8000/?symbol=EURUSD-OTC&tf=1m](http://127.0.0.1:8000/?symbol=EURUSD-OTC&tf=1m)
- Atau pilih tombol cepat **EUR/USD (OTC IQ)** pada panel navigasi simbol populer dasbor.

---

## ⏰ Otomasi Latar Belakang (Celery & Celery Beat)

Jika `IQOPTION_SSID` atau `IQOPTION_EMAIL` + `IQOPTION_PASSWORD` dikonfigurasi pada `.env`:
- **Celery Beat** akan secara otomatis menjadwalkan penarikan data candle IQ Option setiap 2 menit:
  - Task: `data_ingestion.tasks.fetch_iqoption_prices`
  - Schedule: `*/2 * * * *`
- Data candle baru akan tersinkronisasi secara terus-menerus ke dalam basis data SQLite tanpa perlu intervensi manual.
