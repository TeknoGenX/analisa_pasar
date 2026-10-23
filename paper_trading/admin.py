#paper_trading/admin.py
from django.contrib import admin
from .models import VirtualAccount, AutoTradeSetting, PaperTrade


@admin.register(VirtualAccount)
class VirtualAccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'balance', 'currency', 'is_active', 'created_at')
    search_fields = ('name',)
    list_filter = ('is_active', 'currency')


@admin.register(AutoTradeSetting)
class AutoTradeSettingAdmin(admin.ModelAdmin):
    list_display = ('account', 'is_enabled', 'trade_amount', 'min_probability', 'only_strong_signals', 'max_open_positions')
    list_filter = ('is_enabled', 'only_strong_signals')


@admin.register(PaperTrade)
class PaperTradeAdmin(admin.ModelAdmin):
    list_display = ('id', 'instrument', 'order_type', 'timeframe', 'entry_price', 'exit_price', 'amount', 'pnl', 'status', 'is_auto_trade', 'entry_time')
    list_filter = ('status', 'order_type', 'is_auto_trade', 'timeframe')
    search_fields = ('instrument__symbol', 'signal_info', 'notes')
    readonly_fields = ('entry_time', 'exit_time')
