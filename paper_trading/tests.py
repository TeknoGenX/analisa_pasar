#paper_trading/tests.py
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from data_ingestion.models import MarketInstrument, MarketData
from paper_trading.models import VirtualAccount, AutoTradeSetting, PaperTrade
from paper_trading.services import (
    get_or_create_default_account,
    open_paper_trade,
    close_paper_trade,
    evaluate_open_positions,
    reset_virtual_account,
)


class PaperTradingTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.account = get_or_create_default_account()
        self.instrument = MarketInstrument.objects.create(
            symbol='EURUSD=X',
            name='Euro / US Dollar',
            market_category='FOREX',
            is_active=True
        )

        base_time = timezone.now()
        for i in range(20):
            MarketData.objects.create(
                instrument=self.instrument,
                timeframe='1m',
                timestamp=base_time - timedelta(minutes=20 - i),
                open_price=1.1000 + (i * 0.0001),
                high_price=1.1005 + (i * 0.0001),
                low_price=1.0995 + (i * 0.0001),
                close_price=1.1002 + (i * 0.0001),
                volume=100.0
            )

    def test_default_account_creation(self):
        self.assertIsNotNone(self.account)
        self.assertEqual(self.account.balance, 10000.0)
        self.assertEqual(self.account.currency, 'USD')
        self.assertIsNotNone(self.account.auto_setting)
        self.assertFalse(self.account.auto_setting.is_enabled)

    def test_open_buy_order_success(self):
        initial_balance = self.account.balance
        trade = open_paper_trade(
            account=self.account,
            instrument=self.instrument,
            order_type='BUY',
            amount=200.0,
            timeframe='1m',
            entry_price=1.1020,
            take_profit=1.1050,
            stop_loss=1.1000
        )

        self.assertEqual(trade.status, 'OPEN')
        self.assertEqual(trade.amount, 200.0)
        self.assertEqual(trade.entry_price, 1.1020)
        self.assertEqual(self.account.balance, initial_balance - 200.0)

    def test_open_order_insufficient_balance(self):
        self.account.balance = 50.0
        self.account.save()

        with self.assertRaises(ValueError):
            open_paper_trade(
                account=self.account,
                instrument=self.instrument,
                order_type='BUY',
                amount=100.0
            )

    def test_close_trade_manually_with_profit(self):
        trade = open_paper_trade(
            account=self.account,
            instrument=self.instrument,
            order_type='BUY',
            amount=100.0,
            entry_price=1.1000,
            take_profit=1.1050,
            stop_loss=1.0950
        )
        bal_before_close = self.account.balance

        # Harga naik ke 1.1025 (profit 50% dari jarak SL 0.0050)
        closed_trade = close_paper_trade(trade, exit_price=1.1025, reason='MANUAL')
        self.assertEqual(closed_trade.status, 'CLOSED_MANUAL')
        self.assertGreater(closed_trade.pnl, 0)
        self.assertEqual(closed_trade.pnl, 50.0)
        self.assertEqual(self.account.balance, bal_before_close + 100.0 + 50.0)

    def test_evaluate_open_positions_hit_tp(self):
        trade = open_paper_trade(
            account=self.account,
            instrument=self.instrument,
            order_type='BUY',
            amount=100.0,
            entry_price=1.1000,
            take_profit=1.1050,
            stop_loss=1.0950
        )

        # Buat candle baru yang menembus TP (High = 1.1060)
        now = timezone.now()
        MarketData.objects.create(
            instrument=self.instrument,
            timeframe='1m',
            timestamp=now,
            open_price=1.1020,
            high_price=1.1060,
            low_price=1.1010,
            close_price=1.1055,
            volume=50.0
        )

        closed_count = evaluate_open_positions()
        self.assertEqual(closed_count, 1)

        trade.refresh_from_db()
        self.assertEqual(trade.status, 'CLOSED_TP')
        self.assertEqual(trade.exit_price, 1.1050)
        self.assertGreater(trade.pnl, 0)

    def test_evaluate_open_positions_hit_sl(self):
        trade = open_paper_trade(
            account=self.account,
            instrument=self.instrument,
            order_type='BUY',
            amount=100.0,
            entry_price=1.1000,
            take_profit=1.1050,
            stop_loss=1.0950
        )

        # Buat candle baru yang menembus SL (Low = 1.0940)
        now = timezone.now()
        MarketData.objects.create(
            instrument=self.instrument,
            timeframe='1m',
            timestamp=now,
            open_price=1.0980,
            high_price=1.0990,
            low_price=1.0940,
            close_price=1.0945,
            volume=50.0
        )

        closed_count = evaluate_open_positions()
        self.assertEqual(closed_count, 1)

        trade.refresh_from_db()
        self.assertEqual(trade.status, 'CLOSED_SL')
        self.assertEqual(trade.exit_price, 1.0950)
        self.assertLess(trade.pnl, 0)

    def test_account_stats_and_reset(self):
        # 1 trade win
        t1 = open_paper_trade(self.account, self.instrument, 'BUY', 100.0, entry_price=1.1000, take_profit=1.1050, stop_loss=1.0950)
        close_paper_trade(t1, exit_price=1.1050, reason='TP')

        # 1 trade loss
        t2 = open_paper_trade(self.account, self.instrument, 'BUY', 100.0, entry_price=1.1000, take_profit=1.1050, stop_loss=1.0950)
        close_paper_trade(t2, exit_price=1.0950, reason='SL')

        stats = self.account.get_stats()
        self.assertEqual(stats['total_trades'], 2)
        self.assertEqual(stats['win_trades'], 1)
        self.assertEqual(stats['loss_trades'], 1)
        self.assertEqual(stats['win_rate'], 50.0)

        # Reset akun
        reset_virtual_account(self.account, initial_balance=10000.0)
        self.assertEqual(self.account.balance, 10000.0)
        self.assertEqual(self.account.trades.count(), 0)

    def test_api_create_order_view(self):
        response = self.client.post(
            reverse('paper_trading:create_order'),
            {
                'symbol': 'EURUSD=X',
                'order_type': 'BUY',
                'amount': '150',
                'timeframe': '1m',
                'take_profit': '1.1080',
                'stop_loss': '1.0980',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['trade']['symbol'], 'EURUSD=X')
        self.assertEqual(data['trade']['amount'], 150.0)

    def test_api_account_status(self):
        response = self.client.get(reverse('paper_trading:account_status'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('account', data)
        self.assertIn('stats', data)
        self.assertIn('open_trades', data)
        self.assertIn('closed_trades', data)

    def test_toggle_auto_trade(self):
        response = self.client.post(
            reverse('paper_trading:toggle_auto_trade'),
            {'enabled': 'true', 'trade_amount': '250', 'min_probability': '75'}
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_enabled'])
        self.assertEqual(data['trade_amount'], 250.0)
        self.assertEqual(data['min_probability'], 75)

    def test_equity_includes_used_margin_when_trade_open(self):
        last_c = self.instrument.price_data.order_by('-timestamp').first()
        current_close = last_c.close_price

        # Membuka order senilai 500 pada harga penutupan terakhir
        trade = open_paper_trade(
            account=self.account,
            instrument=self.instrument,
            order_type='BUY',
            amount=500.0,
            timeframe='1m',
            entry_price=current_close,
        )
        # Saldo kas berkurang 500
        self.assertEqual(self.account.balance, 9500.0)
        # Ekuitas tidak boleh defisit 500; harus tetap 10000.0 saat floating PnL 0
        self.assertEqual(self.account.equity, 10000.0)

        # Verifikasi via API account status
        response = self.client.get(reverse('paper_trading:account_status'))
        self.assertEqual(response.status_code, 200)
        acc_data = response.json()['account']
        self.assertEqual(acc_data['balance'], 9500.0)
        self.assertEqual(acc_data['equity'], 10000.0)

    def test_evaluate_open_positions_ignores_past_candles(self):
        # Buat candle di masa lalu dengan high sangat tinggi (1.2000)
        past_time = timezone.now() - timedelta(minutes=5)
        MarketData.objects.create(
            instrument=self.instrument,
            timeframe='1m',
            timestamp=past_time,
            open_price=1.1000,
            high_price=1.2000,
            low_price=1.0900,
            close_price=1.1005,
            volume=50.0
        )

        # Buka order sekarang dengan TP 1.1500 (di bawah high lilin masa lalu 1.2000)
        trade = open_paper_trade(
            account=self.account,
            instrument=self.instrument,
            order_type='BUY',
            amount=100.0,
            entry_price=1.1005,
            take_profit=1.1500,
            stop_loss=1.0800
        )

        # Evaluasi posisi tidak boleh menutup trade karena candle masa lalu mendahului entry_time
        closed_count = evaluate_open_positions()
        self.assertEqual(closed_count, 0)
        trade.refresh_from_db()
        self.assertEqual(trade.status, 'OPEN')
