from django.test import TestCase
from django.utils import timezone
from data_ingestion.models import MarketInstrument, MarketData

class DataIngestionModelTestCase(TestCase):
    def test_market_instrument_creation(self):
        inst = MarketInstrument.objects.create(
            symbol='BTC-USD',
            name='Bitcoin / US Dollar',
            market_category='CRYPTO',
            is_active=True
        )
        self.assertEqual(str(inst), 'BTC-USD (Cryptocurrency)')

    def test_market_data_creation_and_uniqueness(self):
        inst = MarketInstrument.objects.create(
            symbol='AAPL',
            name='Apple Inc',
            market_category='STOCK',
            is_active=True
        )
        now = timezone.now()
        md = MarketData.objects.create(
            instrument=inst,
            timeframe='1d',
            timestamp=now,
            open_price=150.0,
            high_price=155.0,
            low_price=149.0,
            close_price=154.0,
            volume=10000.0
        )
        self.assertEqual(md.timeframe, '1d')
        self.assertIn('AAPL', str(md))
