from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from data_ingestion.models import MarketInstrument, MarketData

class DashboardViewsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.instrument = MarketInstrument.objects.create(
            symbol='EURUSD=X',
            name='Euro / US Dollar',
            market_category='FOREX',
            is_active=True
        )
        base_time = timezone.now()
        for i in range(25):
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1d',
                timestamp=base_time - timedelta(days=25 - i),
                open_price=1.10 + (i * 0.005),
                high_price=1.12 + (i * 0.005),
                low_price=1.09 + (i * 0.005),
                close_price=1.10 + (i * 0.005),
                volume=100.0
            )

    def test_main_dashboard_view_status_200(self):
        response = self.client.get(reverse('trading_dashboard:main_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('data', response.context)
        self.assertIn('summary', response.context)
        self.assertIn('active_tf', response.context)
        self.assertEqual(response.context['active_tf'], '1d')

    def test_main_dashboard_custom_timeframe(self):
        response = self.client.get(reverse('trading_dashboard:main_dashboard') + '?tf=1h')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tf'], '1h')

    def test_single_market_selection_eurusd_1m(self):
        # Buat data 1m untuk EURUSD
        base_time = timezone.now()
        for i in range(25):
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1m',
                timestamp=base_time - timedelta(minutes=25 - i),
                open_price=1.1200 + (i * 0.0001),
                high_price=1.1205 + (i * 0.0001),
                low_price=1.1195 + (i * 0.0001),
                close_price=1.1202 + (i * 0.0001),
                volume=50.0
            )

        response = self.client.get(reverse('trading_dashboard:main_dashboard') + '?symbol=EURUSD=X&tf=1m')
        self.assertEqual(response.status_code, 200)
        self.assertIn('selected_instrument', response.context)
        self.assertEqual(response.context['selected_instrument'].symbol, 'EURUSD=X')
        self.assertIn('prediction_data', response.context)
        pred_data = response.context['prediction_data']
        self.assertTrue(pred_data['has_enough_data'])
        self.assertIn(pred_data['prediction']['direction'], ['NAIK', 'TURUN', 'KONSOLIDASI'])
        self.assertGreaterEqual(pred_data['prediction']['prob_up'], 0)
        self.assertGreaterEqual(pred_data['prediction']['prob_down'], 0)
        self.assertIn('EURUSD=X', response.content.decode('utf-8'))
        self.assertIn('PREDIKSI', response.content.decode('utf-8'))

    def test_flexible_symbol_lookup_without_suffix(self):
        # Memilih 'EURUSD' tanpa '=X' harus otomatis ter-resolve ke 'EURUSD=X'
        response = self.client.get(reverse('trading_dashboard:main_dashboard') + '?symbol=EURUSD&tf=1d')
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context['selected_instrument'])
        self.assertEqual(response.context['selected_instrument'].symbol, 'EURUSD=X')

    def test_single_market_export_csv(self):
        response = self.client.get(reverse('trading_dashboard:export_csv') + '?symbol=EURUSD=X&tf=1d')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment; filename="analisa_EURUSD=X_1d.csv"', response['Content-Disposition'])
        content = response.content.decode('utf-8')
        self.assertIn('EURUSD=X', content)
        self.assertIn('Prediksi Arah', content)

    from unittest.mock import patch

    @patch('data_ingestion.tasks.fetch_market_prices')
    def test_single_market_sync_redirect(self, mock_fetch):
        response = self.client.get(reverse('trading_dashboard:sync_data') + '?symbol=EURUSD=X&tf=1m')
        self.assertEqual(response.status_code, 302)
        self.assertIn('symbol=EURUSD=X', response.url)
        self.assertIn('tf=1m', response.url)
        mock_fetch.assert_called_once_with(timeframe='1m', symbols=['EURUSD=X'])

    def test_category_filter(self):
        response = self.client.get(reverse('trading_dashboard:main_dashboard') + '?category=FOREX&tf=1d')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_category'], 'FOREX')
