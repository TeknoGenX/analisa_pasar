# trading_dashboard/tests.py
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from data_ingestion.models import MarketInstrument, MarketData

class DashboardViewsTestCase(TestCase):
    from unittest.mock import patch

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

    @patch('data_ingestion.tasks.fetch_iqoption_prices')
    def test_prediction_source_selection_fetches_iqoption_data(self, mock_fetch_iq):
        response = self.client.get(
            reverse('trading_dashboard:main_dashboard')
            + '?symbol=EURUSD=X&tf=1m&source=IQOPTION'
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_data_source'], 'IQOPTION')
        mock_fetch_iq.assert_called_once_with(
            timeframe='1m', symbols=['EURUSD=X']
        )
        self.assertIn('Sumber Data Prediksi', response.content.decode('utf-8'))

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

    def test_category_export_csv_only_includes_selected_category(self):
        crypto = MarketInstrument.objects.create(
            symbol='BTC-USD',
            name='Bitcoin',
            market_category='CRYPTO',
            is_active=True
        )
        base_time = timezone.now()
        for i in range(25):
            MarketData.objects.create(
                instrument=crypto,
                timeframe='1d',
                timestamp=base_time - timedelta(days=25 - i),
                open_price=30000 + i,
                high_price=30100 + i,
                low_price=29900 + i,
                close_price=30050 + i,
                volume=100.0
            )

        response = self.client.get(
            reverse('trading_dashboard:export_csv') + '?category=FOREX&tf=1d'
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'attachment; filename="analisa_pasar_FOREX_1d.csv"',
            response['Content-Disposition']
        )
        content = response.content.decode('utf-8')
        self.assertIn('EURUSD=X', content)
        self.assertNotIn('BTC-USD', content)

    @patch('data_ingestion.tasks.fetch_market_prices')
    def test_single_market_sync_redirect(self, mock_fetch):
        response = self.client.get(reverse('trading_dashboard:sync_data') + '?symbol=EURUSD=X&tf=1m')
        self.assertEqual(response.status_code, 302)
        self.assertIn('symbol=EURUSD=X', response.url)
        self.assertIn('tf=1m', response.url)
        mock_fetch.assert_called_once_with(timeframe='1m', symbols=['EURUSD=X'])

    @patch('data_ingestion.tasks.fetch_iqoption_prices')
    def test_single_market_sync_iqoption_redirect(self, mock_fetch_iq):
        inst_otc = MarketInstrument.objects.create(
            symbol='EURUSD-OTC',
            name='EUR/USD (OTC)',
            market_category='FOREX',
            data_source='IQOPTION',
            is_active=True
        )
        response = self.client.get(reverse('trading_dashboard:sync_data') + '?symbol=EURUSD-OTC&tf=1m')
        self.assertEqual(response.status_code, 302)
        self.assertIn('symbol=EURUSD-OTC', response.url)
        self.assertIn('tf=1m', response.url)
        mock_fetch_iq.assert_called_once_with(timeframe='1m', symbols=['EURUSD-OTC'])

    def test_category_filter(self):
        response = self.client.get(reverse('trading_dashboard:main_dashboard') + '?category=FOREX&tf=1d')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_category'], 'FOREX')

    def test_interactive_chart_rendering_and_components(self):
        import json
        response = self.client.get(reverse('trading_dashboard:main_dashboard') + '?symbol=EURUSD=X&tf=1d')
        self.assertEqual(response.status_code, 200)
        self.assertIn('chart_data_json', response.context)
        
        # Verifikasi payload JSON grafik
        chart_data = json.loads(response.context['chart_data_json'])
        self.assertIn('candles', chart_data)
        self.assertIn('ema_9', chart_data)
        self.assertIn('ema_21', chart_data)
        self.assertIn('atr_upper', chart_data)
        self.assertIn('atr_lower', chart_data)
        self.assertIn('rsi', chart_data)
        self.assertIn('macd', chart_data)
        self.assertIn('volume', chart_data)
        self.assertIn('markers', chart_data)
        self.assertEqual(len(chart_data['candles']), 25)
        self.assertEqual(len(chart_data['atr_upper']), 25)
        self.assertEqual(len(chart_data['atr_lower']), 25)

        # Verifikasi elemen visual TradingView pada HTML
        html = response.content.decode('utf-8')
        self.assertIn('id="tvChartCard"', html)
        self.assertIn('id="tradingviewMainChart"', html)
        self.assertIn('id="tradingviewOscChart"', html)
        self.assertIn('id="btnToggleEma9"', html)
        self.assertIn('id="btnToggleEma21"', html)
        self.assertIn('id="btnToggleAtr"', html)
        self.assertIn('id="btnToggleVol"', html)
        self.assertIn('id="btnToggleMarkers"', html)
        self.assertIn('id="btnOscRsi"', html)
        self.assertIn('id="btnOscMacd"', html)
        self.assertIn('id="rawCandleTableCollapse"', html)

    def test_base_template_includes_bootstrap_bundle_and_charts_js(self):
        response = self.client.get(reverse('trading_dashboard:main_dashboard'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn('bootstrap.bundle.min.js', html)
        self.assertIn('lightweight-charts', html)
        self.assertIn('fa-chart-line', html)
        self.assertIn('btn-outline-purple', html)
        self.assertIn('btn-outline-teal', html)

    def test_resolve_instrument_with_idx_stocks(self):
        from trading_dashboard.views import resolve_instrument

        # Pastikan instrumen sampel ada di database
        samples = [
            ('MGLV.JK', 'NexAI Digital Infrastruktur Tbk', 'STOCK'),
            ('TRUE.JK', 'Triniti Dinamik Tbk', 'STOCK'),
            ('LABA.JK', 'Green Power Group Tbk', 'STOCK'),
            ('BATA.JK', 'Sepatu Bata Tbk', 'STOCK'),
            ('BAYU.JK', 'Bayu Buana Tbk', 'STOCK'),
            ('BBCA.JK', 'Bank Central Asia Tbk', 'STOCK'),
            ('TLKM.JK', 'Telkom Indonesia (Persero) Tbk', 'STOCK'),
        ]
        for sym, name, cat in samples:
            MarketInstrument.objects.get_or_create(
                symbol=sym,
                defaults={'name': name, 'market_category': cat, 'is_active': True}
            )

        # 1. Resolusi via simbol ticker
        self.assertEqual(resolve_instrument('MGLV').symbol, 'MGLV.JK')
        self.assertEqual(resolve_instrument('mglv').symbol, 'MGLV.JK')
        self.assertEqual(resolve_instrument('MGLV.JK').symbol, 'MGLV.JK')

        # 2. Resolusi via nama perusahaan dari prompt (termasuk sufiks Tb dan Tbk.)
        self.assertEqual(resolve_instrument('NexAI Digital Infrastruktur Tb').symbol, 'MGLV.JK')
        self.assertEqual(resolve_instrument('Triniti Dinamik Tbk.').symbol, 'TRUE.JK')
        self.assertEqual(resolve_instrument('Green Power Group Tbk.').symbol, 'LABA.JK')
        self.assertEqual(resolve_instrument('Sepatu Bata Tbk.').symbol, 'BATA.JK')
        self.assertEqual(resolve_instrument('Bayu Buana Tbk').symbol, 'BAYU.JK')

        # 3. Resolusi via prefix PT dan (Persero)
        self.assertEqual(resolve_instrument('PT Bank Central Asia Tbk.').symbol, 'BBCA.JK')
        self.assertEqual(resolve_instrument('PT. Telkom Indonesia (Persero) Tbk.').symbol, 'TLKM.JK')

        # 4. Resolusi format gabungan datalist 'MGLV.JK - NexAI...'
        self.assertEqual(
            resolve_instrument('MGLV.JK - NexAI Digital Infrastruktur Tbk').symbol,
            'MGLV.JK'
        )

    def test_search_instruments_api(self):
        MarketInstrument.objects.get_or_create(
            symbol='MGLV.JK',
            defaults={'name': 'NexAI Digital Infrastruktur Tbk', 'market_category': 'STOCK', 'is_active': True}
        )
        MarketInstrument.objects.get_or_create(
            symbol='TRUE.JK',
            defaults={'name': 'Triniti Dinamik Tbk', 'market_category': 'STOCK', 'is_active': True}
        )

        # Cari berdasarkan kode ticker
        resp = self.client.get(reverse('trading_dashboard:search_instruments_api') + '?q=MGLV')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(len(data['results']) >= 1)
        self.assertEqual(data['results'][0]['symbol'], 'MGLV.JK')

        # Cari berdasarkan nama perusahaan
        resp2 = self.client.get(reverse('trading_dashboard:search_instruments_api') + '?q=NexAI')
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertTrue(len(data2['results']) >= 1)
        self.assertEqual(data2['results'][0]['symbol'], 'MGLV.JK')

        # Cari dengan trailing 'Tbk.'
        resp3 = self.client.get(reverse('trading_dashboard:search_instruments_api') + '?q=Triniti Dinamik Tbk.')
        self.assertEqual(resp3.status_code, 200)
        data3 = resp3.json()
        self.assertTrue(len(data3['results']) >= 1)
        self.assertEqual(data3['results'][0]['symbol'], 'TRUE.JK')

        # Query kosong
        resp_empty = self.client.get(reverse('trading_dashboard:search_instruments_api') + '?q=')
        self.assertEqual(resp_empty.status_code, 200)
        self.assertEqual(resp_empty.json()['results'], [])

    def test_dashboard_renders_search_bar_and_idx_quick_pill(self):
        MarketInstrument.objects.get_or_create(
            symbol='MGLV.JK',
            defaults={'name': 'NexAI Digital Infrastruktur Tbk', 'market_category': 'STOCK', 'is_active': True}
        )
        response = self.client.get(reverse('trading_dashboard:main_dashboard'))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Verifikasi input search dan datalist ter-render
        self.assertIn('id="marketSearchInput"', html)
        self.assertIn('id="instrumentsDatalist"', html)

        # Verifikasi quick pill MGLV (NexAI) ter-render
        self.assertIn('MGLV (NexAI)', html)


