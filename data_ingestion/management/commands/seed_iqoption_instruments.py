#data_ingestion/management/commands/seed_iqoption_instruments.py
from django.core.management.base import BaseCommand
from data_ingestion.models import MarketInstrument
from data_ingestion.iqoption.constants import POPULAR_IQOPTION_INSTRUMENTS


class Command(BaseCommand):
    help = 'Mendaftarkan / Seeding instrumen populer IQ Option Traderoom (termasuk pasangan OTC 24/7) ke SQLite3'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("\n========================================================"))
        self.stdout.write(self.style.NOTICE("🌱 SEEDING INSTRUMEN IQ OPTION TRADEROOM"))
        self.stdout.write(self.style.NOTICE("========================================================\n"))

        created_count = 0
        updated_count = 0

        for item in POPULAR_IQOPTION_INSTRUMENTS:
            symbol = item['symbol']
            name = item['name']
            category = item['category']

            # Pasangan OTC adalah instrumen eksklusif IQ Option (24/7 & Weekend)
            if symbol.endswith('-OTC'):
                inst, created = MarketInstrument.objects.get_or_create(
                    symbol=symbol,
                    defaults={
                        'name': name,
                        'market_category': category,
                        'data_source': 'IQOPTION',
                        'is_active': True,
                    }
                )

                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f"  [+] Baru (OTC): {symbol:<15} | {name:<25} | {category}"))
                else:
                    # Pastikan data_source tetap IQOPTION
                    if inst.data_source != 'IQOPTION':
                        inst.data_source = 'IQOPTION'
                        inst.save(update_fields=['data_source'])
                    updated_count += 1
                    self.stdout.write(f"  [=] Terdaftar : {symbol:<15} | {name:<25} | {category}")
            else:
                # Instrumen non-OTC (Forex/Crypto standar) menggunakan feed Yahoo Finance
                # agar tidak terjadi duplikasi simbol invalid di yfinance
                self.stdout.write(f"  [*] Terhubung : {symbol:<15} -> Feed Pasar Global (Yahoo Finance)")

        self.stdout.write(self.style.NOTICE("\n========================================================"))
        self.stdout.write(self.style.SUCCESS(
            f"🎉 Selesai! {created_count} instrumen baru ditambahkan, {updated_count} instrumen sudah ada."
        ))
        self.stdout.write(self.style.NOTICE("========================================================\n"))
