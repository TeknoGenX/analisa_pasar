from django.db import models
from django.utils import timezone


class VirtualAccount(models.Model):
    """
    Model Akun Virtual untuk Paper Trading (Simulasi Tanpa Risiko).
    Menyimpan saldo, ekuitas, dan melacak performa trading.
    """
    name = models.CharField(max_length=100, default='Akun Simulasi Utama')
    currency = models.CharField(max_length=10, default='USD')
    initial_balance = models.FloatField(default=10000.0, help_text="Saldo modal awal (default $10,000)")
    balance = models.FloatField(default=10000.0, help_text="Saldo kas yang tersedia")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - ${self.balance:,.2f} {self.currency}"

    @property
    def equity(self):
        """Menghitung total ekuitas (Saldo Kas + Floating P&L dari posisi terbuka)"""
        open_trades = self.trades.filter(status='OPEN')
        floating_total = 0.0
        for trade in open_trades:
            # Ambil harga candle terbaru dari database jika tersedia
            last_candle = trade.instrument.price_data.filter(timeframe=trade.timeframe).order_by('-timestamp').first()
            if last_candle:
                floating_total += trade.calculate_floating_pnl(last_candle.close_price)
        return round(self.balance + floating_total, 2)

    def get_stats(self):
        """Menghitung statistik trading historis (Win Rate, Total Profit/Loss, dsb.)"""
        closed_trades = self.trades.exclude(status='OPEN')
        total = closed_trades.count()
        if total == 0:
            return {
                'total_trades': 0,
                'win_trades': 0,
                'loss_trades': 0,
                'win_rate': 0.0,
                'net_pnl': 0.0,
                'gross_profit': 0.0,
                'gross_loss': 0.0,
                'profit_factor': 0.0,
                'roi_percent': 0.0,
            }

        wins = closed_trades.filter(pnl__gt=0).count()
        losses = closed_trades.filter(pnl__lt=0).count()
        win_rate = round((wins / total) * 100, 1)

        gross_profit = sum(t.pnl for t in closed_trades.filter(pnl__gt=0))
        gross_loss = abs(sum(t.pnl for t in closed_trades.filter(pnl__lt=0)))
        net_pnl = round(gross_profit - gross_loss, 2)

        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (round(gross_profit, 2) if gross_profit > 0 else 1.0)
        roi_percent = round(((self.balance - self.initial_balance) / self.initial_balance) * 100, 2)

        return {
            'total_trades': total,
            'win_trades': wins,
            'loss_trades': losses,
            'win_rate': win_rate,
            'net_pnl': net_pnl,
            'gross_profit': round(gross_profit, 2),
            'gross_loss': round(gross_loss, 2),
            'profit_factor': profit_factor,
            'roi_percent': roi_percent,
        }


class AutoTradeSetting(models.Model):
    """
    Konfigurasi Eksekusi Otomatis (Auto-Trade) saat sinyal kuantitatif kuat muncul.
    """
    account = models.OneToOneField(VirtualAccount, related_name='auto_setting', on_delete=models.CASCADE)
    is_enabled = models.BooleanField(default=False, help_text="Aktifkan eksekusi otomatis sinyal STRONG")
    trade_amount = models.FloatField(default=100.0, help_text="Nominal modal per posisi ($)")
    min_probability = models.IntegerField(default=70, help_text="Ambang batas probabilitas minimal (%)")
    only_strong_signals = models.BooleanField(default=True, help_text="Hanya eksekusi sinyal STRONG BUY/SELL")
    max_open_positions = models.IntegerField(default=5, help_text="Maksimal posisi terbuka bersamaan")
    use_atr_tp_sl = models.BooleanField(default=True, help_text="Otomatis gunakan target TP/SL ATR 14")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        status = "AKTIF" if self.is_enabled else "NONAKTIF"
        return f"Auto-Trade [{status}] - ${self.trade_amount}/posisi (Min {self.min_probability}%)"


class PaperTrade(models.Model):
    """
    Catatan Transaksi Posisi Paper Trading (Buku Jurnal Transaksi).
    """
    ORDER_TYPES = [
        ('BUY', 'BUY / LONG (Prediksi Naik)'),
        ('SELL', 'SELL / SHORT (Prediksi Turun)'),
    ]

    STATUS_CHOICES = [
        ('OPEN', 'Posisi Terbuka'),
        ('CLOSED_TP', 'Tutup - Target Untung (TP)'),
        ('CLOSED_SL', 'Tutup - Batas Rugi (SL)'),
        ('CLOSED_MANUAL', 'Tutup - Manual Trader'),
    ]

    account = models.ForeignKey(VirtualAccount, related_name='trades', on_delete=models.CASCADE)
    instrument = models.ForeignKey('data_ingestion.MarketInstrument', related_name='paper_trades', on_delete=models.CASCADE)
    order_type = models.CharField(max_length=10, choices=ORDER_TYPES)
    timeframe = models.CharField(max_length=5, default='1m')
    
    entry_price = models.FloatField(help_text="Harga saat posisi dibuka")
    amount = models.FloatField(default=100.0, help_text="Alokasi modal untuk posisi ini ($)")
    
    take_profit = models.FloatField(null=True, blank=True, help_text="Level harga Take Profit (TP)")
    stop_loss = models.FloatField(null=True, blank=True, help_text="Level harga Stop Loss (SL)")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN', db_index=True)
    entry_time = models.DateTimeField(default=timezone.now, db_index=True)
    
    exit_price = models.FloatField(null=True, blank=True)
    exit_time = models.DateTimeField(null=True, blank=True)
    exit_reason = models.CharField(max_length=100, blank=True, default='')
    
    pnl = models.FloatField(default=0.0, help_text="Keuntungan/Kerugian bersih ($)")
    pnl_percent = models.FloatField(default=0.0, help_text="Persentase PnL (%)")
    
    is_auto_trade = models.BooleanField(default=False, help_text="Dibuka otomatis oleh bot sinyal")
    signal_info = models.CharField(max_length=100, blank=True, default='')
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-entry_time']
        indexes = [
            models.Index(fields=['account', 'status', '-entry_time']),
        ]

    def __str__(self):
        return f"[{self.status}] {self.order_type} {self.instrument.symbol} @ {self.entry_price} (${self.amount})"

    def calculate_floating_pnl(self, current_price):
        """
        Menghitung floating PnL posisi terbuka berdasarkan harga pasar saat ini.
        Menggunakan model kalkulasi Risk/Reward unit (ATR based) atau delta proporsional.
        """
        if not current_price or self.entry_price <= 0:
            return 0.0

        if self.order_type == 'BUY':
            price_delta = current_price - self.entry_price
            if self.stop_loss and self.stop_loss < self.entry_price:
                sl_distance = self.entry_price - self.stop_loss
                pnl = self.amount * (price_delta / sl_distance)
            else:
                pnl = self.amount * (price_delta / self.entry_price * 10)
        else: # SELL
            price_delta = self.entry_price - current_price
            if self.stop_loss and self.stop_loss > self.entry_price:
                sl_distance = self.stop_loss - self.entry_price
                pnl = self.amount * (price_delta / sl_distance)
            else:
                pnl = self.amount * (price_delta / self.entry_price * 10)

        # Batasi potensi kerugian maksimal sebesar modal yang dipertaruhkan (anti-negative balance)
        if pnl < -self.amount:
            pnl = -self.amount

        return round(pnl, 2)
