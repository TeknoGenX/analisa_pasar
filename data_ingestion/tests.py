#data_ingestion/tests.py
from io import StringIO
from unittest.mock import MagicMock, patch

from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, TransactionTestCase
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
        MarketData.objects.create(
            instrument=inst,
            timeframe='1d',
            data_source='IQOPTION',
            timestamp=now,
            open_price=150.0,
            high_price=155.0,
            low_price=149.0,
            close_price=154.0,
            volume=10000.0,
        )
        self.assertEqual(
            MarketData.objects.filter(
                instrument=inst, timeframe='1d', timestamp=now
            ).count(),
            2,
        )

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
        self.assertEqual(
            MarketData.objects.filter(
                instrument=inst, timeframe='1m', data_source='IQOPTION'
            ).count(),
            30,
        )

    @patch('data_ingestion.tasks.yf.download')
    def test_yahoo_sync_saves_data_separately_for_iqoption_instrument(
        self, mock_download
    ):
        import pandas as pd

        instrument = MarketInstrument.objects.create(
            symbol='EURUSD=X',
            name='Euro / US Dollar',
            market_category='FOREX',
            data_source='IQOPTION',
        )
        timestamp = timezone.now()
        mock_download.return_value = pd.DataFrame(
            {
                'Open': [1.1],
                'High': [1.2],
                'Low': [1.0],
                'Close': [1.15],
                'Volume': [100.0],
            },
            index=[timestamp],
        )

        from data_ingestion.tasks import fetch_market_prices

        fetch_market_prices(timeframe='1m', symbols=[instrument.symbol])

        candle = MarketData.objects.get(
            instrument=instrument,
            timeframe='1m',
            data_source='YAHOO',
        )
        self.assertEqual(candle.close_price, 1.15)


class DoctorCommandTestCase(SimpleTestCase):
    @patch('data_ingestion.management.commands.doctor.checks.run_checks', return_value=[])
    @patch('data_ingestion.management.commands.doctor.connections')
    @patch('data_ingestion.management.commands.doctor.cache')
    @patch('data_ingestion.management.commands.doctor.celery_app')
    def test_doctor_command_reports_all_checks_as_successful(
        self, celery_app, cache, connections, run_checks
    ):
        database_connection = MagicMock()
        connections.__getitem__.return_value = database_connection
        cache.get.return_value = 'ok'
        celery_app.connection_for_write.return_value.__enter__.return_value = MagicMock()

        output = StringIO()
        call_command('doctor', stdout=output)

        self.assertIn('Django: pemeriksaan konfigurasi lulus', output.getvalue())
        self.assertIn('Database: koneksi lulus', output.getvalue())
        self.assertIn('Cache: tulis/baca lulus', output.getvalue())
        self.assertIn('Celery broker: koneksi lulus', output.getvalue())
        self.assertIn('Semua pemeriksaan lulus.', output.getvalue())

    @patch('data_ingestion.management.commands.doctor.checks.run_checks', return_value=[])
    @patch('data_ingestion.management.commands.doctor.connections')
    @patch('data_ingestion.management.commands.doctor.cache')
    @patch('data_ingestion.management.commands.doctor.celery_app')
    def test_doctor_command_fails_when_cache_is_unavailable(
        self, celery_app, cache, connections, run_checks
    ):
        from redis.exceptions import ConnectionError

        connections.__getitem__.return_value = MagicMock()
        cache.set.side_effect = ConnectionError('cache unavailable')
        celery_app.connection_for_write.return_value.__enter__.return_value = MagicMock()

        with self.assertRaises(CommandError):
            call_command('doctor', stdout=StringIO(), stderr=StringIO())


class StreamCryptoRealtimeTestCase(TransactionTestCase):
    @patch('data_ingestion.management.commands.stream_crypto_realtime.websockets.connect')
    def test_stream_crypto_realtime_handles_closed_candle_without_async_error(
        self, mock_ws_connect
    ):
        import json
        from unittest.mock import AsyncMock

        inst = MarketInstrument.objects.create(
            symbol='BTC-USD',
            name='Bitcoin / US Dollar',
            market_category='CRYPTO',
            is_active=True,
        )

        fake_msg = json.dumps({
            'k': {
                'x': True,
                'c': '68000.0',
                'h': '68200.0',
                'l': '67900.0',
                'o': '68050.0',
                'v': '15.5',
                't': 1700000000000,
            }
        })

        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=fake_msg)
        mock_ws_connect.return_value.__aenter__.return_value = mock_ws

        out = StringIO()
        call_command('stream_crypto_realtime', '--symbol', 'BTC-USD', '--max-candles', '1', stdout=out)

        # Pastikan tidak terjadi SynchronousOnlyOperation dan lilin tersimpan
        candle = MarketData.objects.filter(instrument=inst, timeframe='1m').first()
        self.assertIsNotNone(candle)
        self.assertEqual(candle.close_price, 68000.0)
        self.assertEqual(candle.open_price, 68050.0)
        self.assertIn('LILIN 1M SELESAI #1', out.getvalue())

    def test_seed_instruments_contains_nexai_and_idx_stocks(self):
        from data_ingestion.management.commands.seed_instruments import ALL_INSTRUMENTS
        from trading_dashboard.views import resolve_instrument

        # Cek ketersediaan NexAI Digital Infrastruktur Tbk (MGLV.JK)
        mglv = next((item for item in ALL_INSTRUMENTS if item['symbol'] == 'MGLV.JK'), None)
        self.assertIsNotNone(mglv)
        self.assertIn('NexAI Digital Infrastruktur', mglv['name'])
        self.assertEqual(mglv['market_category'], 'STOCK')

        # Seeding instrumen MGLV ke DB
        inst = MarketInstrument.objects.create(
            symbol=mglv['symbol'],
            name=mglv['name'],
            market_category=mglv['market_category'],
            is_active=True,
        )

        # Resolusi via kode MGLV tanpa .JK
        resolved_by_code = resolve_instrument('MGLV')
        self.assertIsNotNone(resolved_by_code)
        self.assertEqual(resolved_by_code.symbol, 'MGLV.JK')

        # Resolusi via nama perusahaan
        resolved_by_name = resolve_instrument('NexAI')
        self.assertIsNotNone(resolved_by_name)
        self.assertEqual(resolved_by_name.symbol, 'MGLV.JK')

