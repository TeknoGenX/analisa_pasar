#technical_indicators/tests.py 
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from data_ingestion.models import MarketInstrument, MarketData
from technical_indicators.services import analyze_instrument_optimized

class TechnicalIndicatorsTestCase(TestCase):
    def setUp(self):
        self.instrument = MarketInstrument.objects.create(
            symbol='EURUSD=X',
            name='Euro / US Dollar',
            market_category='FOREX',
            is_active=True
        )

    def test_insufficient_data_returns_none(self):
        # Kurang dari 20 baris data harus mengembalikan None
        base_time = timezone.now()
        for i in range(10):
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1d',
                timestamp=base_time - timedelta(days=i),
                open_price=1.10,
                high_price=1.12,
                low_price=1.09,
                close_price=1.11,
                volume=100.0
            )
        result = analyze_instrument_optimized(self.instrument.id, timeframe='1d')
        self.assertIsNone(result)

    def test_sufficient_data_calculates_indicators_and_macd(self):
        # 30 baris data untuk memastikan SMA, RSI, dan MACD terhitung
        base_time = timezone.now()
        for i in range(35):
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1d',
                timestamp=base_time - timedelta(days=35 - i),
                open_price=1.10 + (i * 0.01),
                high_price=1.12 + (i * 0.01),
                low_price=1.09 + (i * 0.01),
                close_price=1.10 + (i * 0.01),
                volume=100.0
            )

        result = analyze_instrument_optimized(self.instrument.id, timeframe='1d')
        self.assertIsNotNone(result)
        self.assertIn('SMA_5', result)
        self.assertIn('SMA_20', result)
        self.assertIn('RSI_14', result)
        self.assertIn('MACD', result)
        self.assertIn('Signal', result)
        self.assertIn(result['Signal'], ['BUY', 'STRONG BUY', 'SELL', 'STRONG SELL', 'HOLD', 'WAIT'])

    def test_detailed_prediction_chart_data_structure(self):
        from technical_indicators.services import get_detailed_prediction
        base_time = timezone.now()
        for i in range(40):
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='15m',
                timestamp=base_time - timedelta(minutes=(40 - i) * 15),
                open_price=1.10 + (i * 0.001),
                high_price=1.105 + (i * 0.001),
                low_price=1.095 + (i * 0.001),
                close_price=1.102 + (i * 0.001),
                volume=150.0
            )

        res = get_detailed_prediction(self.instrument.id, timeframe='15m')
        self.assertTrue(res['has_enough_data'])
        self.assertIn('chart_data', res)
        cd = res['chart_data']
        self.assertIn('candles', cd)
        self.assertIn('atr_upper', cd)
        self.assertIn('atr_lower', cd)
        self.assertIn('ema_9', cd)
        self.assertIn('ema_21', cd)
        self.assertIn('rsi', cd)
        self.assertIn('macd', cd)
        self.assertIn('markers', cd)
        self.assertEqual(len(cd['candles']), 40)
        self.assertEqual(len(cd['atr_upper']), 40)
        self.assertEqual(len(cd['atr_lower']), 40)
        for m in cd['markers']:
            self.assertIn('time', m)
            self.assertIn('position', m)
            self.assertIn('shape', m)
            self.assertIn('text', m)

    def test_detailed_prediction_uses_selected_data_source(self):
        from technical_indicators.services import get_detailed_prediction

        base_time = timezone.now()
        for i in range(25):
            timestamp = base_time - timedelta(minutes=25 - i)
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1m',
                data_source='YAHOO',
                timestamp=timestamp,
                open_price=1.1 + i * 0.001,
                high_price=1.12 + i * 0.001,
                low_price=1.09 + i * 0.001,
                close_price=1.11 + i * 0.001,
                volume=100.0,
            )
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1m',
                data_source='IQOPTION',
                timestamp=timestamp,
                open_price=2.1 + i * 0.001,
                high_price=2.12 + i * 0.001,
                low_price=2.09 + i * 0.001,
                close_price=2.11 + i * 0.001,
                volume=100.0,
            )

        yahoo_result = get_detailed_prediction(
            self.instrument.id, timeframe='1m', data_source='YAHOO'
        )
        iqoption_result = get_detailed_prediction(
            self.instrument.id, timeframe='1m', data_source='IQOPTION'
        )

        self.assertTrue(yahoo_result['has_enough_data'])
        self.assertTrue(iqoption_result['has_enough_data'])
        self.assertEqual(yahoo_result['latest']['close'], 1.134)
        self.assertEqual(iqoption_result['latest']['close'], 2.134)

    def test_analyze_instrument_optimized_uses_selected_data_source(self):
        base_time = timezone.now()
        for i in range(25):
            timestamp = base_time - timedelta(minutes=25 - i)
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='15m',
                data_source='YAHOO',
                timestamp=timestamp,
                open_price=1.10,
                high_price=1.12,
                low_price=1.09,
                close_price=1.11,
                volume=100.0,
            )
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='15m',
                data_source='IQOPTION',
                timestamp=timestamp,
                open_price=2.10,
                high_price=2.12,
                low_price=2.09,
                close_price=2.11,
                volume=100.0,
            )

        res_yahoo = analyze_instrument_optimized(self.instrument.id, timeframe='15m', data_source='YAHOO')
        res_iq = analyze_instrument_optimized(self.instrument.id, timeframe='15m', data_source='IQOPTION')

        self.assertIsNotNone(res_yahoo)
        self.assertIsNotNone(res_iq)
        self.assertEqual(res_yahoo['close_price'], 1.11)
        self.assertEqual(res_iq['close_price'], 2.11)
        self.assertAlmostEqual(res_yahoo['SMA_20'], 1.11)
        self.assertAlmostEqual(res_iq['SMA_20'], 2.11)

