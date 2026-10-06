from django.contrib import admin
from .models import MarketInstrument, MarketData

@admin.register(MarketInstrument)
class MarketInstrumentAdmin(admin.ModelAdmin):
    list_display = ('symbol', 'name', 'market_category', 'is_active', 'created_at')
    list_filter = ('market_category', 'is_active')
    search_fields = ('symbol', 'name')
    list_editable = ('is_active',)

@admin.register(MarketData)
class MarketDataAdmin(admin.ModelAdmin):
    list_display = ('instrument', 'timeframe', 'timestamp', 'close_price', 'volume')
    list_filter = ('timeframe', 'instrument', 'timestamp')
    date_hierarchy = 'timestamp'
    
    # HAPUS baris readonly_fields dan fungsi has_add_permission 
    # agar Anda bisa menambahkan dan mengedit data harga secara manual via web.