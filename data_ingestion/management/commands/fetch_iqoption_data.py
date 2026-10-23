#data_ingestion/management/commands/fetch_iqoption_data.py
import os
import time
from django.core.management.base import BaseCommand
from data_ingestion.iqoption.constants import (
    POPULAR_IQOPTION_INSTRUMENTS,
    TIMEFRAME_TO_SECONDS,
    resolve_active_id,
)
from data_ingestion.iqoption.service import sync_iqoption_candles, get_or_create_iqoption_instrument


class Command(BaseCommand):
    help = 'Menarik riwayat data lilin pasar dari IQ Option Traderoom (https://iqoption.com/traderoom)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--symbol',
            type=str,
            default='EURUSD-OTC',
            help='Simbol instrumen IQ Option (contoh: EURUSD, EURUSD-OTC, GBPUSD-OTC, BTCUSD, XAUUSD, atau "all-popular")'
        )
        parser.add_argument(
            '--timeframe',
            '-tf',
            type=str,
            default='1m',
            choices=['1m', '5m', '15m', '30m', '1h', '1d'],
            help='Kerangka waktu lilin (1m, 5m, 15m, 30m, 1h, 1d)'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=200,
            help='Jumlah lilin historis yang ingin diunduh (default: 200, maks: 1000 per request)'
        )
        parser.add_argument(
            '--ssid',
            type=str,
            default=None,
            help='Token SSID IQ Option (bisa juga diset di .env sebagai IQOPTION_SSID)'
        )
        parser.add_argument(
            '--email',
            type=str,
            default=None,
            help='Email akun IQ Option (opsional, jika tidak menggunakan SSID)'
        )
        parser.add_argument(
            '--password',
            type=str,
            default=None,
            help='Password akun IQ Option (opsional, jika tidak menggunakan SSID)'
        )
        parser.add_argument(
            '--demo-feed',
            action='store_true',
            help='Gunakan mode demo feed simulasi untuk pengujian tanpa kredensial aktif'
        )

    def handle(self, *args, **options):
        symbol_arg = options['symbol']
        timeframe = options['timeframe']
        count = options['count']
        ssid = options['ssid'] or os.environ.get('IQOPTION_SSID')
        email = options['email'] or os.environ.get('IQOPTION_EMAIL')
        password = options['password'] or os.environ.get('IQOPTION_PASSWORD')
        demo_feed = options['demo_feed']

        self.stdout.write(self.style.NOTICE("\n========================================================"))
        self.stdout.write(self.style.NOTICE("📊 PENARIKAN DATA PASAR IQ OPTION TRADEROOM"))
        self.stdout.write(self.style.NOTICE("========================================================"))
        self.stdout.write(f"• URL Platform : https://iqoption.com/traderoom")
        self.stdout.write(f"• Timeframe    : {timeframe} ({TIMEFRAME_TO_SECONDS.get(timeframe, 60)} detik)")
        self.stdout.write(f"• Target Bar   : {count} lilin")
        self.stdout.write(f"• Mode         : {'Simulasi Demo Feed' if demo_feed else 'Live WebSocket IQ Option'}\n")

        # Cek ketersediaan kredensial jika bukan mode demo feed
        if not demo_feed and not ssid and not (email and password):
            self.stdout.write(self.style.WARNING("⚠️ PERHATIAN: Kredensial IQ Option belum diatur di .env!"))
            self.stdout.write("💡 CARA MENDAPATKAN SSID DARI BROWSER:")
            self.stdout.write("1. Buka https://iqoption.com/traderoom di Chrome / Firefox / Edge dan login.")
            self.stdout.write("2. Tekan tombol F12 (Buka Developer Tools).")
            self.stdout.write("3. Masuk ke tab 'Application' (atau 'Storage') > 'Cookies' > 'https://iqoption.com'.")
            self.stdout.write("4. Cari baris bernama 'ssid', salin nilai nilainya (string panjang acak).")
            self.stdout.write("5. Tambahkan ke file .env:\n   IQOPTION_SSID=nilai_ssid_anda")
            self.stdout.write("\n💡 Atau jalankan dengan opsi --demo-feed untuk menguji pipeline sekarang:")
            self.stdout.write("   python manage.py fetch_iqoption_data --symbol EURUSD-OTC --demo-feed\n")
            return

        # Tentukan daftar simbol yang akan ditarik
        if symbol_arg.lower() in ['all-popular', 'all', 'popular']:
            symbols_to_fetch = [p['symbol'] for p in POPULAR_IQOPTION_INSTRUMENTS]
        elif ',' in symbol_arg:
            symbols_to_fetch = [s.strip() for s in symbol_arg.split(',') if s.strip()]
        else:
            symbols_to_fetch = [symbol_arg.strip()]

        total = len(symbols_to_fetch)
        success_count = 0
        total_records = 0

        for idx, sym in enumerate(symbols_to_fetch, 1):
            name, act_id = resolve_active_id(sym)
            if not act_id:
                self.stdout.write(self.style.ERROR(f"[{idx}/{total}] ❌ Simbol '{sym}' tidak dikenali dalam daftar IQ Option."))
                continue

            self.stdout.write(f"[{idx}/{total}] Mengunduh {name} (ID: {act_id}) [{timeframe}]...")

            res = sync_iqoption_candles(
                symbol=name,
                timeframe=timeframe,
                count=count,
                ssid=ssid,
                email=email,
                password=password,
                demo_feed=demo_feed
            )

            if res.get('success'):
                saved = res.get('records_saved', 0)
                success_count += 1
                total_records += saved
                self.stdout.write(self.style.SUCCESS(
                    f"   ✅ Berhasil: {saved} lilin tersimpan ke SQLite3. "
                    f"URL Dasbor: http://127.0.0.1:8000/?symbol={res['instrument']}&tf={timeframe}"
                ))
            else:
                self.stdout.write(self.style.ERROR(f"   ❌ Gagal: {res.get('error')}"))

        self.stdout.write(self.style.NOTICE("\n========================================================"))
        self.stdout.write(self.style.SUCCESS(
            f"🎉 Selesai! Berhasil memproses {success_count}/{total} instrumen. "
            f"Total {total_records} candle bar tersimpan ke database."
        ))
        self.stdout.write(self.style.NOTICE("========================================================\n"))
