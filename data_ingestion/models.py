#data_ingestion/models.py
from django.db import models
from django.utils import timezone

class MarketInstrument(models.Model):
    CATEGORY_CHOICES = [
        ('FOREX', 'Forex'),
        ('CRYPTO', 'Cryptocurrency'),
        ('STOCK', 'Saham'),
        ('COMMODITY', 'Komoditas'),
    ]

    SOURCE_CHOICES = [
        ('YAHOO', 'Yahoo Finance'),
        ('IQOPTION', 'IQ Option'),
    ]

    symbol = models.CharField(max_length=20, unique=True, help_text="Contoh yfinance: EURUSD=X, BTC-USD, AAPL")
    name = models.CharField(max_length=100, help_text="Nama aset (contoh: Euro / US Dollar)")
    market_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='FOREX')
    data_source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='YAHOO', help_text="Sumber penyedia data feed (Yahoo Finance atau IQ Option)")
    is_active = models.BooleanField(default=True, help_text="Jika aktif, Celery akan rutin menarik data ini")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.symbol} ({self.get_market_category_display()} - {self.get_data_source_display()})"

class MarketData(models.Model):
    TIMEFRAME_CHOICES = [
        ('1m', '1 Menit'),
        ('5m', '5 Menit'),
        ('15m', '15 Menit'),
        ('30m', '30 Menit'),
        ('1h', '1 Jam'),
        ('1d', '1 Hari'),
        ('1wk', '1 Minggu'),
        ('1mo', '1 Bulan'),
    ]

    instrument = models.ForeignKey(MarketInstrument, on_delete=models.CASCADE, related_name='price_data')
    timeframe = models.CharField(max_length=5, choices=TIMEFRAME_CHOICES, default='1d', help_text="Pilih kerangka waktu (timeframe)")
    data_source = models.CharField(max_length=20, choices=MarketInstrument.SOURCE_CHOICES, default='YAHOO')
    timestamp = models.DateTimeField(db_index=True)
    open_price = models.FloatField()
    high_price = models.FloatField()
    low_price = models.FloatField()
    close_price = models.FloatField()
    volume = models.FloatField(default=0)

    class Meta:
        # Menjaga keunikan data berdasarkan instrumen, timeframe, dan waktu
        unique_together = ('instrument', 'timeframe', 'data_source', 'timestamp')
        ordering = ['-timestamp']
        # Index komposit untuk mempercepat kueri analitik Pandas berdasarkan instrumen, timeframe, dan waktu
        indexes = [
            models.Index(fields=['instrument', 'timeframe', '-timestamp']),
        ]

    def __str__(self):
        return f"[{self.get_timeframe_display()}] {self.instrument.symbol} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"