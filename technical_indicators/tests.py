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
