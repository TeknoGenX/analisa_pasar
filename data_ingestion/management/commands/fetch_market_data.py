from django.core.management.base import BaseCommand
from data_ingestion.tasks import fetch_market_prices, TIMEFRAME_CONFIG

class Command(BaseCommand):
    help = 'Menarik data harga pasar dari Yahoo Finance untuk timeframe yang ditentukan (misal: 1m, 5m, 1d)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--timeframe',
            type=str,
            default=None,
            help='Satu timeframe tertentu, misal: 1m, 5m, 15m, 1h, 1d'
        )
        parser.add_argument(
            '--timeframes',
            type=str,
            default=None,
            help='Daftar timeframe dipisah koma, contoh: 1m,5m,1d'
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Tarik seluruh timeframe utama (1m, 5m, 1d)'
        )

    def handle(self, *args, **options):
        tf_list = []
        if options['all']:
            tf_list = ['1m', '5m', '15m', '30m', '1h', '1d', '1wk']
        elif options['timeframes']:
            tf_list = [t.strip() for t in options['timeframes'].split(',') if t.strip()]
        elif options['timeframe']:
            tf_list = [options['timeframe'].strip()]
        else:
            tf_list = ['1m', '5m', '15m', '30m', '1h', '1d', '1wk']

        self.stdout.write(self.style.NOTICE(f"🚀 Memulai penarikan data untuk timeframe: {', '.join(tf_list)}"))

        for tf in tf_list:
            if tf not in TIMEFRAME_CONFIG:
                self.stdout.write(self.style.WARNING(f"⚠️ Timeframe '{tf}' tidak valid. Pilihan: {list(TIMEFRAME_CONFIG.keys())}"))
                continue

            self.stdout.write(f"⏳ Sedang mengunduh data pasar untuk timeframe '{tf}'...")
            result = fetch_market_prices(timeframe=tf)
            self.stdout.write(self.style.SUCCESS(f"✅ {result}"))

        self.stdout.write(self.style.SUCCESS("🎉 Seluruh penarikan data selesai!"))
