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
        self.assertEqual(str(inst), 'BTC-USD (Cryptocurrency - Yahoo Finance)')

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

    def test_iqoption_resolve_active_id(self):
        from data_ingestion.iqoption.constants import resolve_active_id
        name, aid = resolve_active_id('EURUSD-OTC')
        self.assertEqual(name, 'EURUSD-OTC')
        self.assertEqual(aid, 76)

        name, aid = resolve_active_id('EURUSD')
        self.assertEqual(aid, 1)

        name, aid = resolve_active_id('BTC-USD')
        self.assertEqual(aid, 816)

    def test_iqoption_sync_candles_demo(self):
        from data_ingestion.iqoption.service import sync_iqoption_candles, get_or_create_iqoption_instrument
        inst = get_or_create_iqoption_instrument('EURUSD-OTC')
        self.assertEqual(inst.symbol, 'EURUSD-OTC')
        self.assertEqual(inst.market_category, 'FOREX')

        result = sync_iqoption_candles('EURUSD-OTC', timeframe='1m', count=30, demo_feed=True)
        self.assertTrue(result['success'])
        self.assertEqual(result['records_saved'], 30)

        count = MarketData.objects.filter(instrument=inst, timeframe='1m').count()
        self.assertEqual(count, 30)

